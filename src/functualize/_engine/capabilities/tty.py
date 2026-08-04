"""TTY capability — terminal ownership for job-owned UIs.

A job that draws its own UI declares it in the signature::

    @job
    def config_editor(cfg: EditorConfig, tty: TTY) -> None:
        tty.run(ConfigEditorApp(ctx=tty.ctx, config=cfg))

``tty: TTY`` is a HARD requirement — harvested into the descriptor (so warm/lazy
boot routes the job to a handoff without importing it, and constrained contexts
refuse it pre-flight). ``tty: TTY | None`` is a preference (injected when
EXCLUSIVE is grantable, else None — surface resolution decides, Phase 5).

``tty.run(app)`` runs the job-owned app while it owns the terminal.
``tty.ctx`` is the RunContext — the sanctioned API handle for the app
(``invoke`` / ``log`` / ``prompt_*`` / ``emit``), deliberately NOT the
FunctualizeApp (boot/registration powers are the wrong object-capability grant).
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from functualize._types.errors import TerminalUnavailable

if TYPE_CHECKING:
    from functualize._engine.capabilities.runcontext import RunContext

__all__ = ["TTY", "terminal_available"]


class TTY:
    """Terminal-ownership capability delivered by DI to a job that owns its UI.

    You cannot obtain the handle without declaring the parameter, and you
    cannot declare the parameter without the router seeing it — one artifact
    serves both the static routing decision and the runtime handle.

    Args:
        caps: The per-invocation capability map; ``ctx`` resolves the
            RunContext from it lazily (so declaration order does not matter).
        available: Whether terminal ownership can be granted in this context.
    """

    def __init__(
        self, *, caps: dict[type, Any], available: bool, funcapp: Any = None
    ) -> None:
        self._caps = caps
        self._available = available
        self._funcapp = funcapp

    @property
    def ctx(self) -> RunContext | None:
        """The RunContext for this execution — the app's API handle.

        Resolved lazily from the per-invocation capability map, so it is
        populated by the time the job body runs regardless of parameter order.
        Returns None only if the job declared no ``rc: RunContext`` parameter
        (a fuller guarantee arrives with the Phase 5 orchestrator handoff).
        """
        from functualize._engine.capabilities.runcontext import RunContext

        return self._caps.get(RunContext)

    def run(self, app: Any) -> Any:
        """Run a job-owned app while it owns the terminal.

        Raises:
            TerminalUnavailable: If terminal ownership cannot be granted here
                (MCP / CI / piped / background).
            TypeError: If ``app`` is not runnable (no ``.run()`` method).
        """
        if not self._available:
            raise TerminalUnavailable(
                "This job needs an interactive terminal (it declares "
                "`tty: TTY`). Run it from `func` at a real TTY — it cannot run "
                "over MCP, in CI, or with piped I/O."
            )
        run = getattr(app, "run", None)
        if not callable(run):
            raise TypeError(
                "tty.run(app) expects a runnable app with a .run() method "
                "(e.g. a functualize.ui.TextualApp); got "
                f"{type(app).__name__}."
            )

        # A Surface-conforming app becomes the active surface for its window:
        # child rc.invoke() events fan out to it and nested prompts route to
        # its collect(). Popped in finally so a crash still unwinds the stack.
        from functualize._types.interactivity import Surface

        pushed = False
        if self._funcapp is not None and isinstance(app, Surface):
            self._funcapp.push_surface(app)
            pushed = True
        try:
            return run()
        finally:
            if pushed:
                self._funcapp.pop_surface(app)


def terminal_available() -> bool:
    """Whether an interactive terminal is available for EXCLUSIVE ownership.

    The capability floor: stdin and stdout must both be TTYs. This is the
    conservative Phase-3 signal; the Phase 5 orchestrator refines it with the
    resolved surface (e.g. a job selected inside the func TUI hands off to the
    main thread rather than reading isatty).
    """
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except Exception:
        return False
