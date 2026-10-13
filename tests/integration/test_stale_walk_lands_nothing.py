"""A second process takes a walk while the first still has a staged write.

The delayed move passed its in-memory generation check before the takeover.
Only the SQL predicate at commit time can stop it from overwriting B's row.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from multiprocessing import get_context
from multiprocessing.connection import Connection
from pathlib import Path

from functualize_substrate_sqlite import SqliteRuntimeStoreFactory

from functualize._primitives.lease import StaleGenerationError
from functualize.plugin import (
    Claimed,
    ClaimWorkflow,
    MoveScope,
    RecordStep,
    ReleaseLease,
    RenewLease,
    RuntimeStoreConfig,
    StartWalk,
    StateBatch,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
SCOPE = "taken-over"


def _store(db: Path):
    return (
        SqliteRuntimeStoreFactory()
        .prepare(
            RuntimeStoreConfig(
                url=f"sqlite://{db}", scheme="sqlite", project_root=db.parent
            )
        )
        .store
    )


def _first_process(db: Path, channel: Connection) -> None:
    store = _store(db)
    try:
        with store.transaction() as tx:
            claim = tx.workflows.claim(ClaimWorkflow(SCOPE, "runner-a", NOW, 300))
        assert isinstance(claim, Claimed)
        gen = claim.generation
        with store.transaction() as tx:
            tx.workflows.start(StartWalk(SCOPE, gen, "flow", "entry", "digest", NOW))

        # This command has passed require_fence, but has not yet reached SQL.
        # B takes over before __exit__ flushes the buffered update.
        try:
            with store.transaction() as tx:
                tx.workflows.move(MoveScope(SCOPE, gen, "blocked", "a-position", NOW))
                channel.send(("staged", gen))
                assert channel.poll(30), "second process did not take over"
                assert channel.recv() == "taken"
        except StaleGenerationError:
            pass

        commands = (
            (
                "renew",
                lambda tx: tx.workflows.renew(
                    RenewLease(SCOPE, gen, "runner-a", NOW, 600)
                ),
            ),
            ("release", lambda tx: tx.workflows.release(ReleaseLease(SCOPE, gen, NOW))),
            (
                "record_step",
                lambda tx: tx.workflows.record_step(
                    RecordStep(SCOPE, gen, "a-step", NOW, NOW)
                ),
            ),
            (
                "move",
                lambda tx: tx.workflows.move(
                    MoveScope(SCOPE, gen, "blocked", "a-late", NOW)
                ),
            ),
            (
                "state",
                lambda tx: tx.workflows.write_state(
                    StateBatch(SCOPE, gen, NOW, {"winner": "a"})
                ),
            ),
        )
        refused = []
        for name, issue in commands:
            try:
                with store.transaction() as tx:
                    issue(tx)
            except StaleGenerationError:
                refused.append(name)
        channel.send(("done", refused))
    except BaseException as error:
        channel.send(("error", repr(error)))
        raise
    finally:
        store.close()
        channel.close()


def test_a_stale_walk_lands_nothing_after_a_second_process_takes_over(
    tmp_path: Path,
) -> None:
    db = tmp_path / "state.db"
    context = get_context("spawn")
    parent, child = context.Pipe()
    first = context.Process(target=_first_process, args=(db, child))
    first.start()
    child.close()
    try:
        assert parent.poll(30), "first process did not stage its move"
        phase, generation = parent.recv()
        assert phase == "staged", (phase, generation)

        store = _store(db)
        try:
            with store.transaction() as tx:
                taken = tx.workflows.claim(
                    ClaimWorkflow(
                        SCOPE, "runner-b", NOW + timedelta(seconds=1), 300, force=True
                    )
                )
            assert isinstance(taken, Claimed) and taken.generation > generation
            with store.transaction() as tx:
                tx.workflows.record_step(
                    RecordStep(SCOPE, taken.generation, "b-step", NOW, NOW, result="b")
                )
                tx.workflows.write_state(
                    StateBatch(SCOPE, taken.generation, NOW, {"winner": "b"})
                )
                tx.workflows.move(
                    MoveScope(SCOPE, taken.generation, "running", "b-position", NOW)
                )
            parent.send("taken")
            assert parent.poll(30), "first process did not finish stale writes"
            phase, result = parent.recv()
            assert phase == "done", (phase, result)
            assert set(result) == {"renew", "release", "record_step", "move", "state"}

            view = store.workflows.workflow(SCOPE)
            assert view is not None
            assert (view.generation, view.owner, view.status, view.position) == (
                taken.generation,
                "runner-b",
                "running",
                "b-position",
            ), view
            assert store.workflows.step(SCOPE, "a-step") is None
            assert store.workflows.step(SCOPE, "b-step") is not None
            assert store.workflows.state(SCOPE) == {"winner": "b"}
        finally:
            store.close()
    finally:
        first.join(timeout=30)
        if first.is_alive():
            first.terminate()
            first.join(timeout=5)
        parent.close()
    assert first.exitcode == 0
