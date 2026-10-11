"""A walk releases the selected store's lease before another process claims."""

from __future__ import annotations

import multiprocessing
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from functualize_substrate_sqlite import SQLiteSubstrate
from functualize_substrate_sqlite._factory import SqliteRuntimeStoreFactory

from functualize._engine.frontier import FrontierWalk, GraphModel
from functualize._primitives.document_store import DocumentRuntimeStore
from functualize._primitives.lease import StaleGenerationError
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize.plugin import (
    Claimed,
    ClaimWorkflow,
    ReleaseLease,
    RenewLease,
    RuntimeStoreConfig,
)

if TYPE_CHECKING:
    from functualize.plugin import RuntimeStore


def _store(backend: str, root: Path) -> RuntimeStore:
    if backend == "documents":
        return DocumentRuntimeStore(JsonFileSubstrate(root))
    return (
        SqliteRuntimeStoreFactory()
        .prepare(
            RuntimeStoreConfig(
                url=f"sqlite://{root / 'state.db'}", scheme="sqlite", project_root=root
            )
        )
        .store
    )


def _second_claim(backend: str, root: Path, answer: object) -> None:
    store = _store(backend, root)
    try:
        with store.transaction() as tx:
            outcome = tx.workflows.claim(
                ClaimWorkflow("s1", "second", datetime.now(UTC), 300)
            )
        answer.put(outcome)
    finally:
        store.close()


@pytest.mark.parametrize("backend", ["documents", "sqlite"])
def test_a_walk_releases_the_selected_lease_for_a_second_process(
    backend: str, tmp_path: Path
) -> None:
    root = tmp_path / backend
    root.mkdir()
    runtime = _store(backend, root)
    substrate = (
        JsonFileSubstrate(root)
        if backend == "documents"
        else SQLiteSubstrate(root / "state.db")
    )
    walk = FrontierWalk(
        GraphModel(entry="a"), ScopeStore(substrate), "s1", runtime_store=runtime
    )
    first = walk.claim()
    assert isinstance(first, Claimed)
    before = runtime.workflows.workflow("s1")
    assert before is not None and before.expires_at is not None
    walk.renew()
    renewed = runtime.workflows.workflow("s1")
    assert renewed is not None and renewed.expires_at is not None
    assert renewed.expires_at >= before.expires_at
    walk.release()

    ctx = multiprocessing.get_context("spawn")
    answer = ctx.Queue()
    process = ctx.Process(target=_second_claim, args=(backend, root, answer))
    process.start()
    process.join(timeout=15)
    assert process.exitcode == 0
    second = answer.get(timeout=2)
    assert isinstance(second, Claimed)
    assert second.generation == first.generation + 1

    with pytest.raises(StaleGenerationError), runtime.transaction() as tx:
        tx.workflows.renew(
            RenewLease("s1", first.generation, "first", datetime.now(UTC), 300)
        )
    with pytest.raises(StaleGenerationError), runtime.transaction() as tx:
        tx.workflows.release(ReleaseLease("s1", first.generation, datetime.now(UTC)))

    view = runtime.workflows.workflow("s1")
    assert view is not None and (view.owner, view.generation) == (
        "second",
        second.generation,
    )
    runtime.close()
