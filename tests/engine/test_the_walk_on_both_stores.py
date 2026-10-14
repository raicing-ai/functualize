"""The walk's records slice on both shipped stores, built only through the port.

W9's both-stores witness: every other walk test runs on the document store,
and its helpers set state up through `ScopeStore`, so proving the same walk
behaviour on SQLite takes a module that constructs nothing but ports — the
same `FrontierWalk`/`WorkflowWalker` calls, parametrised over
`DocumentRuntimeStore` and `SqliteRuntimeStore`.

What each subject guards:

- **resumed says running** — the D2 = 1 stamp, read back through the port on
  a *second* walk, so a scope resumed from `blocked` is live on both stores;
- **the recorded branch wins on replay** — sabotage (i)'s target: a replayed
  conditional must follow the branch it paused on, which is only true if the
  branch went through `RecordBranch`;
- **a loop's passes are distinct records** — the same node twice under
  different loop keys, both records present, replay-skip exact;
- **`FromJob` inside a walk on SQLite** — the walk-scoped reference reads the
  walk's own step records through the port (ruling R-3), so a consumer inside
  a walk receives the producer's recorded value rather than going blind;
- **a takeover records no completion time** — the takeover wire (`claim` →
  `_step_that_went_silent` → `_record_timed_out`) writes the `timed_out` record
  through the port, with ruling R-2's `completed_at=None`, which the document
  store keeps as `""` (byte-identical to the legacy record) and SQLite as NULL;
- **the epilogue keeps its legacy record** — `record_body`'s value lands in
  `scope["epilogue"]` in exactly the record shape the walk wrote before the
  port, and reads back as a usable step view (contracts §2, W-AC-4).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import pytest
from functualize_substrate_sqlite import SQLiteSubstratePlugin
from pydantic import BaseModel

from functualize._engine.capabilities.state import State  # noqa: TC001
from functualize._engine.frontier import FrontierWalk, GraphModel, StepStatus
from functualize._engine.workflow_runner import WorkflowRunner
from functualize._engine.workflow_walker import WalkOutcome, WorkflowWalker
from functualize._primitives.document_store import DocumentRuntimeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.workflow import Loop, WorkflowDeclaration
from functualize.job import FromJob, job
from functualize.plugin import Claimed, RuntimeStoreConfig
from functualize.workflow import END, Edge, Step, workflow

if TYPE_CHECKING:
    from functualize.plugin import RuntimeStore


def _store(backend: str, root: Path) -> RuntimeStore:
    """The selected store over ``root``, prepared as boot prepares it."""
    if backend == "documents":
        return DocumentRuntimeStore(JsonFileSubstrate(root))
    from functualize_substrate_sqlite import SqliteRuntimeStoreFactory

    return (
        SqliteRuntimeStoreFactory()
        .prepare(
            RuntimeStoreConfig(
                url=f"sqlite://{root / 'state.db'}", scheme="sqlite", project_root=root
            )
        )
        .store
    )


def _walk(graph: GraphModel, store: RuntimeStore, scope: str = "s1") -> FrontierWalk:
    return FrontierWalk(graph, scope, runtime_store=store)


def _claimed(walk: FrontierWalk) -> int:
    outcome = walk.claim()
    assert isinstance(outcome, Claimed)
    return outcome.generation


@pytest.fixture(params=["documents", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> RuntimeStore:
    root = tmp_path / request.param
    root.mkdir()
    return _store(request.param, root)


@pytest.fixture(params=["documents", "sqlite"])
def backend(request: pytest.FixtureRequest) -> str:
    return str(request.param)


# -- a resumed walk says running -------------------------------------------


def test_a_resumed_walk_says_running(store: RuntimeStore) -> None:
    graph = GraphModel(entry="first", edges={"first": ["second"], "second": []})
    first = _walk(graph, store)
    _claimed(first)
    assert first.start("flow") == ["first"]
    first.complete("first")
    first.move("blocked", "hold")
    first.release()

    resumed = _walk(graph, store)
    _claimed(resumed)
    runnable = resumed.start("flow")

    view = resumed.view()
    assert view is not None
    assert view.status == "running"
    assert runnable == ["hold"]  # the persisted position, not the entry
    assert view.position == "hold"
    store.close()


# -- the recorded branch wins on replay (sabotage i's target) ---------------


def test_the_recorded_branch_wins_on_replay(store: RuntimeStore) -> None:
    graph = GraphModel(
        entry="pick",
        conditional={"pick": {"left": "l-out", "right": "r-out"}},
        edges={"l-out": [], "r-out": []},
    )
    first = _walk(graph, store)
    _claimed(first)
    first.start("flow")
    assert first.complete("pick", choice="left") == ["l-out"]
    first.release()

    replay = _walk(graph, store)
    _claimed(replay)
    replay.start("flow")
    # A different choice on replay must not move the walk: the branch it
    # paused on is the one it recorded.
    assert replay.complete("pick", choice="right") == ["l-out"]
    assert replay.branch("pick") == "left"
    store.close()


# -- a loop's passes are distinct records -----------------------------------


def test_each_loop_pass_records_its_own_step(store: RuntimeStore) -> None:
    graph = GraphModel(entry="spin", edges={"spin": []})
    walk = _walk(graph, store)
    _claimed(walk)
    walk.start("flow")

    walk.complete("spin", args_hash="h1", return_value=1)
    walk.complete("spin", args_hash="h2", status=StepStatus.FAILED)

    records = {step.step_key: step for step in walk.steps()}
    assert set(records) == {"spin::h1", "spin::h2"}
    assert walk.should_replay_skip("spin", "h1") is True
    assert walk.should_replay_skip("spin", "h2") is False  # a failed pass re-runs
    store.close()


def test_a_looped_workflow_repeats_on_both_stores(store: RuntimeStore) -> None:
    """A real walker follows each loop edge and persists each pass through the port."""
    declaration = WorkflowDeclaration(
        nodes=(Step("fan"), Step("left"), Step("right"), Step("join")),
        edges=(
            Edge(source="fan", target="left"),
            Edge(source="fan", target="right"),
            Edge(source="left", target="join"),
            Edge(source="right", target="join"),
            Loop(source="join", target="fan", max_iterations=3),
            Edge(source="join", target=END),
        ),
    )
    calls: list[str] = []

    def run_step(name: str) -> str:
        calls.append(name)
        return name

    report = WorkflowWalker(
        declaration,
        "loop-scope",
        run_step=run_step,
        runtime_store=store,
        workflow_name="loop-flow",
    ).run()

    assert report.outcome is WalkOutcome.COMPLETED, report
    assert {name: calls.count(name) for name in ("fan", "left", "right", "join")} == {
        "fan": 3,
        "left": 3,
        "right": 3,
        "join": 3,
    }
    steps = store.workflows.steps("loop-scope")
    assert len([step for step in steps if step.step_key.startswith("join::")]) == 3
    store.close()


# -- FromJob inside a walk, on SQLite (ruling R-3) ---------------------------

#: What the consumer observed — module level so the annotated parameter can
#: resolve its type (see the test docstring).
SEEN: list[int] = []


class _Envelope(BaseModel):
    n: int


@job
def _produce() -> _Envelope:
    return _Envelope(n=7)


@job
def _consume(up: Annotated[_Envelope, FromJob("produce")]) -> None:
    SEEN.append(up.n)


@workflow(
    steps=[Step("produce"), Step("consume")],
    edges=[
        Edge(source="produce", target="consume"),
        Edge(source="consume", target=END),
    ],
)
def _flow() -> str:
    return "done"


def test_from_job_inside_a_walk_reads_the_recorded_step(tmp_path: Path) -> None:
    """The walk-scoped `FromJob` resolves through `workflows.steps`.

    A consumer step inside a workflow references the producer's return value;
    on SQLite the producer's record is a `workflow_steps` row, and the
    consumer must receive it — the read the three-file gate could not see.

    The jobs live at module level (with the envelope they annotate): a class
    defined inside the test function is invisible to the annotation resolver,
    and a `FromJob` parameter that cannot resolve its type is exactly the
    blindness this test exists to catch elsewhere.
    """
    from functualize._config.chain import ResolutionChain
    from functualize._config.sources import DefaultSource
    from functualize.app import ConfigSources, FunctualizeApp, JobSources, PluginSources
    from functualize.types import RunRequest

    SEEN.clear()
    app = FunctualizeApp(
        "from-job-on-sqlite",
        job_sources=JobSources(functions=[]),
        config_sources=ConfigSources(
            config_resolution_chain=ResolutionChain(
                [DefaultSource({"runtime_store": {"url": "sqlite:"}})]
            )
        ),
        plugin_sources=PluginSources(
            entry_point_group="", explicit_plugins=[SQLiteSubstratePlugin()]
        ),
    )
    app.register_dynamic_job("produce", _produce)
    app.register_dynamic_job("consume", _consume)
    app.register_dynamic_job("flow", _flow)

    result = app.execute(RunRequest(job_name="flow", surface="app.execute"))
    assert result.exception is None, result.exception

    assert SEEN == [7], "the consumer did not receive the producer's recorded value"
    store = app.execution_engine._runtime_store
    assert store.profile.name == "sqlite"
    produced = [
        step
        for step in store.workflows.steps(_scope_of(app, "flow"))
        if step.step_key.startswith("produce::")
    ]
    assert produced and produced[0].reusable and produced[0].result == {"n": 7}
    store.close()


def _scope_of(app: Any, workflow_name: str) -> str:
    """The one scope of a single run of ``workflow_name``."""
    from functualize.plugin import WorkflowQuery

    scopes = app.execution_engine._runtime_store.workflows.resumable(
        WorkflowQuery(workflow=workflow_name)
    )
    [view] = scopes
    return view.scope_id


# -- ruling R-2: a takeover records no completion time ----------------------


def _stored_completion(backend: str, root: Path, step_key: str) -> object:
    """The raw stored `completed_at` of the scope's one step record."""
    if backend == "documents":
        stored = JsonFileSubstrate(root).read("scopes")
        assert stored is not None
        return stored.data["scopes"]["s1"]["steps"][step_key]["completed_at"]
    import sqlite3

    connection = sqlite3.connect(f"file:{root / 'state.db'}?mode=ro", uri=True)
    try:
        [(value,)] = connection.execute(
            "SELECT completed_at FROM workflow_steps "
            "WHERE scope_id = 's1' AND step_key = ?",
            (step_key,),
        )
    finally:
        connection.close()
    return value


def test_a_takeover_records_no_completion_time(backend: str, tmp_path: Path) -> None:
    """The takeover wire writes its `timed_out` record with no completion time.

    `claim` → `_step_that_went_silent` → `_record_timed_out`: a step still
    `running` when its lease expired is recorded `timed_out` through the
    port, and ruling R-2's `completed_at=None` is `""` on documents and NULL
    on SQLite. A stamp would make a scope taken over by a new runner look
    recently active, and survive an age-based purge it should not.
    """
    root = tmp_path / backend
    root.mkdir()
    store = _store(backend, root)
    graph = GraphModel(entry="first", edges={"first": []})
    walk = _walk(graph, store)
    _claimed(walk)
    walk.start("flow")
    # The runner dies mid-flow: `first` is still running and nothing was
    # stamped, so the scope is abandoned the moment the claim's lease expires
    # (release ends a lease the way an expiry does). `complete` is deliberately
    # never called: it would write the very record the takeover has to write.
    assert walk.step("first::") is None
    walk.release()

    resumed = _walk(graph, store)
    _claimed(resumed)  # takeover: claim finds the silent step and records it

    assert _stored_completion(backend, root, "first::") == (
        "" if backend == "documents" else None
    )
    view = resumed.step("first::")
    assert view is not None and view.completed_at is None and view.status == "timed_out"
    store.close()


def test_a_renewal_overtaken_before_its_commit_is_superseded(tmp_path: Path) -> None:
    """The heartbeat's verdict follows what was stored, not what was attempted.

    SQLite checks the fence when the renewal is staged and again in the
    statement's predicate. A forced claim that commits between the two leaves
    the renewal matching no row, so the walk no longer owns the scope —
    `renew()` must say `SUPERSEDED`, or the heartbeat waits a whole interval
    believing it still holds a scope another runner is walking.
    """
    from unittest.mock import patch

    from functualize_substrate_sqlite._workflow_sql import SqlWorkflowWriter

    from functualize._engine.frontier import RenewalOutcome

    store = _store("sqlite", tmp_path)
    walk = _walk(GraphModel(entry="a"), store)
    generation = _claimed(walk)
    real_renew = SqlWorkflowWriter.renew

    def overtaken(writer: SqlWorkflowWriter, cmd: Any) -> None:
        real_renew(writer, cmd)  # the fence check passes; the update is staged
        rival = _walk(GraphModel(entry="a"), store).claim(owner="rival", force=True)
        assert isinstance(rival, Claimed)  # committed before the renewal is

    with patch.object(SqlWorkflowWriter, "renew", overtaken):
        assert walk.renew() is RenewalOutcome.SUPERSEDED

    view = store.workflows.workflow("s1")
    assert view is not None
    assert (view.owner, view.generation) == ("rival", generation + 1)
    store.close()


# -- the epilogue keeps its legacy record (contracts §2, W-AC-4) ------------


def test_the_epilogue_keeps_its_legacy_record(backend: str, tmp_path: Path) -> None:
    """`record_body`'s value lands exactly where and as it always has.

    On documents `scope["epilogue"]` keeps the record the walk wrote before
    the port — `status`, `return_value`, `completed_at` and nothing else —
    because every surface reading the body's result reads those keys off the
    raw scope. On SQLite the epilogue is a plain step row with the same
    content. Both read back as a usable step view.
    """
    root = tmp_path / backend
    root.mkdir()
    store = _store(backend, root)
    runner = WorkflowRunner(run_step=None, runtime_store=store)
    runner.record_body("the answer")

    if backend == "documents":
        stored = JsonFileSubstrate(root).read("scopes")
        assert stored is not None
        record = stored.data["scopes"][runner.scope_id]["epilogue"]
        assert set(record) == {"status", "return_value", "completed_at"}
        assert record["status"] == "success"
        assert record["return_value"] == "the answer"
        assert record["completed_at"]
    else:
        import sqlite3

        connection = sqlite3.connect(f"file:{root / 'state.db'}?mode=ro", uri=True)
        try:
            [(status, result, completed_at)] = connection.execute(
                "SELECT status, result, completed_at FROM workflow_steps "
                "WHERE scope_id = ? AND step_key = '__epilogue__'",
                (runner.scope_id,),
            )
        finally:
            connection.close()
        assert status == "success"
        assert json.loads(result) == "the answer"
        assert completed_at

    view = store.workflows.step(runner.scope_id, "__epilogue__")
    assert view is not None
    assert view.result == "the answer"
    assert view.status == "success"
    assert view.completed_at is not None
    store.close()


# -- gate B-4 (W10/W11): a walk's state lands in the selected store ----------


def _write_rows(state: State) -> str:
    state.set("rows", 500)
    return "written"


@workflow(
    steps=[Step("writer")],
    edges=[Edge(source="writer", target=END)],
)
def _stateful_flow() -> str:
    return "done"


def _walk_state_app(backend: str, root: Path) -> Any:
    """An app over ``root`` whose one step writes state inside the walk."""
    from functualize._config.chain import ResolutionChain
    from functualize._config.sources import DefaultSource
    from functualize.app import ConfigSources, FunctualizeApp, JobSources, PluginSources

    config: dict[str, Any] = {}
    plugins: list[Any] = []
    if backend == "sqlite":
        config = {"runtime_store": {"url": f"sqlite://{root / 'state.db'}"}}
        plugins = [SQLiteSubstratePlugin()]
    app = FunctualizeApp(
        "walk-state",
        job_sources=JobSources(functions=[]),
        config_sources=ConfigSources(
            config_resolution_chain=ResolutionChain([DefaultSource(config)])
        ),
        plugin_sources=PluginSources(entry_point_group="", explicit_plugins=plugins),
    )
    app.register_dynamic_job("writer", _write_rows)
    app.register_dynamic_job("stateful", _stateful_flow)
    return app


def test_a_walk_steps_state_lands_in_the_selected_store(
    backend: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gate B-4 (W10/W11): `state.set` inside a walk lands in the selected
    store's scope state, and a resumed walk reads it back.

    The sabotage these two waves are ticked against: route `state_for_scope`
    back to `ScopeBackedStateStore` and the walk's writes land in the scope
    document instead — the `scope_state` row assertion below fails.
    """
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from functualize._engine.capabilities.state import state_for_scope
    from functualize._engine.capabilities.workflow_scope import WorkflowScope
    from functualize._engine.recording import WorkflowRecorder
    from functualize._primitives.lease import DEFAULT_LEASE_SECONDS
    from functualize.plugin import Claimed
    from functualize.types import RunRequest

    root = tmp_path / backend
    root.mkdir()
    # Project mode is "a `.functualize/` exists above start"; without one the
    # substrate lands in the standalone cache instead of under this root.
    (root / ".functualize").mkdir()
    monkeypatch.chdir(root)
    app = _walk_state_app(backend, root)

    result = app.execute(RunRequest(job_name="stateful", surface="app.execute"))
    assert result.exception is None, result.exception
    scope_id = _scope_of(app, "stateful")

    if backend == "sqlite":
        import sqlite3

        connection = sqlite3.connect(f"file:{root / 'state.db'}?mode=ro", uri=True)
        try:
            [(value,)] = connection.execute(
                "SELECT value FROM scope_state WHERE scope_id = ? AND key = 'rows'",
                (scope_id,),
            )
        finally:
            connection.close()
        assert json.loads(value) == 500

    # A resumed walk reads the value back in another process: a fresh handle
    # over the same store, the scope re-claimed at its new generation, the
    # read the walk's `State` makes (`WorkflowReader.state`).
    if backend == "documents":
        fresh = DocumentRuntimeStore(JsonFileSubstrate.for_project(root))
    else:
        fresh = _store(backend, root)
    with fresh.transaction() as tx:
        outcome = tx.workflows.claim(
            WorkflowRecorder().claimed(
                scope_id=scope_id,
                owner="another-process",
                now=datetime.now(UTC),
                lease_seconds=DEFAULT_LEASE_SECONDS,
                force=True,
            )
        )
    assert isinstance(outcome, Claimed)
    scope = WorkflowScope(scope_id)
    scope.generation = outcome.generation
    resumed = state_for_scope(scope, SimpleNamespace(_runtime_store=fresh))
    assert resumed.get("rows") == 500
    fresh.close()


# -- gate B-5 (W12): the walk log appends through the port ------------------


def test_walk_events_land_in_the_selected_stores_events(
    backend: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gate B-5 (W12): walk events are appended through `EventWriter`.

    On SQLite the events are `scope_events` rows and no `documents['scopes']`
    key is created — the sabotage (the walk log back on
    `ScopeStore.append_event`) fails exactly that assertion. On documents
    nothing changed: the events land in `scope["events"]`.
    """
    from functualize.types import RunRequest

    root = tmp_path / backend
    root.mkdir()
    # Project mode is "a `.functualize/` exists above start"; without one the
    # substrate lands in the standalone cache instead of under this root.
    (root / ".functualize").mkdir()
    monkeypatch.chdir(root)
    app = _walk_state_app(backend, root)

    result = app.execute(RunRequest(job_name="stateful", surface="app.execute"))
    assert result.exception is None, result.exception
    scope_id = _scope_of(app, "stateful")

    if backend == "sqlite":
        import sqlite3

        connection = sqlite3.connect(f"file:{root / 'state.db'}?mode=ro", uri=True)
        try:
            [(documents,)] = connection.execute(
                "SELECT COUNT(*) FROM documents WHERE key = 'scopes'"
            )
            names = [
                row[0]
                for row in connection.execute(
                    "SELECT type FROM scope_events WHERE scope_id = ? ORDER BY seq",
                    (scope_id,),
                )
            ]
        finally:
            connection.close()
        assert documents == 0, "the walk log created documents['scopes']"
        assert names, "walk events are not rows of scope_events"
        assert names[0] == "workflow.walk.start"
        assert names[-1] == "workflow.walk.end"
    else:
        stored = JsonFileSubstrate.for_project(root).read("scopes")
        assert stored is not None
        events = stored.data["scopes"][scope_id]["events"]
        names = [e.get("type") for e in events]
        assert names[0] == "workflow.walk.start"
        assert names[-1] == "workflow.walk.end"
