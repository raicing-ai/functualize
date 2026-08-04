"""The engine records every top-level run, and only those (T42).

`func builtin history` answers "what has run here lately?" — but only if the
engine actually writes a record, on every way a run can end. So this pins the
producer at the level that matters (the real execution path, not a store unit
test) and pins the two decisions that keep the ring useful rather than noisy:

* **Both outcomes are recorded.** A history that only shows successes is a
  history you cannot debug from — the failed run is the one you came looking
  for.
* **Only top-level runs are recorded.** A workflow step, a dependency, and an
  `rc.invoke` child all run one level deeper, and recording them would bury the
  handful of things the user launched under the internals of one of them — a
  single deep workflow could evict all real history from the 200-record ring.

Secrets never enter the ring: only the `args_hash` is stored, so a record
identifies a run without persisting its inputs.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from functualize._app.state import AppState
from functualize.app.core import FunctualizeApp
from functualize.app.utils import StateStore


@pytest.fixture(autouse=True)
def _in_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    (tmp_path / ".functualize").mkdir()
    monkeypatch.chdir(tmp_path)
    AppState.reset()
    yield
    AppState.reset()


def _history(tmp_path: Path) -> list[dict]:
    return StateStore.for_project(tmp_path).get_history()


def _app() -> FunctualizeApp:
    app = FunctualizeApp(name="histtest")

    def ok() -> str:
        return "fine"

    def boom() -> str:
        raise RuntimeError("nope")

    app.register_dynamic_job("ok", ok)
    app.register_dynamic_job("boom", boom)
    return app


class TestTheProducerWrites:
    def test_a_successful_run_is_recorded(self, tmp_path: Path) -> None:
        _app().execute("ok")

        history = _history(tmp_path)
        assert len(history) == 1
        assert history[0]["job"] == "ok"
        assert history[0]["status"] == "success"
        assert history[0]["namespace"] == "job"

    def test_a_failed_run_is_recorded_too(self, tmp_path: Path) -> None:
        """The record you actually need when something breaks."""
        _app().execute("boom")

        history = _history(tmp_path)
        assert len(history) == 1
        assert history[0]["job"] == "boom"
        assert history[0]["status"] == "failure"

    def test_the_record_carries_a_hash_and_never_the_arguments(
        self, tmp_path: Path
    ) -> None:
        app = FunctualizeApp(name="histtest")

        def greet(name: str = "world") -> str:
            return name

        app.register_dynamic_job("greet", greet)
        app.execute("greet", name="s3cr3t")

        record = _history(tmp_path)[0]
        assert "args_hash" in record
        assert record["args_hash"]
        # The value must not appear anywhere in the persisted record.
        assert "s3cr3t" not in str(record)

    def test_the_record_carries_timing(self, tmp_path: Path) -> None:
        _app().execute("ok")

        assert isinstance(_history(tmp_path)[0]["duration_ms"], (int, float))


class TestOnlyTopLevelRuns:
    def test_an_invoked_child_is_not_recorded(self, tmp_path: Path) -> None:
        """`rc.invoke` runs a child one level deeper; only the launch counts.

        Recording invokes would let one workflow's internals evict every other
        run from the ring.
        """
        # Runtime import, not TYPE_CHECKING: the annotation `rc: RunContext` is
        # resolved at runtime for DI injection, so the name must be in the
        # module's runtime globals or `rc` is never injected and the test goes
        # vacuous again.
        from functualize.job import RunContext  # noqa: TC001

        app = FunctualizeApp(name="histtest")

        def child() -> str:
            return "c"

        def parent(rc: RunContext) -> str:
            # A genuine child run — if this does not actually execute, the test
            # would pass vacuously (there is no child record because there is no
            # child), so the return value is asserted below.
            result = rc.invoke("child")
            assert result.return_value == "c"
            return "p"

        app.register_dynamic_job("child", child)
        app.register_dynamic_job("parent", parent)
        assert app.execute("parent").status.value == "Success"

        history = _history(tmp_path)
        jobs = [r["job"] for r in history]
        assert jobs == ["parent"], f"the invoked child leaked into history: {jobs}"

    def test_the_ring_is_bounded(self, tmp_path: Path) -> None:
        """The store trims to HISTORY_LIMIT (200); a long-lived project must not
        grow state.json without bound."""
        from functualize._primitives.state_format import HISTORY_LIMIT

        app = _app()
        for _ in range(HISTORY_LIMIT + 15):
            app.execute("ok")

        assert len(_history(tmp_path)) == HISTORY_LIMIT


class TestHistoryDoesNotDisturbTheRun:
    def test_a_store_write_failure_is_swallowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """History is a convenience. A store that cannot be written must never
        turn a job that ran fine into a visible failure.

        `append_history` is the realistic failure (a full disk, a locked
        store); the recorder's guard wraps record-building *and* the write, so
        this exercises the whole guarded path.
        """
        from functualize._primitives import state_store as store_mod

        def _explode(self: object, record: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(store_mod.StateStore, "append_history", _explode)

        result = _app().execute("ok")

        assert result.status.value == "Success"
