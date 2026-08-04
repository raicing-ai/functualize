"""Terminal Orchestrator: Textual ↔ ExecutionRuntime — clean handoff.

Run with:
    uv run python experiments/offscreen_textual/experiment.py

Architecture:
    The orchestrator sits ABOVE both Textual and the execution runtime.
    It runs them sequentially — each fully owns the terminal when active.

    ┌─────────────────────────────────────────────────────┐
    │ Orchestrator loop:                                   │
    │   1. Textual inline app (command selection)          │
    │      → exits with chosen command or "quit"           │
    │   2. Execution runtime (Rich + stdin + signals)      │
    │      → returns result                                │
    │   3. Loop back to 1 with result in state             │
    └─────────────────────────────────────────────────────┘

    No file swaps. No thread killing. No driver hacks.
    Each phase gets exclusive, clean terminal access.

Try:
- Select a command and press Enter to execute
- At the prompt: type yes/no + Enter
- Ctrl+C during execution cancels gracefully
- Select 'quit' to exit
"""

from __future__ import annotations

import os
import signal
import sys
import termios
import time
import tty
from dataclasses import dataclass, field


# ═══════════════════════════════════════════════════════════════════════════
# Interactive Select (arrow key menu for prompts)
# ═══════════════════════════════════════════════════════════════════════════


def interactive_select(choices: list[str], console=None) -> str:
    """Display an interactive menu with arrow key navigation.

    Uses raw terminal input for arrow keys + Enter.
    Renders with ANSI escape codes (cursor movement to update in place).
    Raises KeyboardInterrupt on Ctrl+C.
    """
    selected = 0
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    def _render(idx: int, first: bool = False) -> None:
        """Render the choices, highlighting the selected one."""
        if not first:
            # Move cursor up to overwrite previous render
            sys.stdout.write(f"\033[{len(choices)}A")

        for i, choice in enumerate(choices):
            sys.stdout.write("\r\033[K")  # Clear line
            if i == idx:
                sys.stdout.write(f"  \033[1;32m❯ {choice}\033[0m\n")
            else:
                sys.stdout.write(f"    \033[2m{choice}\033[0m\n")
        sys.stdout.flush()

    def _read_key() -> str:
        """Read a single key or escape sequence."""
        ch = os.read(fd, 1)
        if ch == b'\x03':  # Ctrl+C
            raise KeyboardInterrupt
        if ch == b'\x1b':  # Escape sequence
            ch2 = os.read(fd, 1)
            if ch2 == b'[':
                ch3 = os.read(fd, 1)
                if ch3 == b'A':
                    return "up"
                elif ch3 == b'B':
                    return "down"
            return "escape"
        if ch in (b'\r', b'\n'):
            return "enter"
        if ch == b'k':
            return "up"
        if ch == b'j':
            return "down"
        return ch.decode("utf-8", errors="ignore")

    try:
        tty.setraw(fd)
        sys.stdout.write("\033[?25l")  # Hide cursor
        sys.stdout.flush()
        _render(selected, first=True)

        while True:
            key = _read_key()
            if key == "up":
                selected = (selected - 1) % len(choices)
                _render(selected)
            elif key == "down":
                selected = (selected + 1) % len(choices)
                _render(selected)
            elif key == "enter":
                return choices[selected]
    finally:
        sys.stdout.write("\033[?25h")  # Show cursor
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


# ═══════════════════════════════════════════════════════════════════════════
# Shared State (persists across Textual/Execution sessions)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class AppState:
    """State that persists between shell and execution phases."""

    run_history: list[dict] = field(default_factory=list)
    available_commands: list[str] = field(default_factory=lambda: [
        "deploy", "migrate", "build", "test", "rollback"
    ])


# ═══════════════════════════════════════════════════════════════════════════
# Phase 1: Textual Shell (command selection)
# ═══════════════════════════════════════════════════════════════════════════


def run_textual_shell(state: AppState) -> str | None:
    """Run Textual inline app for command selection.

    Returns the chosen command string, or None if user quits.
    Textual fully owns the terminal during this phase.
    """
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.widgets import Footer, Static, OptionList
    from textual.widgets.option_list import Option

    class ShellApp(App[str | None]):
        """Inline command selector."""

        CSS = """
        Screen { height: auto; }
        #header { background: $primary; color: $text; padding: 0 1; height: 1; }
        #history { height: auto; max-height: 4; padding: 0 1; color: $text-muted; }
        OptionList { height: auto; min-height: 3; max-height: 8; padding: 0 1; }
        #hint { padding: 0 1; height: 1; color: $text-muted; }
        """

        BINDINGS = [
            Binding("q", "quit_app", "Quit"),
        ]

        def compose(self) -> ComposeResult:
            yield Static(" ⚙ func — select a command", id="header")

            # Show last result if any
            if state.run_history:
                last = state.run_history[-1]
                icon = "✓" if last["status"] == "success" else "⊘" if last["status"] == "cancelled" else "✗"
                history_text = f"  Last: {icon} {last['command']} → {last['status']}"
                if last.get("prompt_answer"):
                    history_text += f" (prompt: '{last['prompt_answer']}')"
                yield Static(history_text, id="history")

            # Command list
            options = [Option(cmd) for cmd in state.available_commands]
            options.append(Option("quit", id="quit"))
            yield OptionList(*options, id="commands")
            yield Static(" ↑↓ select, Enter execute, q quit", id="hint")
            yield Footer()

        def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
            selected = event.option.prompt
            if selected == "quit":
                self.exit(None)
            else:
                self.exit(str(selected))

        def action_quit_app(self) -> None:
            self.exit(None)

    app = ShellApp()
    return app.run(inline=True)


# ═══════════════════════════════════════════════════════════════════════════
# Phase 2: Execution Runtime (Rich + stdin)
# ═══════════════════════════════════════════════════════════════════════════


def run_execution(command: str) -> dict:
    """Execute a command with Rich visualization + real stdin prompts.

    Fully owns the terminal. Uses Rich Console, Rich Live, and input().
    Ctrl+C works natively (SIGINT in cooked mode).
    Returns a result dict.
    """
    from rich.console import Console, Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.tree import Tree

    console = Console()
    result = {"command": command, "status": "success", "prompt_answer": None, "steps": 0}

    cancelled = False
    original_sigint = signal.getsignal(signal.SIGINT)

    def _on_sigint(sig, frame):
        nonlocal cancelled
        cancelled = True

    signal.signal(signal.SIGINT, _on_sigint)

    try:
        console.print()
        console.print(Panel.fit(
            f"[bold]Executing:[/bold] {command}",
            border_style="blue",
        ))
        console.print()

        # ─── Simulate execution steps with scrollback + live ──────────

        steps_for_command = {
            "deploy": [("migrate", 0.4), ("build", 0.5), ("sync", 0.4), ("verify", 0.3)],
            "migrate": [("backup", 0.3), ("apply", 0.6), ("verify", 0.3)],
            "build": [("clean", 0.2), ("compile", 0.7), ("bundle", 0.4)],
            "test": [("lint", 0.3), ("unit", 0.5), ("integration", 0.6)],
            "rollback": [("snapshot", 0.3), ("revert", 0.4), ("verify", 0.3)],
        }

        steps = steps_for_command.get(command, [("run", 1.0)])
        total = len(steps)

        def _tree(done_count):
            d, r, p = "[green]✓[/green]", "[yellow]⏳[/yellow]", "[dim]○[/dim]"
            root_icon = d if done_count >= total else r
            t = Tree(f"  {root_icon} [bold]{command}[/bold]")
            for i, (name, _) in enumerate(steps):
                if i < done_count:
                    t.add(f"{d} {name}")
                elif i == done_count:
                    t.add(f"{r} {name}")
                else:
                    t.add(f"{p} {name}")
            return t

        def _bar(done_count):
            tbl = Table.grid(padding=(0, 1))
            f = int(25 * done_count / total) if total else 25
            tbl.add_row(f"  [{'█' * f}{'░' * (25 - f)}] {done_count}/{total}")
            return tbl

        with Live(Group(_tree(0), _bar(0)), console=console,
                  refresh_per_second=4, vertical_overflow="visible") as live:
            for i, (step_name, duration) in enumerate(steps):
                if cancelled:
                    break
                # Scrollback log
                console.print(f"  [green]●[/green] {step_name}: running...")
                time.sleep(duration / 2)
                if cancelled:
                    break
                console.print(f"  [green]●[/green] {step_name}: done")
                # Update live tree
                live.update(Group(_tree(i + 1), _bar(i + 1)))
                time.sleep(duration / 2)
                result["steps"] = i + 1

        if cancelled:
            result["status"] = "cancelled"
            console.print()
            console.print("  [bold red]✗ CANCELLED[/bold red] (Ctrl+C)")
            console.print()
            return result

        console.print()
        console.print("  [green]●[/green] All steps complete!")
        console.print()

        # ─── Prompt (interactive select!) ─────────────────────────────
        # Restore default SIGINT so Ctrl+C raises KeyboardInterrupt
        signal.signal(signal.SIGINT, original_sigint)

        console.print("  ┌─────────────────────────────────────────────────┐")
        console.print(f"  │ [yellow]⚠[/yellow]  Confirm {command}?                              │")
        console.print("  │ Use ↑↓ arrows to select, Enter to confirm       │")
        console.print("  │ (Ctrl+C to cancel)                              │")
        console.print("  └─────────────────────────────────────────────────┘")
        console.print()

        try:
            answer = interactive_select(
                choices=["Yes, proceed", "No, abort"],
                console=console,
            )
            result["prompt_answer"] = answer
            if answer == "Yes, proceed":
                console.print(f"  [green]✓[/green] Confirmed: [bold]yes[/bold]")
            else:
                console.print(f"  [red]✗[/red] Declined: [bold]no[/bold]")
                result["status"] = "declined"
        except (KeyboardInterrupt, EOFError):
            console.print("\n  [yellow]⊘[/yellow] Cancelled")
            result["status"] = "cancelled"
            result["prompt_answer"] = "(cancelled)"
            return result

        # ─── Final ───────────────────────────────────────────────────
        console.print()
        console.print("  [green]●[/green] Finalizing...")
        time.sleep(0.3)
        console.print()
        console.print(Panel.fit(
            f"[bold green]✓ {command} complete[/bold green] — "
            f"{result['steps']} steps, prompt: '{result['prompt_answer']}'",
            border_style="green",
        ))

    finally:
        signal.signal(signal.SIGINT, original_sigint)

    console.print()
    time.sleep(0.5)
    return result


# ═══════════════════════════════════════════════════════════════════════════
# Orchestrator (main loop)
# ═══════════════════════════════════════════════════════════════════════════


def main():
    """Orchestrator loop: Textual → Execution → Textual → ..."""
    state = AppState()

    print("\n  Terminal Orchestrator — Textual ↔ Rich Execution Runtime")
    print("  ─────────────────────────────────────────────────────────\n")
    time.sleep(0.5)

    while True:
        # Phase 1: Textual shell (command selection)
        command = run_textual_shell(state)

        if command is None:
            print("\n  Goodbye!\n")
            break

        # Phase 2: Execution runtime
        result = run_execution(command)

        # Store result for next shell session
        state.run_history.append(result)

        # Brief pause before next Textual session
        print("\n  [Press any key or wait 2s for shell to return...]\n")
        time.sleep(2.0)


if __name__ == "__main__":
    main()
