"""Every entry into a walk says `running`, so a live resumed walk is visible.

`runtime-schema-migrations`/T3, decision D2 = 1. Spec AC-12, AC-15.

`FrontierWalk.start` stamped `RUNNING` on first entry only. A scope resumed
from `blocked` (a gate had just been answered) or from `failed` (a step had just
raised) kept that status for the walk's whole duration, while a runner was
mid-step. Three readers paid for it:

- `app/_workflow_view.list_scopes` showed `waiting` or `ready` — a parked-looking
  row — for a walk that was running;
- `app/_workflow_control.advanceable_scopes` listed the scope, but by accident:
  it qualifies on `blocked` being in `LIVE_STATUSES` rather than on anything the
  walk said;
- `FrontierWalk._step_that_went_silent`, which requires `running` before it will
  diagnose a step whose lease lapsed, could not see a resumed walk at all. That
  is the behaviour this change *creates*, and it is the one the third class
  below is about — not a correction of a wrong answer but a fact that was not
  there to read.

The stamp is unconditional, so the tests say what keeps a cancelled scope
cancelled: `resume_scope` refuses it before a walk exists, which the last class
asserts rather than assumes.
"""

from __future__ import annotations

from collections.abc import Generator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel
from tests._support.engine_storage import port_for

from functualize._app.state import AppState
from functualize._engine.frontier import (
    FrontierWalk,
    GraphModel,
    StepStatus,
    step_key,
)
from functualize._engine.workflow_walker import WorkflowWalker
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.workflow import WorkflowDeclaration
from functualize.app.core import FunctualizeApp
from functualize.app.utils import (
    advanceable_scopes,
    cancel_scope,
    list_scopes,
    resume_scope,
)
from functualize.types import RunRequest
from functualize.workflow import END, Edge, Gate, Step, workflow


class Approval(BaseModel):
    approved: bool


# ----------------------------------------------------------------------
# The engine-level fixtures: a store, and a walk over it
# ----------------------------------------------------------------------


@pytest.fixture
def engine_store(tmp_path: Path) -> ScopeStore:
    """A walk's store and nothing else.

    `FrontierWalk` and `WorkflowWalker` take a `ScopeStore` and no app, which is
    the whole of what the classes below need — the app-level half of this file
    builds its own, because there the *verb* (`resume_scope`) is the subject.
    """
    return ScopeStore(JsonFileSubstrate(tmp_path))


def _line() -> WorkflowDeclaration:
    """`first → second → END` — a failed step leaves a position on it."""
    return WorkflowDeclaration(
        nodes=(Step("first"), Step("second")),
        edges=(
            Edge(source="first", target="second"),
            Edge(source="second", target=END),
        ),
    )


def _gated_line() -> WorkflowDeclaration:
    """`first → hold → second → END`, with `hold` a gate.

    The gate is what makes a *resumed* position reachable with no step record
    under it: `block` sets the position to the gate and records no step there,
    so the walk that re-enters takes `FrontierWalk.start`'s resumed branch. A
    failed step leaves a position too, but it leaves a `failed` record under it,
    and `_step_that_went_silent` leaves a step that already reported alone.
    """
    return WorkflowDeclaration(
        nodes=(Step("first"), Gate(name="hold", awaits=Approval), Step("second")),
        edges=(
            Edge(source="first", target="hold"),
            Edge(source="hold", target="second"),
            Edge(source="second", target=END),
        ),
    )


def _walk(
    store: ScopeStore, declaration: WorkflowDeclaration, scope_id: str, run_step: Any
) -> Any:
    return WorkflowWalker(
        declaration, store, scope_id, run_step=run_step, runtime_store=port_for(store)
    ).run()


def _running(name: str) -> str:
    return name


def _failing_at(target: str) -> Any:
    def run_step(name: str) -> str:
        if name == target:
            raise RuntimeError(f"{name} blew up")
        return name

    return run_step


class _ProcessDied(BaseException):
    """What a step raises when the runner does not survive it.

    A `BaseException`, deliberately: `_service_step` catches `Exception`, so
    every ordinary failure stamps a status on its way out. This shape escapes
    that and reaches `run`'s `finally: release()` with nothing stamped — which
    is what a killed process leaves behind, produced here by the walk itself
    rather than written into the record by the test.
    """


def _dies_at(target: str) -> Any:
    def run_step(name: str) -> str:
        if name == target:
            raise _ProcessDied(name)
        return name

    return run_step


def _observing(
    store: ScopeStore, scope_id: str, names: list[str], statuses: list[Any]
) -> Any:
    """A `run_step` that notes what the scope said at the moment it ran.

    The reader is the walk's own store, so this is the record as the engine
    itself would see it — no second handle, no flush to wait on.
    """

    def run_step(name: str) -> str:
        names.append(name)
        scope = store.get_scope(scope_id) or {}
        statuses.append(scope.get("status"))
        return name

    return run_step


def _leave_mid_step(store: ScopeStore, scope_id: str, *, at: str, status: str) -> None:
    """A runner that stopped mid-step, as its record looks afterwards.

    Positioned, leased by a name that will never renew, and `status` — the one
    field the two tests using this helper vary, and the field this task is
    about. Written through the raw record because this is a process that died,
    not an operation the system offers: the same reason
    `tests/workflow/test_typed_step_outcomes._abandon` writes its own this way.

    `at` is a node a resumed walk would be on, which is what puts the record on
    the branch `FrontierWalk.start` changed.
    """
    store.ensure_scope(scope_id, "demo")
    store.set_scope_status(scope_id, status)
    store.set_position(scope_id, at)
    store.claim_scope(scope_id, owner="dead-runner", seconds=1)
    scope = store.get_scope(scope_id) or {}
    past = (datetime.now(UTC) - timedelta(seconds=600)).isoformat()
    lease = {**scope["lease"], "expires_at": past}
    store._mutate(  # noqa: SLF001
        lambda env: env["scopes"][scope_id].__setitem__("lease", lease)
    )


def _step_status(store: ScopeStore, scope_id: str, node: str) -> Any:
    record = store.get_step(scope_id, step_key(node, ""))
    return None if record is None else record.get("status")


# ----------------------------------------------------------------------
# The app-level fixtures: the `resume` verb, and a step that can look
# ----------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset() -> Generator[None]:
    AppState.reset()
    yield
    AppState.reset()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "project"
    (root / ".functualize").mkdir(parents=True)
    monkeypatch.chdir(root)
    return root


@pytest.fixture
def seen() -> list[dict[str, Any]]:
    """What each step could read about its own scope, at the moment it ran."""
    return []


@pytest.fixture
def calls() -> list[str]:
    return []


@pytest.fixture
def holder() -> dict[str, Any]:
    """Where the app parks itself so a job can reach it mid-walk."""
    return {}


@pytest.fixture
def app(
    project: Path, calls: list[str], seen: list[dict[str, Any]], holder: dict[str, Any]
) -> FunctualizeApp:
    instance = FunctualizeApp(name="testapp")

    def observe(step: str) -> None:
        """Read the scope the way a third party would, mid-walk.

        A *separate* `ScopeStore` on purpose: the point is what the record says
        to someone who is not the walk — the CLI, the MCP adapter, a person
        listing runs while it works.
        """
        store = ScopeStore.for_project(project)
        scope = store.get_scope("rel-1") or {}
        row = next(
            (
                row
                for row in list_scopes(holder["app"], store)
                if row["workflow_id"] == "rel-1"
            ),
            None,
        )
        seen.append(
            {
                "step": step,
                "status": scope.get("status"),
                "advanceable": advanceable_scopes(store),
                "row": row,
            }
        )

    def build() -> str:
        calls.append("build")
        observe("build")
        return "artifact"

    def deploy() -> str:
        calls.append("deploy")
        observe("deploy")
        return "deployed"

    @workflow(
        steps=[Step("build"), Gate(name="approve", awaits=Approval), Step("deploy")],
        edges=[
            Edge(source="build", target="approve"),
            Edge(source="approve", target="deploy"),
            Edge(source="deploy", target=END),
        ],
    )
    def release() -> str:
        calls.append("body")
        return "shipped"

    instance.register_dynamic_job("build", build)
    instance.register_dynamic_job("deploy", deploy)
    instance.register_dynamic_job("release", release)
    holder["app"] = instance
    return instance


@pytest.fixture
def store(app: FunctualizeApp, project: Path, calls: list[str]) -> ScopeStore:
    """A scope blocked at the gate, `build` already recorded."""
    app.execute(
        RunRequest(job_name="release", surface="app.execute", workflow_scope_id="rel-1")
    )
    calls.clear()
    return ScopeStore.for_project(project)


# ----------------------------------------------------------------------
# (a), (b) — the scope says `running` from the moment the walk owns it
# ----------------------------------------------------------------------


class TestAResumedWalkSaysRunning:
    """D2 = 1, seen from outside the walk.

    The first test is the control: the first-entry path stamped then and stamps
    now, so it is asserted only to show that "every entry" did not cost the
    original one.
    """

    def test_a_first_entry_already_said_running(
        self, store: ScopeStore, seen: Sequence[dict[str, Any]]
    ) -> None:
        first = seen[0]
        assert first["step"] == "build"
        assert first["status"] == "running"

    def test_a_walk_resumed_from_blocked_says_running(
        self,
        app: FunctualizeApp,
        store: ScopeStore,
        calls: list[str],
        seen: list[dict[str, Any]],
    ) -> None:
        """The gate was answered, so the walk resumes — and still reads live.

        The resume starts from `blocked`, which is the status a person sees
        before they answer the gate. Before D2 = 1 it stayed `blocked` for the
        walk that answered it.
        """
        scope = store.get_scope("rel-1") or {}
        assert scope["status"] == "blocked", "the fixture is the pre-resume state"
        seen.clear()

        result = resume_scope(app, store, "rel-1", input={"approved": True})

        assert result["status"] == "success"
        assert calls == ["deploy", "body"], "the resumed walk ran its step"
        assert [entry["step"] for entry in seen] == ["deploy"], (
            "only `deploy` reports from inside the walk — the epilogue body runs "
            "after the walk has stamped its own ending, and is covered elsewhere"
        )
        deploy = seen[0]
        assert deploy["status"] == "running", (
            "the store still said blocked while the walk was on the scope"
        )
        assert deploy["row"] is not None
        assert deploy["row"]["status"] == "running"
        assert deploy["row"]["state"] == "running", "not `waiting` and not `ready`"
        assert "rel-1" in deploy["advanceable"]

    def test_a_walk_resumed_from_failed_says_running(
        self, engine_store: ScopeStore
    ) -> None:
        """A step raised, and the retry is a walk like any other.

        The first walk fails on `second` and leaves the position there, so the
        second walk resumes into that node rather than replaying from the entry
        — the branch that did not stamp before this change.
        """
        _walk(engine_store, _line(), "s1", _failing_at("second"))
        assert (engine_store.get_scope("s1") or {})["status"] == "failed"

        names: list[str] = []
        statuses: list[Any] = []
        _walk(
            engine_store, _line(), "s1", _observing(engine_store, "s1", names, statuses)
        )

        assert names == ["second"], "the failed step was retried, not replayed past"
        assert statuses == ["running"]
        assert (engine_store.get_scope("s1") or {})["status"] == "completed"

    def test_a_walk_resumed_from_completed_says_running(
        self, engine_store: ScopeStore
    ) -> None:
        """The shortest entry there is, and why it is read at the seam.

        A completed scope has no position left (`complete` clears it), so a
        resume re-enters at the graph entry and replay-skips every step that
        already succeeded — nothing calls `run_step`, and no step callback can
        witness the stamp. `--retry-epilogue` drives exactly this entry, and
        `tests/workflow/test_workflow_control.TestRetryEpilogue` is where the
        body re-running is covered; the stamp is read here, through the call
        `WorkflowWalker._run_walk` makes.
        """
        _walk(engine_store, _line(), "s1", _running)
        scope = engine_store.get_scope("s1") or {}
        assert scope["status"] == "completed"
        assert scope["position"] is None

        walk = FrontierWalk(
            GraphModel(entry="first"),
            engine_store,
            "s1",
            runtime_store=port_for(engine_store),
        )
        walk.start()

        assert (engine_store.get_scope("s1") or {})["status"] == "running"

        # And the walk that follows it still ends where it did: the stamp is an
        # entry, not a resurrection.
        names: list[str] = []
        _walk(engine_store, _line(), "s1", _observing(engine_store, "s1", names, []))
        assert names == [], "every step was replayed from its record"
        assert (engine_store.get_scope("s1") or {})["status"] == "completed"


# ----------------------------------------------------------------------
# (c) — the fact the stamp creates: a resumed walk can go silent
# ----------------------------------------------------------------------


class TestASilentResumedWalkIsDiagnosed:
    """The fact the stamp creates, proven by a walk rather than a fixture.

    `_step_that_went_silent` diagnoses a scope that reads `running` with an
    expired lease and an unrecorded node under its position. A resumed walk now
    leaves exactly that when its process dies mid-step; before D2 = 1 it left
    the status it had resumed from, which is the control below.
    """

    def test_a_resumed_walk_that_went_silent_is_diagnosed(
        self, engine_store: ScopeStore
    ) -> None:
        # Walk 1 stops at the gate: position `hold`, no step recorded there.
        _walk(engine_store, _gated_line(), "s1", _running)
        blocked = engine_store.get_scope("s1") or {}
        assert blocked["status"] == "blocked"
        assert blocked["position"] == "hold"

        # Walk 2 resumes — the deposited answer is what `answer_gate` writes —
        # past the gate and dies on `second`.
        engine_store.put_gate("s1", "hold", {"payload": {"approved": True}})
        with pytest.raises(_ProcessDied):
            _walk(engine_store, _gated_line(), "s1", _dies_at("second"))

        # What the dead resumed walk leaves: its own entry stamp, the position
        # it was on, and no record of a step that never reported.
        scope = engine_store.get_scope("s1") or {}
        assert scope["status"] == "running", "the resumed walk's own entry stamp"
        assert scope["position"] == "second"
        assert _step_status(engine_store, "s1", "second") is None

        FrontierWalk(
            GraphModel(entry="first"),
            engine_store,
            "s1",
            runtime_store=port_for(engine_store),
        ).claim()

        assert _step_status(engine_store, "s1", "second") == StepStatus.TIMED_OUT

    def test_the_same_record_on_the_old_status_is_left_alone(
        self, engine_store: ScopeStore
    ) -> None:
        """The pre-D2 shape: same position, same dead lease, status `blocked`.

        Hand-written, and it has to be: after this change no walk leaves that
        record any more, which is the whole of what the change is. It is here so
        the test above reads as "the stamp is what makes a silent resumed walk
        visible" rather than as a detector that would have noticed anyway.
        """
        _leave_mid_step(engine_store, "s1", at="second", status="blocked")

        FrontierWalk(
            GraphModel(entry="first"),
            engine_store,
            "s1",
            runtime_store=port_for(engine_store),
        ).claim()

        assert _step_status(engine_store, "s1", "second") is None


# ----------------------------------------------------------------------
# (d) — the stamp cannot resurrect a cancelled scope
# ----------------------------------------------------------------------


class TestTheStampDoesNotResurrectATerminalScope:
    def test_resuming_a_cancelled_scope_is_refused_before_any_walk(
        self, app: FunctualizeApp, store: ScopeStore, seen: list[dict[str, Any]]
    ) -> None:
        """`set_scope_status` writes unconditionally, so the refusal that keeps
        `cancelled` cancelled is `resume_scope`'s, and it has to be the thing
        under test — not the stamp's own restraint, which does not exist."""
        assert cancel_scope(store, "rel-1")["status"] == "cancelled"
        seen.clear()

        result = resume_scope(app, store, "rel-1")

        assert result["error"] == "scope_cancelled"
        assert seen == [], "no walk was built, so no entry stamped anything"
        assert (store.get_scope("rel-1") or {})["status"] == "cancelled"
