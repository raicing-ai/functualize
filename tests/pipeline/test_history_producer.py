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

Secrets never enter history: only the `args_hash` is stored, so a record
identifies a run without persisting its inputs.

**Retargeted by `durable-run-layer`/T3b.** The ring in `state.json` is gone;
job history is now *derived* from the run log, because the log already recorded
every one of those runs plus the nested ones plus who invoked them. Only the
`_history` helper below changed — every rule this file pins is asserted through
the derivation instead of the writer, and they all held. That is the evidence
the move preserved the semantics rather than the claim that it did.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from functualize._app.state import AppState
from functualize._primitives.run_store import RunStore
from functualize.app.core import FunctualizeApp, request_for
from functualize.app.utils import job_history


@pytest.fixture(autouse=True)
def _in_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    (tmp_path / ".functualize").mkdir()
    monkeypatch.chdir(tmp_path)
    AppState.reset()
    yield
    AppState.reset()


def _history(tmp_path: Path) -> list[dict]:
    """What `func builtin history` shows for jobs — derived from the run log."""
    return job_history(RunStore.for_project(tmp_path))


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
        _app().execute(request_for("ok"))

        history = _history(tmp_path)
        assert len(history) == 1
        assert history[0]["job"] == "ok"
        assert history[0]["status"] == "success"
        assert history[0]["namespace"] == "job"

    def test_a_failed_run_is_recorded_too(self, tmp_path: Path) -> None:
        """The record you actually need when something breaks."""
        _app().execute(request_for("boom"))

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
        app.execute(request_for("greet", name="s3cr3t"))

        record = _history(tmp_path)[0]
        assert "args_hash" in record
        assert record["args_hash"]
        # The value must not appear anywhere in the persisted record.
        assert "s3cr3t" not in str(record)

    def test_the_record_carries_timing(self, tmp_path: Path) -> None:
        _app().execute(request_for("ok"))

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
        assert app.execute(request_for("parent")).status.value == "Success"

        history = _history(tmp_path)
        jobs = [r["job"] for r in history]
        assert jobs == ["parent"], f"the invoked child leaked into history: {jobs}"

    def test_a_top_level_parallel_batch_records_every_item(
        self, tmp_path: Path
    ) -> None:
        """`func builtin parallel a b` is the user launching a and b (AC-18, #5).

        The items run one level down — `Invoke.parallel` gives each
        `invoke_depth=1` — so the plain depth rule recorded neither, and
        `func builtin history` came back empty for a command that had just run
        two jobs. Mechanically nested, but not nested *work*.
        """
        app = _app()

        results = app.execute_parallel(["ok", "boom"])

        # Assert the batch actually ran, so an empty history cannot pass here
        # vacuously — the same trap the invoked-child test above guards.
        assert [r.job_name for r in results] == ["ok", "boom"]

        jobs = sorted(r["job"] for r in _history(tmp_path))
        assert jobs == ["boom", "ok"], f"a parallel item is missing: {jobs}"

    def test_a_batch_launched_inside_a_job_is_still_nested(
        self, tmp_path: Path
    ) -> None:
        """Surface alone is not the rule — depth *and* surface are.

        `rc.invoke_parallel(...)` inside a job produces the same
        `invoke.parallel` surface, but those items really are internals: the
        parent is already in the ring, and a fan-out from inside a job is
        exactly what would evict real history. Widening on surface alone would
        have reintroduced the eviction the depth rule exists to prevent.
        """
        from functualize.job import RunContext  # noqa: TC001

        app = _app()

        captured: list = []

        def fanout(rc: RunContext) -> str:
            # Tuples, not bare names: `invoke_parallel` takes
            # (job, kwargs) pairs. Passing plain strings made this test
            # vacuous once already — the items never ran, so "no history
            # records" meant "nothing happened", not "nesting was respected".
            results = rc.invoke_parallel([("ok", {}), ("ok", {})])
            captured.extend(results)
            return "done"

        app.register_dynamic_job("fanout", fanout)
        outcome = app.execute(request_for("fanout"))
        assert outcome.status.value == "Success", outcome.exception
        # The items must have really run, or the history assertion below is a
        # test of nothing.
        assert [r.status.value for r in captured] == ["Success", "Success"], captured

        jobs = [r["job"] for r in _history(tmp_path)]
        assert jobs == ["fanout"], f"a nested parallel item leaked in: {jobs}"

    def test_history_is_bounded(self, tmp_path: Path) -> None:
        """A long-lived project must not grow its log without bound.

        The bound moved with the data: the ring's own `HISTORY_LIMIT` (200) is
        gone, and history is now capped by whatever the run log keeps —
        `RUNS_LIMIT` (500). Larger, and correctly so: one cap now covers both
        questions, and the run log is the thing that has to stay bounded.
        """
        from functualize._primitives.run_format import RUNS_LIMIT

        app = _app()
        for _ in range(RUNS_LIMIT + 15):
            app.execute(request_for("ok"))

        assert len(_history(tmp_path)) == RUNS_LIMIT


class TestHistoryDoesNotDisturbTheRun:
    def test_a_store_write_failure_is_swallowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """History is a convenience. A store that cannot be written must never
        turn a job that ran fine into a visible failure.

        `RunStore.open_run` is the realistic failure now (a full disk, a
        locked store) — the ring's `append_history` is gone, and opening the
        run record is what took its place as the write on the run's path. The
        engine's guard wraps it, so this exercises the whole guarded path.
        """
        from functualize._primitives import run_store as store_mod

        def _explode(self: object, record: object) -> str:
            raise OSError("disk full")

        monkeypatch.setattr(store_mod.RunStore, "open_run", _explode)

        result = _app().execute(request_for("ok"))

        assert result.status.value == "Success"
