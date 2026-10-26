"""The effect-receiver example, proven against the real outbox.

Three proofs: the receiver satisfies the protocol, a redelivery of the same
idempotency key applies once, and a gate answered over SQLite through the
public door is delivered to the registered receiver after the commit.
"""

from __future__ import annotations

import sys
from collections.abc import Generator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from functualize_substrate_sqlite import SQLiteSubstratePlugin
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from functualize_effect_receiver import AuditReceiver, EffectReceiverPlugin

from functualize._app.state import AppState
from functualize._config.chain import ResolutionChain
from functualize._config.sources import DefaultSource
from functualize.app.config import ConfigSources, JobSources, PluginSources
from functualize.app.core import FunctualizeApp
from functualize.app.utils import answer_gate, selected_workflow_store
from functualize.plugin import EffectReceiver
from functualize.types import RunRequest
from functualize.workflow import END, Edge, Gate, Step, workflow


class Approval(BaseModel):
    approved: bool
    reason: str


def build() -> str:
    return "artifact"


@workflow(
    steps=[Step("build"), Gate(name="approve", awaits=Approval)],
    edges=[Edge(source="build", target="approve"), Edge(source="approve", target=END)],
)
def release() -> str:
    return "shipped"


@dataclass
class _Intent:
    """One outbox row, as the dispatcher hands it to a receiver."""

    effect_id: str
    idempotency_key: str
    payload: dict[str, Any] = field(default_factory=dict)
    topic: str = "gate.accepted"
    attempts: int = 1


@pytest.fixture(autouse=True)
def _reset() -> Generator[None]:
    AppState.reset()
    yield
    AppState.reset()


def test_the_receiver_satisfies_the_protocol() -> None:
    assert isinstance(AuditReceiver(), EffectReceiver)
    assert AuditReceiver.topic == "gate.accepted"


def test_a_redelivery_of_the_same_key_applies_once() -> None:
    receiver = AuditReceiver()
    effect = _Intent("eff-1", "gate.accepted:req-1", {"gate": "approve"})

    receiver.receive(effect)
    receiver.receive(effect)  # the crash-redelivery: same intent, again

    assert len(receiver.audit) == 1
    assert "gate=approve" in receiver.audit[0]

    receiver.receive(_Intent("eff-2", "gate.accepted:req-2", {"gate": "approve"}))
    assert len(receiver.audit) == 2


def test_an_answered_gate_is_delivered_after_the_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    (root / ".functualize").mkdir(parents=True)
    monkeypatch.chdir(root)

    plugin = EffectReceiverPlugin()
    app = FunctualizeApp(
        "example",
        job_sources=JobSources(functions=[build, release]),
        config_sources=ConfigSources(
            config_resolution_chain=ResolutionChain(
                [
                    DefaultSource(
                        {"runtime_store": {"url": f"sqlite://{tmp_path / 'state.db'}"}}
                    )
                ]
            )
        ),
        plugin_sources=PluginSources(
            entry_point_group="",
            explicit_plugins=[SQLiteSubstratePlugin(), plugin],
        ),
    )
    app.execute(
        RunRequest(job_name="release", surface="app.execute", workflow_scope_id="rel-1")
    )

    answered = answer_gate(
        app,
        selected_workflow_store(app),
        "rel-1",
        "approve",
        {"approved": True, "reason": "ok"},
        source="cli",
    )

    assert answered["status"] == "answered"
    # Delivered after the commit, applied once, keyed by the request.
    store = selected_workflow_store(app)
    request = store.inputs.for_gate("rel-1", "approve")
    assert request is not None
    assert plugin.receiver.audit == [
        f"gate.accepted:{request.request_id} gate=approve request={request.request_id}"
    ]
