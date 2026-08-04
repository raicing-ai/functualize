"""Surface-stack routing: event fan-out ordering and stack-scoped collect."""

from __future__ import annotations

import contextlib
from types import SimpleNamespace

from functualize._engine.capabilities.tty import TTY
from functualize._engine.surface_routing import active_collector, iter_fanout_surfaces


class _Render:
    def __init__(self, name: str, terminal: bool = True) -> None:
        self.name = name
        self.needs_terminal = terminal

    def handle_event(self, event: object) -> None:  # Surface
        pass


class _Collector(_Render):
    def collect(self, request: object) -> object:  # + PromptCollector
        return None


def _app(surfaces: list, stack: list) -> SimpleNamespace:
    return SimpleNamespace(_surfaces=surfaces, _surface_stack=stack)


# --- fan-out ordering -------------------------------------------------------


def test_fanout_registered_then_stacked() -> None:
    # A headless stacked surface does not open an exclusive window, so all
    # surfaces receive in registered-then-stacked order.
    a, b = _Render("a"), _Render("b")
    c = _Render("c", terminal=False)
    out = iter_fanout_surfaces(_app([a, b], [c]))
    assert out == [a, b, c]


def test_fanout_skips_terminal_surfaces_during_exclusive_window() -> None:
    panel = _Render("panel", terminal=True)
    logfile = _Render("logfile", terminal=False)  # headless
    exclusive = _Render("job-app", terminal=True)  # pushed, owns the terminal

    out = iter_fanout_surfaces(_app([panel, logfile], [exclusive]))
    # The registered terminal panel is skipped; the headless log and the
    # active exclusive surface both receive.
    assert panel not in out
    assert logfile in out
    assert exclusive in out


def test_fanout_no_exclusive_window_delivers_to_all() -> None:
    panel = _Render("panel", terminal=True)
    logfile = _Render("logfile", terminal=False)
    out = iter_fanout_surfaces(_app([panel, logfile], []))
    assert set(out) == {panel, logfile}


# --- collect resolution -----------------------------------------------------


def test_active_collector_prefers_registered_collector() -> None:
    coll = _Collector("bar")
    assert active_collector(_app([_Render("panel"), coll], [])) is coll


def test_active_collector_top_of_stack_wins() -> None:
    registered = _Collector("registered")
    stacked = _Collector("stacked")
    assert active_collector(_app([registered], [stacked])) is stacked


# --- TTY.run pushes the app as the active surface ---------------------------


def test_tty_run_pushes_and_pops_surface_app() -> None:
    stack: list = []
    funcapp = SimpleNamespace(
        _surfaces=[],
        _surface_stack=stack,
        push_surface=lambda s: stack.append(s),
        pop_surface=lambda s=None: stack.pop(),
    )

    class _App(_Render):
        def __init__(self) -> None:
            super().__init__("job-app")
            self.on_stack_during_run: bool | None = None

        def run(self) -> str:
            # While the app runs it must be the active surface.
            self.on_stack_during_run = self in stack
            return "done"

    app = _App()
    tty = TTY(caps={}, available=True, funcapp=funcapp)
    assert tty.run(app) == "done"
    assert app.on_stack_during_run is True
    assert stack == []  # popped in finally


def test_tty_run_pops_on_exception() -> None:
    stack: list = []
    funcapp = SimpleNamespace(
        _surfaces=[],
        _surface_stack=stack,
        push_surface=lambda s: stack.append(s),
        pop_surface=lambda s=None: stack.pop(),
    )

    class _App(_Render):
        def __init__(self) -> None:
            super().__init__("job-app")

        def run(self) -> None:
            raise RuntimeError("boom")

    tty = TTY(caps={}, available=True, funcapp=funcapp)
    with contextlib.suppress(RuntimeError):
        tty.run(_App())
    assert stack == []  # unwound despite the crash
