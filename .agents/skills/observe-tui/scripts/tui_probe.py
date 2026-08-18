"""PTY screen probe: run a CLI/TUI command in a pseudo-terminal and observe it.

Spawns COMMAND in a real PTY, feeds its output through an in-memory pyte
terminal emulator, and executes an ordered scenario of steps (wait for text,
send keys, snapshot the screen). The rendered screen is printed as plain text
so a human or AI agent can read exactly what a user would see.

This is a MANUAL/AGENT verification tool. It must never be imported by pytest
or wired into CI — see .claude/skills/observe-tui/SKILL.md.

Usage:
    uv run --with pyte python .claude/skills/observe-tui/scripts/tui_probe.py \
        [options] [--step SPEC ...] -- COMMAND [ARGS...]

Steps (executed in the order given; a final snapshot always prints at exit):
    --step wait:TEXT     block until TEXT appears anywhere on screen (--timeout)
    --step send:KEYS     write KEYS to the PTY; supports <enter> <tab> <esc>
                         <space> <backspace> <up> <down> <left> <right>
                         <home> <end> <pgup> <pgdn> <ctrl+X> tokens
    --step snap[:LABEL]  print the current screen
    --step sleep:SECS    let the app run for SECS seconds (output keeps feeding)

Examples:
    # Boot the inline TUI in an example project, confirm it renders
    uv run --with pyte python .claude/skills/observe-tui/scripts/tui_probe.py \
        --cwd examples/quickstart --step "wait:Type a command" -- uv run func

    # Type a command name and watch the result
    uv run --with pyte python .claude/skills/observe-tui/scripts/tui_probe.py \
        --cwd examples/quickstart --step "wait:Type a command" \
        --step "send:hello<enter>" --step sleep:2 -- uv run func

Exit codes: 0 = scenario completed; 2 = a wait: step timed out.
"""

from __future__ import annotations

import argparse
import os
import re
import select
import sys
import time

import ptyprocess
import pyte

NAMED_KEYS = {
    "enter": "\r",
    "tab": "\t",
    "esc": "\x1b",
    "escape": "\x1b",
    "space": " ",
    "backspace": "\x7f",
    "delete": "\x1b[3~",
    "up": "\x1b[A",
    "down": "\x1b[B",
    "right": "\x1b[C",
    "left": "\x1b[D",
    "home": "\x1b[H",
    "end": "\x1b[F",
    "pgup": "\x1b[5~",
    "pgdn": "\x1b[6~",
}


def encode_keys(spec: str) -> bytes:
    """Translate a send: spec with <named> tokens into raw PTY bytes."""
    out: list[str] = []
    for token in re.split(r"(<[^<>]+>)", spec):
        if token.startswith("<") and token.endswith(">"):
            name = token[1:-1].lower()
            if name in NAMED_KEYS:
                out.append(NAMED_KEYS[name])
            elif name.startswith("ctrl+") and len(name) == 6:
                out.append(chr(ord(name[5].upper()) - 64))
            else:
                raise SystemExit(f"unknown key token {token!r} in send spec")
        else:
            out.append(token)
    return "".join(out).encode()


class Probe:
    def __init__(self, command: list[str], cwd: str, cols: int, rows: int) -> None:
        env = dict(os.environ)
        env.update(
            {
                "TERM": "xterm-256color",
                "COLORTERM": "truecolor",
                "COLUMNS": str(cols),
                "LINES": str(rows),
            }
        )
        self.proc = ptyprocess.PtyProcess.spawn(
            command, dimensions=(rows, cols), cwd=cwd, env=env
        )
        self.screen = pyte.Screen(cols, rows)
        self.stream = pyte.ByteStream(self.screen)
        self.cols = cols
        self.feed_errors: list[str] = []
        self.eof = False

    def _pump(self, poll: float) -> None:
        """Read any pending PTY output (waiting up to poll seconds) into pyte."""
        ready, _, _ = select.select([self.proc.fd], [], [], poll)
        if not ready:
            return
        try:
            data = os.read(self.proc.fd, 65536)
        except OSError:
            self.eof = True
            return
        if not data:
            self.eof = True
            return
        try:
            self.stream.feed(data)
        except Exception as exc:  # noqa: BLE001 — diagnostic tool, report and continue
            self.feed_errors.append(repr(exc))

    def run_for(self, seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end and not self.eof:
            self._pump(0.05)

    def on_screen(self, text: str) -> bool:
        return any(text in line for line in self.screen.display)

    def wait_for(self, text: str, timeout: float) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if self.on_screen(text):
                return True
            if self.eof:
                break
            self._pump(0.1)
        return self.on_screen(text)

    def send(self, data: bytes) -> None:
        self.proc.write(data)
        self.run_for(0.3)  # let the app react before the next step

    def snapshot(self, label: str) -> None:
        ruler = "─" * self.cols
        print(f"┌{ruler}┐  {label}")
        lines = [line.rstrip() for line in self.screen.display]
        while lines and not lines[-1]:
            lines.pop()
        for line in lines:
            print(f"│{line.ljust(self.cols)}│")
        print(f"└{ruler}┘")
        status = "exited" if self.eof or not self.proc.isalive() else "running"
        print(
            f"  cursor=({self.screen.cursor.x},{self.screen.cursor.y})"
            f"  process={status}  feed_errors={self.feed_errors[:3]}"
        )

    def close(self) -> None:
        try:
            if self.proc.isalive():
                self.proc.terminate(force=True)
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--cwd", default=".", help="working directory for COMMAND")
    parser.add_argument("--cols", type=int, default=100)
    parser.add_argument("--rows", type=int, default=30)
    parser.add_argument(
        "--timeout", type=float, default=20.0, help="timeout per wait: step (seconds)"
    )
    parser.add_argument(
        "--step",
        action="append",
        default=[],
        dest="steps",
        metavar="SPEC",
        help="scenario step: wait:TEXT | send:KEYS | snap[:LABEL] | sleep:SECS",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER, metavar="-- COMMAND")
    args = parser.parse_args()

    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("no COMMAND given (put it after --)")

    probe = Probe(command, args.cwd, args.cols, args.rows)
    timed_out = False
    try:
        probe.run_for(1.0)  # initial paint
        for step in args.steps:
            kind, _, rest = step.partition(":")
            if kind == "wait":
                print(f"⏳ wait for {rest!r} (timeout {args.timeout}s)")
                if not probe.wait_for(rest, args.timeout):
                    print(f"✗ TIMEOUT: {rest!r} never appeared on screen")
                    timed_out = True
                    break
            elif kind == "send":
                print(f"⌨  send {rest!r}")
                probe.send(encode_keys(rest))
            elif kind == "snap":
                probe.snapshot(rest or "snapshot")
            elif kind == "sleep":
                probe.run_for(float(rest))
            else:
                raise SystemExit(f"unknown step kind {kind!r}")
        probe.snapshot("final screen")
    finally:
        probe.close()
    return 2 if timed_out else 0


if __name__ == "__main__":
    sys.exit(main())
