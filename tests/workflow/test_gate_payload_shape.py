"""One gate, one stored shape, whoever answered it.

`deposit_gate_input` validated with `model(**payload)` and then stored
`payload` — the raw dict — discarding every default and coercion the validation
had just applied. The walker's own strategy path stores `model.model_dump()`,
and the walker feeds whichever it finds straight to the node.

So the same gate produced two different objects depending on who answered it,
and a model with a defaulted field had that field **missing** when a human
deposited the answer.

This is a precondition for gate drafts, not a tidy-up after them: a draft that
accumulated raw fragments and committed them raw would make the divergence
permanent, because the draft would become the canonical accumulation format.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from pydantic import BaseModel

from functualize._app.state import AppState
from functualize.app.core import FunctualizeApp
from functualize.app.utils import StateStore, deposit_gate_input
from functualize.types import RunRequest
from functualize.workflow import END, Edge, Gate, Step, workflow


class Approval(BaseModel):
    approved: bool
    reason: str = "unspecified"  # a default the raw path used to discard
    reviewers: int = 1  # a coercion the raw path used to discard


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
def app(project: Path) -> FunctualizeApp:
    instance = FunctualizeApp(name="testapp")
    seen: list[object] = []

    def build() -> str:
        return "artifact"

    @workflow(
        steps=[Step("build"), Gate(name="approve", awaits=Approval)],
        edges=[
            Edge(source="build", target="approve"),
            Edge(source="approve", target=END),
        ],
    )
    def release() -> str:
        return "shipped"

    instance.register_dynamic_job("build", build)
    instance.register_dynamic_job("release", release)
    instance._seen = seen  # type: ignore[attr-defined]
    return instance


def _blocked(app: FunctualizeApp, project: Path) -> StateStore:
    app.execute(
        RunRequest(job_name="release", surface="app.execute", workflow_scope_id="rel-1")
    )
    return StateStore.for_project(project)


class TestTheDepositPathStoresTheValidatedDump:
    """AC-10."""

    def test_a_defaulted_field_survives(
        self, app: FunctualizeApp, project: Path
    ) -> None:
        store = _blocked(app, project)

        result = deposit_gate_input(app, store, "rel-1", "approve", {"approved": True})
        assert "error" not in result, result

        gate = store.get_gate("rel-1", "approve")
        assert gate is not None
        assert gate["payload"]["reason"] == "unspecified", (
            "the default was discarded — the raw dict was stored"
        )

    def test_a_coercion_survives(self, app: FunctualizeApp, project: Path) -> None:
        store = _blocked(app, project)

        deposit_gate_input(
            app, store, "rel-1", "approve", {"approved": True, "reviewers": "3"}
        )

        stored = store.get_gate("rel-1", "approve")["payload"]
        assert stored["reviewers"] == 3
        assert isinstance(stored["reviewers"], int), "stored the uncoerced string"

    def test_the_stored_payload_equals_the_models_own_dump(
        self, app: FunctualizeApp, project: Path
    ) -> None:
        """The invariant, stated as an assertion: `payload` is the output of a
        complete, successful validation, dumped — nothing else."""
        store = _blocked(app, project)
        supplied = {"approved": True, "reviewers": "2"}

        deposit_gate_input(app, store, "rel-1", "approve", supplied)

        assert (
            store.get_gate("rel-1", "approve")["payload"]
            == Approval(**supplied).model_dump()
        )

    def test_invalid_input_still_stores_nothing(
        self, app: FunctualizeApp, project: Path
    ) -> None:
        """The all-or-nothing guarantee must survive the change."""
        store = _blocked(app, project)

        result = deposit_gate_input(
            app, store, "rel-1", "approve", {"approved": "yes?"}
        )

        assert result["error"] == "validation_error"
        assert store.get_gate("rel-1", "approve")["payload"] is None


class TestBothPathsAgree:
    def test_the_walker_receives_what_the_strategy_path_would_have_built(
        self, app: FunctualizeApp, project: Path
    ) -> None:
        """The walker feeds the stored payload straight to the node. Since both
        paths now store `model_dump()`, the node's value is the same object
        either way — which is the whole point."""
        store = _blocked(app, project)
        deposit_gate_input(app, store, "rel-1", "approve", {"approved": True})

        stored = store.get_gate("rel-1", "approve")["payload"]
        strategy_shape = Approval(approved=True).model_dump()

        assert stored == strategy_shape
        assert set(stored) == set(strategy_shape) == {"approved", "reason", "reviewers"}
