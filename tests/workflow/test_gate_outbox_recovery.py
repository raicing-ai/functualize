"""A gate answer's effect survives a process kill; redelivery is deduplicated.

Row 4.1 of the gate-interactions-outbox feature, and the shape's falsifiable
experiment (§11): answer a gate, kill the process after the transaction
commits but before dispatch, restart on the same SQLite file, and observe one
accepted transition, a request readable with its candidate, decision and
evidence, and one receiver-side application despite a forced redelivery.

**The crashes are real.** Each one is a child process that dies by
``os._exit`` — no ``finally``, no ``atexit``, no flush — at a seam the
production code crosses:

* *between commit and dispatch* — the answer path commits the candidate, its
  decision and the ``gate.accepted`` intent as one unit and then calls
  ``_app.effects.drain``; the child dies inside that call, before the
  dispatcher claims anything;
* *between delivery and acknowledgement* — the boot drain claims the intent
  and hands it to the receiver, which applies it; the child dies inside
  ``SqlEffectQueue.published``, so the claim is never acknowledged.

Everything the parent then asserts is read back through a fresh app or a fresh
store on the same file — nothing a dead process held in memory.

**The receiver deduplicates on the idempotency key**, as the
``EffectReceiver`` contract tells every receiver to: it logs every delivery
and applies an effect only the first time its key arrives. Both ledgers are
files, because the deliveries happen in different processes. The assertions
count both — deliveries can exceed one (at-least-once), applications cannot.

**SQLite only, and why.** The outbox tier exists only on a store whose profile
declares ``durable_outbox=True``. The document store declares ``False``: it
has no queue, records no intent, builds no dispatcher, and refuses to boot when
a receiver is registered (row 2.3, AC-5). There is no document-store queue to
crash and recover, so the last test pins that absence instead of pretending to
test a port the document store does not implement.
"""

from __future__ import annotations

import json
import multiprocessing
import os
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from functualize_substrate_sqlite import SQLiteSubstratePlugin
from functualize_substrate_sqlite._factory import SqliteRuntimeStoreFactory
from pydantic import BaseModel

from functualize._app.state import AppState
from functualize._config.chain import ResolutionChain
from functualize._config.sources import DefaultSource
from functualize._engine.recording.input_recorder import content_digest
from functualize._primitives.outbox import CLAIM_LEASE_SECONDS, OutboxDispatcher
from functualize._types.errors import RuntimeStoreCapabilityError
from functualize._types.gate_resolution import EvaluationOutcome, EvidenceRef
from functualize._types.persistence import OutboxStore, RuntimeStoreConfig
from functualize.app.config import ConfigSources, JobSources, PluginSources
from functualize.app.core import FunctualizeApp
from functualize.app.utils import answer_gate, selected_workflow_store
from functualize.types import RunRequest
from functualize.workflow import END, Edge, Gate, Step, workflow

if TYPE_CHECKING:
    from functualize._types.persistence import EffectView

SCOPE = "wf_42"
TOPIC = "gate.accepted"
EVIDENCE = EvidenceRef("artifact://ev_5", content_digest(b"signed form"), "image/png")
#: Exit codes the children die with, so the parent can tell *where* each died.
DIED_BEFORE_DISPATCH = 17
DIED_BEFORE_ACK = 23


class Approval(BaseModel):
    approved: bool


def build() -> str:
    return "artifact"


def deploy() -> str:
    return "deployed"


@workflow(
    steps=[Step("build"), Gate(name="approval", awaits=Approval), Step("deploy")],
    edges=[
        Edge(source="build", target="approval"),
        Edge(source="approval", target="deploy"),
        Edge(source="deploy", target=END),
    ],
)
def release() -> str:
    return "shipped"


class LedgerReceiver:
    """An `EffectReceiver` that deduplicates on the key, across processes.

    ``deliveries`` logs every call; ``applied`` holds each key the first time
    it arrives and is never written for a key it already holds — the
    application the at-least-once contract makes the receiver responsible for.
    """

    topic = TOPIC

    def __init__(self, ledger: Path) -> None:
        self.deliveries = ledger / "deliveries.jsonl"
        self.applied = ledger / "applied.jsonl"

    def receive(self, effect: EffectView) -> None:
        key = effect.idempotency_key
        with self.deliveries.open("a", encoding="utf-8") as log:
            log.write(json.dumps({"key": key, "attempts": effect.attempts}) + "\n")
        if key in _keys(self.applied):
            return
        with self.applied.open("a", encoding="utf-8") as log:
            log.write(json.dumps({"key": key, "payload": effect.payload}) + "\n")
            log.flush()
            os.fsync(log.fileno())


class ReceiverPlugin:
    """Registers the receiver the way a consumer package does."""

    version = "0.1.0"
    description = "Registers the ledger receiver."
    name = "ledger-receiver"

    def __init__(self, receiver: LedgerReceiver) -> None:
        self._receiver = receiver

    def __call__(self, app: Any) -> None:
        app.extensions.register_effect_receiver(self._receiver)


def _keys(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [json.loads(line)["key"] for line in path.read_text().splitlines()]


def _url(root: Path) -> str:
    return f"sqlite://{root / 'state.db'}"


def _app(root: Path, url: str, *plugins: object) -> FunctualizeApp:
    AppState.reset()
    return FunctualizeApp(
        "recovery",
        job_sources=JobSources(functions=[build, deploy, release]),
        config_sources=ConfigSources(
            config_resolution_chain=ResolutionChain(
                [DefaultSource({"runtime_store": {"url": url}})]
            )
        ),
        plugin_sources=PluginSources(
            entry_point_group="", explicit_plugins=[SQLiteSubstratePlugin(), *plugins]
        ),
    )


def _cold_store(root: Path) -> OutboxStore:
    """A fresh store on the file — what a restarted process would open."""
    store = (
        SqliteRuntimeStoreFactory()
        .prepare(RuntimeStoreConfig(url=_url(root), scheme="sqlite", project_root=root))
        .store
    )
    assert isinstance(store, OutboxStore)
    return store


def _outbox(store: OutboxStore) -> list[tuple[Any, ...]]:
    driver = store.driver  # type: ignore[attr-defined]
    rows: list[tuple[Any, ...]] = driver.query(
        "SELECT idempotency_key, status, attempts FROM outbox ORDER BY rowid"
    )
    return rows


def _run_child(target: Any, *args: Any) -> int:
    """Run ``target`` in a child process that dies by ``os._exit``; its code."""
    context: Any = multiprocessing.get_context(
        "fork" if "fork" in multiprocessing.get_all_start_methods() else "spawn"
    )
    child = context.Process(target=target, args=args)
    child.start()
    child.join(timeout=120)
    assert child.exitcode is not None, "the child did not finish"
    return int(child.exitcode)


# -- the children ---------------------------------------------------------------


def _answer_then_die_before_dispatch(root: str, ledger: str) -> None:
    """Answer the gate through the public door; die after commit, before drain.

    The receiver is registered, so without the crash this very call would
    deliver the effect: the drain after the commit is the dispatch.
    """
    project = Path(root)
    os.chdir(project)
    app = _app(project, _url(project), ReceiverPlugin(LedgerReceiver(Path(ledger))))

    import functualize._app.effects as effects

    def die(app: Any, store: Any) -> None:
        os._exit(DIED_BEFORE_DISPATCH)

    effects.drain = die  # the answer path imports it at call time
    answer_gate(
        app,
        selected_workflow_store(app),
        SCOPE,
        "approval",
        {"approved": True},
        source="api",
        evidence=[EVIDENCE],
    )
    os._exit(0)  # unreachable unless the answer path skipped its drain


def _boot_then_die_before_ack(root: str, ledger: str) -> None:
    """Boot with a receiver: the boot drain delivers, then dies acknowledging."""
    project = Path(root)
    os.chdir(project)
    from functualize_substrate_sqlite._outbox_sql import SqlEffectQueue

    def die(self: Any, effect: Any, *, now: Any) -> None:
        os._exit(DIED_BEFORE_ACK)

    SqlEffectQueue.published = die  # type: ignore[method-assign]
    _app(project, _url(project), ReceiverPlugin(LedgerReceiver(Path(ledger))))
    os._exit(0)  # unreachable unless the boot drain delivered nothing


# -- fixtures ---------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset() -> Generator[None]:
    AppState.reset()
    yield
    AppState.reset()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A SQLite project with `release` blocked at its gate, no receiver yet."""
    root = tmp_path / "project"
    (root / ".functualize").mkdir(parents=True)
    monkeypatch.chdir(root)
    app = _app(root, _url(root))
    app.execute(
        RunRequest(job_name="release", surface="app.execute", workflow_scope_id=SCOPE)
    )
    view = app.workflow_runtime_store().workflows.workflow(SCOPE)
    assert view is not None and view.status == "blocked"
    AppState.reset()
    return root


@pytest.fixture
def ledger(tmp_path: Path) -> Path:
    path = tmp_path / "ledger"
    path.mkdir()
    return path


# -- 1 and 3: the kill between commit and dispatch --------------------------------


def test_an_intent_committed_before_a_kill_is_delivered_on_the_next_start(
    project: Path, ledger: Path
) -> None:
    code = _run_child(_answer_then_die_before_dispatch, str(project), str(ledger))

    # Died where it was told to: after the answer committed, inside the drain.
    assert code == DIED_BEFORE_DISPATCH
    receiver = LedgerReceiver(ledger)
    assert _keys(receiver.deliveries) == []

    # The commit survived whole, read cold: one accepted transition, the
    # request readable with its candidate, decision and evidence, and the
    # intent still pending — not lost with the dead process.
    store = _cold_store(project)
    request = store.inputs.for_gate(SCOPE, "approval")
    assert request is not None and request.status == "accepted"
    [candidate] = store.inputs.candidates_for(request.request_id)
    assert candidate.evaluation.outcome is EvaluationOutcome.ACCEPTED
    assert candidate.evidence_refs == (EVIDENCE,)
    decision = store.inputs.decision(request.request_id)
    assert decision is not None and decision.accepted_id == candidate.candidate_id
    key = f"{TOPIC}:{request.request_id}"
    assert _outbox(store) == [(key, "pending", 0)]
    store.close()

    # The next start delivers it — from the queue, not by re-answering: the
    # request still holds exactly the one candidate the dead process recorded.
    app = _app(project, _url(project), ReceiverPlugin(receiver))
    assert _keys(receiver.deliveries) == [key]
    assert _keys(receiver.applied) == [key]
    runtime = app.workflow_runtime_store()
    assert isinstance(runtime, OutboxStore)
    assert _outbox(runtime) == [(key, "published", 1)]
    assert len(runtime.inputs.candidates_for(request.request_id)) == 1

    # An acknowledged intent is never delivered again.
    _app(project, _url(project), ReceiverPlugin(receiver))
    assert _keys(receiver.deliveries) == [key]


# -- 2 and 3: the kill between delivery and acknowledgement ------------------------


def test_an_unacknowledged_delivery_is_redelivered_and_applied_once(
    project: Path, ledger: Path
) -> None:
    # The answer commits its intent; no receiver is registered yet, so it waits.
    app = _app(project, _url(project))
    answer_gate(
        app,
        selected_workflow_store(app),
        SCOPE,
        "approval",
        {"approved": True},
        source="api",
    )
    runtime = app.workflow_runtime_store()
    assert isinstance(runtime, OutboxStore)
    [(key, status, attempts)] = _outbox(runtime)
    assert (status, attempts) == ("pending", 0)

    code = _run_child(_boot_then_die_before_ack, str(project), str(ledger))

    # The receiver applied it, then the process died acknowledging.
    assert code == DIED_BEFORE_ACK
    receiver = LedgerReceiver(ledger)
    assert _keys(receiver.deliveries) == [key]
    assert _keys(receiver.applied) == [key]
    store = _cold_store(project)
    assert _outbox(store) == [(key, "claimed", 1)]

    # Inside the claim lease the dead dispatcher's claim still protects it:
    # a restart does not redeliver yet.
    _app(project, _url(project), ReceiverPlugin(receiver))
    assert _keys(receiver.deliveries) == [key]

    # Past the lease the claim is presumed dead and the intent is delivered
    # again — at-least-once — and the receiver's key makes it a no-op.
    later = datetime.now(UTC) + timedelta(seconds=CLAIM_LEASE_SECONDS + 1)
    report = OutboxDispatcher(
        store.effects, {TOPIC: receiver}, clock=lambda: later
    ).drain()
    assert (report.delivered, report.failed) == (1, 0)
    assert _keys(receiver.deliveries) == [key, key]
    assert _keys(receiver.applied) == [key]
    assert _outbox(store) == [(key, "published", 2)]

    # Acknowledged now: nothing further is delivered, however late.
    much_later = later + timedelta(days=1)
    again = OutboxDispatcher(
        store.effects, {TOPIC: receiver}, clock=lambda: much_later
    ).drain()
    assert (again.delivered, again.failed) == (0, 0)
    assert _keys(receiver.deliveries) == [key, key]
    assert _keys(receiver.applied) == [key]
    store.close()


# -- 4: the document store has no queue to recover ---------------------------------


def test_the_document_store_has_no_outbox_to_crash_or_recover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ledger: Path
) -> None:
    """Pinned rather than skipped: the absence is the document store's contract."""
    root = tmp_path / "documents"
    (root / ".functualize").mkdir(parents=True)
    monkeypatch.chdir(root)
    app = _app(root, "documents:")
    store = app.workflow_runtime_store()
    assert store.profile.durable_outbox is False
    assert not isinstance(store, OutboxStore)

    with pytest.raises(RuntimeStoreCapabilityError, match="durable_outbox"):
        _app(root, "documents:", ReceiverPlugin(LedgerReceiver(ledger)))
