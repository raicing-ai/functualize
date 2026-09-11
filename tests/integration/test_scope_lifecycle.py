"""A scope reaches a terminal status when the run that minted it ends.

`scope-record-lifecycle`/T1, AC-3. Before this, a plain job that called
`rc.state.set(...)` wrote a record with ``status: "running"`` and nothing ever
changed it — so `purge_scopes` refused it, the age filter refused it for having
no timestamps, and `list_scopes` hid it. The record was immortal *and*
invisible, which is how `scopes.json` reached 2,188 records with no way to
drain it.

Every assertion here reads the **store on disk**, not the engine's in-memory
scope cache. A test that asked the `WorkflowScope` object whether it felt
closed would pass without a single byte changing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from functualize import FunctualizeApp, RunContext
from functualize._engine.capabilities.state import State  # noqa: TC001
from functualize._primitives.scope_format import resolve_scopes_path
from functualize._primitives.scope_store import ScopeStore
from functualize._types.run_request import RunRequest


def _records() -> dict[str, Any]:
    """Every scope record on disk, read fresh."""
    path = resolve_scopes_path(Path.cwd())
    if not path.exists():
        return {}
    return json.loads(path.read_text()).get("scopes", {})


def _only_record() -> dict[str, Any]:
    """The single record a one-run test produced."""
    records = _records()
    assert len(records) == 1, f"expected exactly one scope record, got {len(records)}"
    return next(iter(records.values()))


class TestAPlainJobsScopeIsFinished:
    """The defect AC-3 names: a non-workflow run left its record running."""

    def test_a_successful_run_leaves_a_completed_record(self) -> None:
        app = FunctualizeApp(name="finishes")

        def writes(rc: RunContext, state: State) -> str:
            state.set("k", 1)
            return "ok"

        app.register_dynamic_job("writes", writes)
        assert (
            app.execute(
                RunRequest(job_name="writes", surface="app.execute")
            ).status.value
            == "Success"
        )

        assert _only_record()["status"] == "completed"

    def test_a_failing_run_leaves_a_failed_record(self) -> None:
        """Failure is terminal too — otherwise a crashed run is immortal.

        This is the path that matters most: a job that raises is exactly the
        one nobody goes back to tidy up.
        """
        app = FunctualizeApp(name="fails")

        def boom(rc: RunContext, state: State) -> str:
            state.set("k", 1)
            raise RuntimeError("nope")

        app.register_dynamic_job("boom", boom)
        result = app.execute(RunRequest(job_name="boom", surface="app.execute"))
        assert result.status.value != "Success"

        assert _only_record()["status"] == "failed"

    def test_a_finished_record_is_purgeable(self) -> None:
        """The consequence AC-3 exists for, asserted end to end.

        `purge_scopes` refuses a non-terminal record. Asserting the status is
        `"completed"` is asserting a string; asserting that purge *removes* it
        is asserting the thing the status was for.
        """
        from functualize.app._workflow_control import purge_scopes

        app = FunctualizeApp(name="purgeable")

        def writes(rc: RunContext, state: State) -> str:
            state.set("k", 1)
            return "ok"

        app.register_dynamic_job("writes", writes)
        app.execute(RunRequest(job_name="writes", surface="app.execute"))
        assert len(_records()) == 1

        store = ScopeStore(resolve_scopes_path(Path.cwd()))
        report = purge_scopes(store)

        assert report.get("removed"), f"purge removed nothing: {report}"
        assert _records() == {}

    def test_a_run_that_touches_no_state_writes_no_record(self) -> None:
        """Nothing is created just so it can be marked finished.

        Minting an empty record to close it would grow the file for runs that
        had nothing to store — the exact growth this feature removes.
        """
        app = FunctualizeApp(name="quiet")

        def quiet(rc: RunContext) -> str:
            return "ok"

        app.register_dynamic_job("quiet", quiet)
        app.execute(RunRequest(job_name="quiet", surface="app.execute"))

        assert _records() == {}


class TestALiveScopeIsNeverFinished:
    """The guard, and the reason this change is safe.

    A workflow parked at a gate has status ``blocked``. Overwriting it would
    lose the resume point *and* seal the store the resumed walk writes to —
    turning a recoverable pause into a lost run. This is the failure durable
    state exists to prevent, so it is asserted directly rather than trusted to
    the `!= "running"` check being read correctly.

    **The block is set from inside the job**, which is how a real walk does it:
    the status is already ``blocked`` when the run ends, so `_close_scope` sees
    it and leaves both the record and the store alone. An earlier version of
    these tests set the status *after* the run had finished, which produced a
    state no walk can reach — a sealed scope object with a live record — and
    then "fixed" the engine to tolerate it. The scope caches were changed to
    treat a closed scope as absent, which silently broke the real guarantee
    that a closed scope refuses writes
    (`test_workflow_scope_close_prevents_mutation`). Both changes are gone;
    the lesson is that a test which has to manufacture an unreachable state is
    evidence about the test, not about the code.
    """

    @staticmethod
    def _block_mid_run(rc: RunContext) -> None:
        """Mark this run's scope blocked, as a walk stopping at a gate does."""
        ScopeStore(resolve_scopes_path(Path.cwd())).set_scope_status(
            rc._workflow_scope.scope_id, "blocked"
        )

    def test_a_blocked_record_survives_the_run_ending(self) -> None:
        app = FunctualizeApp(name="blocked-survives")

        def step(rc: RunContext, state: State) -> str:
            state.set("progress", "half")
            self._block_mid_run(rc)
            return "ok"

        app.register_dynamic_job("step", step)
        app.execute(RunRequest(job_name="step", surface="app.execute"))

        record = _only_record()
        assert record["status"] == "blocked", (
            "the run ended and overwrote a blocked scope — the resume point is gone"
        )

    def test_a_blocked_scopes_state_is_still_writable(self) -> None:
        """Not sealed either. `close()` seals the store; blocked must not.

        Status and sealing are two separate consequences of the same guard, and
        a change could plausibly get one right and the other wrong. Asserted by
        resuming: a second run naming the same scope must be able to write.
        """
        app = FunctualizeApp(name="blocked-writable")
        seen: dict[str, Any] = {}

        def step(rc: RunContext, state: State) -> str:
            state.set("count", (state.get("count") or 0) + 1)
            seen["count"] = state.get("count")
            self._block_mid_run(rc)
            return "ok"

        app.register_dynamic_job("step", step)
        app.execute(RunRequest(job_name="step", surface="app.execute"))
        scope_id = next(iter(_records()))

        result = app.execute(
            RunRequest(
                job_name="step",
                surface="app.execute",
                workflow_scope_id=scope_id,
            )
        )

        assert result.status.value == "Success", result.exception
        assert seen["count"] == 2, (
            "the second run could not write to the blocked scope's state — "
            "the store was sealed when it should not have been"
        )


class TestANamedScopeBelongsToItsCaller:
    """A run given a `workflow_scope_id` must not have that scope closed.

    The defect this class exists for: `owns_scope` was first defined as
    "arrived with no parent scope", which is true of a run that names a scope
    id without passing the object. So the **first** `execute` into a named
    scope sealed it, and the **second** failed — breaking the one thing durable
    state is for, carrying values across runs.

    Caught by `test_full_orchestration_flow`, whose second run asserts
    `invocation=2`. The rule is now: the engine closes only a scope it minted,
    meaning the run named neither an object nor an id.
    """

    def test_two_runs_in_one_named_scope_share_state(self) -> None:
        app = FunctualizeApp(name="named-scope")
        counts: list[int] = []

        def counter(rc: RunContext, state: State) -> str:
            nxt = (state.get("n") or 0) + 1
            state.set("n", nxt)
            counts.append(nxt)
            return "ok"

        app.register_dynamic_job("counter", counter)
        for _ in range(3):
            result = app.execute(
                RunRequest(
                    job_name="counter",
                    surface="app.execute",
                    workflow_scope_id="carried",
                )
            )
            assert result.status.value == "Success", result.exception

        assert counts == [1, 2, 3], (
            "the counter did not carry across runs — the named scope was "
            "closed by the run that used it"
        )

    def test_a_named_scope_is_left_running_for_its_caller_to_finish(
        self,
    ) -> None:
        """Not closed means not marked terminal either.

        The caller owns the lifetime, so the record stays live until something
        that owns it says otherwise. A named scope silently marked `completed`
        would be purgeable out from under the caller.
        """
        app = FunctualizeApp(name="named-stays-live")

        def writes(rc: RunContext, state: State) -> str:
            state.set("k", 1)
            return "ok"

        app.register_dynamic_job("writes", writes)
        app.execute(
            RunRequest(
                job_name="writes",
                surface="app.execute",
                workflow_scope_id="owned-elsewhere",
            )
        )

        assert _records()["owned-elsewhere"]["status"] == "running"


class TestOnlyTheMinterCloses:
    """A nested run must not finish a scope its parent still owns."""

    def test_an_invoked_child_leaves_the_parents_scope_running(self) -> None:
        """The child ends first; the parent is still working.

        Without the `owns_scope` guard the child's `finally` would mark the
        shared scope finished and seal it, and the parent's next `state.set`
        would raise — a failure that only appears when a job invokes another,
        which is most of them.
        """
        app = FunctualizeApp(name="parent-child")
        seen: dict[str, Any] = {}

        def child(rc: RunContext, state: State) -> str:
            state.set("child", "done")
            return "child-ok"

        def parent(rc: RunContext, state: State) -> str:
            state.set("parent", "started")
            rc.invoke("child")
            # If the child closed the scope, this write raises.
            state.set("parent", "finished")
            seen["after_invoke"] = state.get("parent")
            return "parent-ok"

        app.register_dynamic_job("child", child)
        app.register_dynamic_job("parent", parent)

        result = app.execute(RunRequest(job_name="parent", surface="app.execute"))

        assert result.status.value == "Success"
        assert seen["after_invoke"] == "finished"
        record = _only_record()
        assert record["status"] == "completed", (
            "one record, closed once, by the parent — a child closing it would "
            "have shown up as a sealed store above"
        )

    @pytest.mark.parametrize("key", ["parent", "child"])
    def test_both_runs_state_survives_in_one_scope(self, key: str) -> None:
        """Parent and child share the scope, so both writes are in it.

        Guards against the opposite over-correction: giving the child its own
        scope to keep it from closing the parent's.

        Read through the store rather than out of the record: T3 moved job
        state to a per-scope file, so `record["state"]` is no longer where it
        lives. An earlier version of this test read the record and had to be
        changed — which is the correct outcome, since the record is not the
        contract, `state_snapshot` is.
        """
        app = FunctualizeApp(name="shared-record")

        def child(rc: RunContext, state: State) -> str:
            state.set("child", "c")
            return "ok"

        def parent(rc: RunContext, state: State) -> str:
            state.set("parent", "p")
            rc.invoke("child")
            return "ok"

        app.register_dynamic_job("child", child)
        app.register_dynamic_job("parent", parent)
        app.execute(RunRequest(job_name="parent", surface="app.execute"))

        scope_id = next(iter(_records()))
        store = ScopeStore(resolve_scopes_path(Path.cwd()))
        assert key in store.state_snapshot(scope_id)
