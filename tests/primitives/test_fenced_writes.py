"""Every scope write carries a generation, and a stale one is refused.

`durable-run-layer`/T6. Spec AC-8.

T5 built the lease. This is what makes it mean something: a write from a runner
whose claim has been superseded is **refused, not merged**. Merging produces a
record neither runner would recognise and that no reader could tell had
happened — two walks' decisions interleaved into one history.

**The check lives in `_mutate`, not on the eleven write methods.** Putting it on
each would fence them all today and miss the twelfth, added next month by
someone who did not know the rule — the failure mode the capability tripwire
exists for. `TestEveryWritePathIsFenced` enumerates the store's own methods
rather than listing them here, so a new one is covered the day it is written.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

from functualize._primitives.lease import StaleGenerationError
from functualize._primitives.scope_store import ScopeStore


@pytest.fixture
def store(tmp_path: Path) -> ScopeStore:
    s = ScopeStore(tmp_path / "scopes.json")
    s.ensure_scope("wf", "demo")
    return s


def _superseded(store: ScopeStore) -> int:
    """Claim twice; return the **first**, now-stale, generation."""
    first = store.claim_scope("wf", owner="a")
    store.claim_scope("wf", owner="b", force=True)
    return first.generation


class TestAStaleWriteIsRefused:
    def test_recording_a_step_is_refused(self, store: ScopeStore) -> None:
        stale = _superseded(store)
        store.hold("wf", stale)

        with pytest.raises(StaleGenerationError):
            store.record_step("wf", "n1", {"status": "success"})

    def test_the_record_is_unchanged_after_a_refusal(self, store: ScopeStore) -> None:
        """Refused means nothing was written, not "written and then flagged".

        A partial write here is worse than the race it replaces: the reader
        sees a step the walk never took.
        """
        stale = _superseded(store)
        store.hold("wf", stale)

        with pytest.raises(StaleGenerationError):
            store.record_step("wf", "n1", {"status": "success"})

        store.hold("wf", None)
        assert store.get_step("wf", "n1") is None

    def test_the_current_generation_writes_normally(self, store: ScopeStore) -> None:
        lease = store.claim_scope("wf", owner="a")
        store.hold("wf", lease.generation)
        store.record_step("wf", "n1", {"status": "success"})
        assert store.get_step("wf", "n1") is not None

    def test_an_unfenced_store_writes_normally(self, store: ScopeStore) -> None:
        """The state every store starts in.

        A store that is not driving a walk — the CLI reading records, a purge, a
        plugin — holds no lease and must not be refused. Fencing is opt-in for
        exactly the code that claimed.
        """
        store.claim_scope("wf", owner="someone-else")
        assert store.generation_for("wf") is None
        store.record_step("wf", "n1", {"status": "success"})
        assert store.get_step("wf", "n1") is not None

    def test_the_refusal_names_the_current_holder(self, store: ScopeStore) -> None:
        """The question on hitting this is always *who has it now*."""
        stale = _superseded(store)
        store.hold("wf", stale)

        with pytest.raises(StaleGenerationError) as exc:
            store.set_position("wf", "n2")
        assert exc.value.owner == "b"
        assert exc.value.held == 2
        assert exc.value.offered == stale


class TestEveryWritePathIsFenced:
    """Enumerated from the store, not listed here.

    A hand-written list is a second copy of the store's surface, stale the first
    time a method is added — and the method most likely to be forgotten is the
    one written by someone who has not read this file.
    """

    #: Writes that must **not** be fenced, each with the reason.
    #:
    #: The lease verbs are how a runner *obtains* a generation, so fencing them
    #: is circular. `delete_scope` and `clear*` are administrative — purge and
    #: `data clear` run without a lease, by design.
    UNFENCED: dict[str, str] = {
        "claim_scope": "claiming is how you get a generation",
        "renew_scope": "carries its generation as an argument and checks it itself",
        "release_scope": "same",
        "delete_scope": "purge runs without a lease",
        "clear": "administrative; moves the whole file aside",
        "clear_state": "state is fenced by its own file, not the scope record",
        "set_state": "same",
        "delete_state": "same",
        "discard_state": "same",
        "ensure_scope": "must work before a claim — `claim` calls it",
    }

    def _scope_writers(self) -> list[str]:
        """Public methods whose first parameter is ``scope_id`` and that write."""
        out = []
        for name, member in inspect.getmembers(ScopeStore, inspect.isfunction):
            if name.startswith("_"):
                continue
            params = list(inspect.signature(member).parameters)
            if len(params) < 2 or params[1] != "scope_id":
                continue
            source = inspect.getsource(member)
            if "self._mutate(" in source:
                out.append(name)
        return sorted(out)

    def test_the_enumeration_finds_something(self) -> None:
        """Guards the test below against passing vacuously."""
        writers = self._scope_writers()
        assert len(writers) >= 8, f"only found {writers}"

    def test_every_scope_write_passes_its_scope_id_to_mutate(self) -> None:
        """`scope_id=` is what arms the check — omitting it silently unfences.

        This is the one that catches a new write method: it will call
        `self._mutate(_apply)` like its neighbours looked like before T6, and
        fail here rather than shipping unfenced.
        """
        unarmed = []
        for name in self._scope_writers():
            if name in self.UNFENCED:
                continue
            source = inspect.getsource(getattr(ScopeStore, name))
            if "scope_id=scope_id" not in source:
                unarmed.append(name)
        assert not unarmed, (
            f"{unarmed} call `self._mutate` without `scope_id=`, so their writes "
            f"are never fenced. Pass it, or add the method to UNFENCED with the "
            f"reason it must not be."
        )

    def test_the_exemptions_still_exist(self) -> None:
        """An exemption naming a method that is gone would hide a real gap."""
        missing = [name for name in self.UNFENCED if not hasattr(ScopeStore, name)]
        assert not missing, f"UNFENCED names methods that no longer exist: {missing}"

    @pytest.mark.parametrize(
        ("method", "args"),
        [
            ("record_step", ("n1", {"status": "success"})),
            ("set_position", ("n1",)),
            ("set_scope_status", ("completed",)),
            ("record_branch", ("a", "b")),
            ("put_gate", ("g", {"status": "pending"})),
            ("record_epilogue", ({"status": "success"},)),
        ],
    )
    def test_each_named_write_is_refused_when_stale(
        self, store: ScopeStore, method: str, args: tuple[Any, ...]
    ) -> None:
        """The enumeration above proves the *shape*; this proves the behaviour.

        A method could pass `scope_id=` and still be reachable by a path that
        skips `_mutate`, which only running it can show.
        """
        stale = _superseded(store)
        store.hold("wf", stale)
        with pytest.raises(StaleGenerationError):
            getattr(store, method)("wf", *args)


class TestFencingInsideABatch:
    def test_a_batch_write_is_also_refused(self, store: ScopeStore) -> None:
        """The walk writes in batches, so an unfenced batch would be a hole
        exactly where the walk lives."""
        stale = _superseded(store)
        store.hold("wf", stale)

        with pytest.raises(StaleGenerationError), store.batch():
            store.record_step("wf", "n1", {"status": "success"})

    def test_a_refused_batch_writes_nothing(self, store: ScopeStore) -> None:
        """`batch` writes on clean exit only, so the refusal discards the block.

        Without this, a walk could get halfway through a node's writes before
        being fenced, which is the partial record the refusal exists to prevent.
        """
        lease = store.claim_scope("wf", owner="a")
        store.hold("wf", lease.generation)
        store.record_step("wf", "before", {"status": "success"})

        store.claim_scope("wf", owner="b", force=True)

        with pytest.raises(StaleGenerationError), store.batch():
            store.record_step("wf", "during", {"status": "success"})

        store.hold("wf", None)
        assert store.get_step("wf", "before") is not None
        assert store.get_step("wf", "during") is None


class TestTheCheckIsInsideTheLock:
    def test_a_claim_between_read_and_write_is_caught(self, store: ScopeStore) -> None:
        """Checking before the write would leave exactly this window open.

        The walk reads the scope, decides what to write, and writes. If someone
        claims in between, a check made at decision time has already passed.
        The check runs against the envelope the write is about to modify.
        """
        lease = store.claim_scope("wf", owner="a")
        store.hold("wf", lease.generation)

        # The walk has read and decided. Now someone else takes the scope.
        store.claim_scope("wf", owner="b", force=True)

        with pytest.raises(StaleGenerationError):
            store.record_step("wf", "n1", {"status": "success"})


class TestTheFenceIsPerScopeNotPerStore:
    """A nested workflow claims its own scope through the *same* store object.

    The first implementation held one generation for the whole store. It looked
    simpler and broke nested workflows outright: the parent's hold fenced every
    write the child made to a **different** scope, so the child could not even
    create its own record — `ensure_scope` was refused.

    Caught by `test_a_nested_workflow_still_owns_its_own_scope`, four tests
    away in the integration suite. These are the unit-level statements of the
    same property, so the next person to reach for one value per store fails
    here first.
    """

    def test_holding_one_scope_does_not_fence_another(self, store: ScopeStore) -> None:
        store.ensure_scope("other")
        parent = store.claim_scope("wf", owner="parent")
        store.hold("wf", parent.generation)

        # The child's own scope has no hold, so its writes go through.
        store.ensure_scope("other", "child-workflow")
        store.record_step("other", "n1", {"status": "success"})

        assert store.get_scope("other")["workflow"] == "child-workflow"

    def test_two_scopes_hold_independent_generations(self, store: ScopeStore) -> None:
        store.ensure_scope("other")
        outer = store.claim_scope("wf", owner="parent")
        inner = store.claim_scope("other", owner="child")
        store.hold("wf", outer.generation)
        store.hold("other", inner.generation)

        store.record_step("wf", "a", {"status": "success"})
        store.record_step("other", "b", {"status": "success"})

        assert store.generation_for("wf") == outer.generation
        assert store.generation_for("other") == inner.generation

    def test_releasing_one_leaves_the_other_held(self, store: ScopeStore) -> None:
        """A child walk finishing must not unfence its parent."""
        store.ensure_scope("other")
        outer = store.claim_scope("wf", owner="parent")
        inner = store.claim_scope("other", owner="child")
        store.hold("wf", outer.generation)
        store.hold("other", inner.generation)

        store.hold("other", None)

        assert store.generation_for("other") is None
        assert store.generation_for("wf") == outer.generation, (
            "the child releasing cleared the parent's fence — the parent's "
            "writes would stop being checked mid-walk"
        )
