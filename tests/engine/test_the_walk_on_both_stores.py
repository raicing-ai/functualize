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
- **a takeover records no completion time** — ruling R-2: a step that went
  silent is recorded with `completed_at=None`, which the document store keeps
  as `""` (byte-identical to the legacy record) and SQLite as NULL.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import pytest
from functualize_substrate_sqlite import SQLiteSubstratePlugin
from pydantic import BaseModel

from functualize._engine.frontier import FrontierWalk, GraphModel, StepStatus
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


def _stored_completion(backend: str, root: Path) -> object:
    """The raw stored `completed_at` of the scope's one step record."""
    if backend == "documents":
        stored = JsonFileSubstrate(root).read("scopes")
        assert stored is not None
        return stored.data["scopes"]["s1"]["steps"]["first::never"]["completed_at"]
    import sqlite3

    connection = sqlite3.connect(f"file:{root / 'state.db'}?mode=ro", uri=True)
    try:
        [(value,)] = connection.execute(
            "SELECT completed_at FROM workflow_steps "
            "WHERE scope_id = 's1' AND step_key = 'first::never'"
        )
    finally:
        connection.close()
    return value


def test_a_takeover_records_no_completion_time(backend: str, tmp_path: Path) -> None:
    """`completed_at=None` is `""` on documents and NULL on SQLite (R-2).

    A stamp would make a scope taken over by a new runner look recently
    active, and survive an age-based purge it should not.
    """
    root = tmp_path / backend
    root.mkdir()
    store = _store(backend, root)
    graph = GraphModel(entry="first", edges={"first": []})
    walk = _walk(graph, store)
    _claimed(walk)
    walk.start("flow")
    walk.complete("first")
    # The step the first runner never reported: recorded with no completion.
    walk.record("first::never", StepStatus.TIMED_OUT, completed_at=None)

    assert _stored_completion(backend, root) == ("" if backend == "documents" else None)
    view = walk.step("first::never")
    assert view is not None and view.completed_at is None and view.status == "timed_out"
    store.close()
