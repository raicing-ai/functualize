"""Tests for sh.defer() and background=True (S2/T14, §B.5).

Deferred commands unwind LIFO on the engine's job-exit path — on success,
failure, and Ctrl+C — not via user try/finally.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from functualize._engine.capabilities.shell import WiredShell
from functualize._engine.executor import JobExecutionEngine
from functualize._events.bus import EventBus
from functualize._events.hooks import HookRegistry

# Keep at runtime: the DI engine resolves this annotation via get_type_hints.
from functualize.job import Shell  # noqa: TC001


@pytest.fixture
def sh() -> WiredShell:
    return WiredShell()


class TestDeferMechanics:
    def test_defer_does_not_run_immediately(self, sh: WiredShell, tmp_path) -> None:
        marker = tmp_path / "cleanup"
        sh.defer(["touch", str(marker)])
        assert not marker.exists()

    def test_run_deferred_executes(self, sh: WiredShell, tmp_path) -> None:
        marker = tmp_path / "cleanup"
        sh.defer(["touch", str(marker)])
        sh.run_deferred()
        assert marker.exists()

    def test_defers_run_lifo(self, sh: WiredShell, tmp_path) -> None:
        log = tmp_path / "order.txt"
        sh.defer(f"echo first >> {log}", shell=True)
        sh.defer(f"echo second >> {log}", shell=True)
        sh.run_deferred()
        # Registered first, second → runs second, first.
        assert log.read_text().split() == ["second", "first"]

    def test_run_deferred_clears_the_stack(self, sh: WiredShell, tmp_path) -> None:
        counter = tmp_path / "n.txt"
        sh.defer(f"echo x >> {counter}", shell=True)
        sh.run_deferred()
        sh.run_deferred()  # second unwind must be a no-op
        assert counter.read_text().count("x") == 1

    def test_failing_defer_does_not_stop_the_rest(
        self, sh: WiredShell, tmp_path
    ) -> None:
        marker = tmp_path / "still-ran"
        sh.defer(["touch", str(marker)])  # registered first → runs last
        sh.defer(["this-command-does-not-exist-xyz"])
        sh.run_deferred()  # must not raise
        assert marker.exists()

    def test_failing_defer_does_not_raise(self, sh: WiredShell) -> None:
        sh.defer(["false"])
        sh.run_deferred()  # check defaults to False for cleanups


class TestBackground:
    def test_background_returns_immediately(self, sh: WiredShell) -> None:
        import time

        start = time.perf_counter()
        r = sh(["sleep", "5"], background=True)
        assert time.perf_counter() - start < 2  # did not wait for the sleep
        assert r.pid is not None
        assert r.returncode == 0  # "started", not "succeeded"

    def test_background_can_be_torn_down_by_defer(
        self, sh: WiredShell, tmp_path
    ) -> None:
        marker = tmp_path / "torn-down"
        sh(["sleep", "30"], background=True)
        sh.defer(["touch", str(marker)])
        sh.run_deferred()
        assert marker.exists()

    def test_background_missing_executable_reports_127(self, sh: WiredShell) -> None:
        r = sh(["this-command-does-not-exist-xyz"], background=True)
        assert r.returncode == 127


class TestEngineOwnedUnwind:
    """The engine runs defers at job exit — success, failure, and Ctrl+C."""

    def _engine(self) -> JobExecutionEngine:
        di_registry = MagicMock()
        di_registry.available_types.return_value = set()
        middleware_chain = MagicMock()
        middleware_chain.has_middleware = False
        return JobExecutionEngine(
            di_registry=di_registry,
            hook_registry=HookRegistry(),
            middleware_chain=middleware_chain,
            event_bus=EventBus(),
        )

    def test_defers_run_on_success(self, tmp_path) -> None:
        marker = tmp_path / "on-success"

        def my_job(sh: Shell) -> str:
            sh.defer(["touch", str(marker)])  # type: ignore[attr-defined]
            return "ok"

        result = self._engine().execute("my_job", my_job, kwargs={})
        assert result.return_value == "ok"
        assert marker.exists()

    def test_defers_run_on_failure(self, tmp_path) -> None:
        marker = tmp_path / "on-failure"

        def my_job(sh: Shell) -> None:
            sh.defer(["touch", str(marker)])  # type: ignore[attr-defined]
            raise RuntimeError("boom")

        self._engine().execute("my_job", my_job, kwargs={})
        assert marker.exists()

    def test_defers_run_on_keyboard_interrupt(self, tmp_path) -> None:
        from functualize.types import RunStatus

        marker = tmp_path / "on-interrupt"

        def my_job(sh: Shell) -> None:
            sh.defer(["touch", str(marker)])  # type: ignore[attr-defined]
            raise KeyboardInterrupt

        # The engine reports Ctrl+C as a FAILURE result carrying the
        # KeyboardInterrupt (it does not propagate) — and the defers still run.
        result = self._engine().execute("my_job", my_job, kwargs={})
        assert result.status is RunStatus.FAILURE
        assert isinstance(result.exception, KeyboardInterrupt)
        assert marker.exists()
