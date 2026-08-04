"""TTY and Live per-invocation capabilities: behavior + engine wiring.

Covers the two capability classes directly (TTY.run refusal/dispatch, the
degrading Live handles) and their integration with the executor: a job that
declares ``tty: TTY`` / ``live: Live`` must not be flagged as a missing DI
provider, and the per-invocation factory must construct them.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from functualize._engine.capabilities.live import Live, LiveHandle
from functualize._engine.capabilities.tty import TTY, terminal_available
from functualize._engine.executor import JobExecutionEngine
from functualize._engine.result import RegisteredJob
from functualize._primitives.di import DIRegistry
from functualize._types.errors import TerminalUnavailable

# --- TTY behavior -----------------------------------------------------------


def test_tty_run_refuses_when_unavailable() -> None:
    tty = TTY(caps={}, available=False)
    with pytest.raises(TerminalUnavailable) as exc:
        tty.run(MagicMock())
    assert "terminal" in str(exc.value).lower()


def test_tty_run_dispatches_to_app_when_available() -> None:
    app = MagicMock()
    app.run.return_value = 42
    tty = TTY(caps={}, available=True)
    assert tty.run(app) == 42
    app.run.assert_called_once_with()


def test_tty_run_rejects_non_runnable_app() -> None:
    tty = TTY(caps={}, available=True)
    with pytest.raises(TypeError):
        tty.run(object())  # no .run() method


def test_tty_ctx_resolves_runcontext_from_caps() -> None:
    from functualize._engine.capabilities.runcontext import RunContext

    rc = MagicMock(spec=RunContext)
    caps: dict[type, object] = {RunContext: rc}
    tty = TTY(caps=caps, available=True)
    assert tty.ctx is rc


def test_tty_ctx_is_none_without_runcontext_param() -> None:
    tty = TTY(caps={}, available=True)
    assert tty.ctx is None


# --- Live behavior (degrading kernel handles) -------------------------------


class _Construct:
    def __rich__(self) -> str:
        return "x"


def test_live_add_returns_noop_handle_in_kernel() -> None:
    live = Live()
    handle = live.add(_Construct())
    assert isinstance(handle, LiveHandle)
    # No bound surface — every method is a no-op that must not raise.
    handle.update()
    handle.push()
    handle.remove()


def test_live_panel_returns_noop_handle_in_kernel() -> None:
    live = Live()
    handle = live.panel(_Construct())
    assert isinstance(handle, LiveHandle)
    handle.update()


def test_live_delegates_to_bound_zone_when_present() -> None:
    zone = MagicMock()
    live = Live(_zone=zone)
    construct = _Construct()

    live.add(construct)
    zone.add.assert_called_once_with(construct)

    live.panel(construct)
    zone.panel.assert_called_once_with(construct)


def test_live_handle_forwards_to_bound_surface_handle() -> None:
    bound = MagicMock()
    handle = LiveHandle(_Construct(), _bound=bound)
    handle.update()
    bound.update.assert_called_once_with()
    handle.remove()
    bound.remove.assert_called_once_with()


def test_terminal_available_is_bool() -> None:
    # In the test harness stdin/stdout are usually not TTYs; either way it is a
    # bool and does not raise.
    assert isinstance(terminal_available(), bool)


# --- Executor integration ---------------------------------------------------


def _make_engine() -> JobExecutionEngine:
    mw = MagicMock()
    mw.has_middleware = False
    return JobExecutionEngine(
        di_registry=DIRegistry(),
        hook_registry=MagicMock(),
        middleware_chain=mw,
        event_bus=MagicMock(),
    )


def _register(engine: JobExecutionEngine, name: str, fn: object) -> None:
    engine.register_job(
        RegisteredJob(
            name=name,
            function=fn,
            config_class=None,
            group=None,
            module_path="test_module",
            job_directory=Path("."),
        )
    )


def test_tty_and_live_are_not_missing_providers() -> None:
    """A job declaring tty/live must pass DI validation (per-invocation types)."""
    engine = _make_engine()

    def job(tty: TTY, live: Live) -> None: ...

    _register(engine, "job", job)
    # Should not raise — TTY/Live are engine per-invocation types, not DI providers.
    engine.validate_di_bindings()


def test_factory_constructs_tty_and_live() -> None:
    engine = _make_engine()
    context = MagicMock()
    caps: dict[type, object] = {}

    tty = engine._create_per_invocation_cap(TTY, context, caps)
    assert isinstance(tty, TTY)

    live = engine._create_per_invocation_cap(Live, context, caps)
    assert isinstance(live, Live)


# --- Regression: the executor's plan classifies tty/live as injectable -------


class TestPlanClassifiesCapabilities:
    """The plan-building path must route tty/live to DI, not skip them.

    Regression for a gap the unit tests above missed: the factory + validation
    were wired, but _get_resolution_plan seeds a SEPARATE per-invocation set —
    without TTY/Live there, a `live: Live` / `tty: TTY` param was classified
    "skip" and never injected (TypeError: missing argument at runtime).
    """

    def test_live_and_tty_params_are_di_not_skip(self) -> None:
        engine = _make_engine()

        def job(live: Live, tty: TTY) -> None: ...

        plan = engine._get_resolution_plan(job)
        by_name = {b.name: b.source for b in plan.params}
        assert by_name["live"] == "di"
        assert by_name["tty"] == "di"

    def test_optional_tty_is_di(self) -> None:
        engine = _make_engine()

        def job(live: Live, tty: TTY | None = None) -> None: ...

        plan = engine._get_resolution_plan(job)
        by_name = {b.name: b.source for b in plan.params}
        assert by_name["tty"] == "di"
        assert by_name["live"] == "di"
