"""The example substrate, held to the port it claims to satisfy.

A substrate is six methods, and the interesting half of the test is the pair of
distinctions the stores actually depend on:

- **None is not an empty document.** A missing `scopes` reads as "no scopes"; an
  empty one reads as "a scope file that happens to be empty". A substrate that
  collapses them makes every store's discard rule wrong.
- **`clear` is not `delete`.** `clear` is the documented way out of a document
  that cannot be read and may keep a copy; `delete` is the scope purge and must
  not.

Everything else is bookkeeping.
"""

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from functualize_state_memory import MemoryStatePlugin, MemorySubstrate

from functualize._types.protocols import StoreSubstrate


class TestItSatisfiesThePort:
    def test_it_is_a_store_substrate(self):
        assert isinstance(MemorySubstrate(), StoreSubstrate)

    def test_every_member_is_present(self):
        substrate = MemorySubstrate()
        for name in ("read", "write", "lock", "clear", "delete", "describe"):
            assert hasattr(substrate, name), name


class TestReadAndWrite:
    def test_a_document_comes_back(self):
        substrate = MemorySubstrate()
        substrate.write("scopes", {"format_version": 1, "scopes": {}})
        stored = substrate.read("scopes")
        assert stored is not None
        assert stored.data == {"format_version": 1, "scopes": {}}

    def test_nothing_written_reads_as_none(self):
        assert MemorySubstrate().read("scopes") is None

    def test_an_empty_document_is_not_nothing(self):
        """The distinction every store's discard rule rests on."""
        substrate = MemorySubstrate()
        substrate.write("scopes", {})
        stored = substrate.read("scopes")
        assert stored is not None and stored.data == {}

    def test_the_revision_moves_on_every_write(self):
        substrate = MemorySubstrate()
        substrate.write("runs", {"n": 1})
        first = substrate.read("runs").revision
        substrate.write("runs", {"n": 2})
        assert substrate.read("runs").revision != first

    def test_a_reader_cannot_mutate_what_is_stored(self):
        substrate = MemorySubstrate()
        substrate.write("runs", {"n": 1})
        substrate.read("runs").data["n"] = 99
        assert substrate.read("runs").data == {"n": 1}


class TestCompareAndSwap:
    """The half a substrate that cannot lock relies on."""

    def test_a_matching_revision_writes(self):
        substrate = MemorySubstrate()
        substrate.write("runs", {"n": 1})
        revision = substrate.read("runs").revision
        assert substrate.write("runs", {"n": 2}, expect=revision) is True

    def test_a_stale_revision_is_refused_and_changes_nothing(self):
        substrate = MemorySubstrate()
        substrate.write("runs", {"n": 1})
        stale = substrate.read("runs").revision
        substrate.write("runs", {"n": 2})

        assert substrate.write("runs", {"n": 3}, expect=stale) is False
        assert substrate.read("runs").data == {"n": 2}

    def test_no_expectation_writes_unconditionally(self):
        substrate = MemorySubstrate()
        substrate.write("runs", {"n": 1})
        assert substrate.write("runs", {"n": 2}) is True


class TestClearIsNotDelete:
    def test_clear_says_where_it_went(self):
        substrate = MemorySubstrate()
        substrate.write("scopes", {"a": 1})
        assert substrate.clear("scopes") is not None
        assert substrate.read("scopes") is None

    def test_clearing_nothing_answers_none(self):
        assert MemorySubstrate().clear("scopes") is None

    def test_delete_reports_whether_there_was_one(self):
        substrate = MemorySubstrate()
        substrate.write("scopes", {"a": 1})
        assert substrate.delete("scopes") is True
        assert substrate.delete("scopes") is False


class TestTheLockIsReentrant:
    def test_a_nested_lock_does_not_deadlock(self):
        """A store may already hold it when a batch takes it again."""
        substrate = MemorySubstrate()
        with substrate.lock("scopes"), substrate.lock("scopes", "runs"):
            substrate.write("scopes", {"a": 1})
        assert substrate.read("scopes").data == {"a": 1}

    def test_it_serialises_two_threads(self):
        substrate = MemorySubstrate()
        substrate.write("runs", {"n": 0})
        errors = []

        def bump():
            try:
                for _ in range(200):
                    with substrate.lock("runs"):
                        current = substrate.read("runs").data["n"]
                        substrate.write("runs", {"n": current + 1})
            except Exception as exc:  # pragma: no cover - a failure is the report
                errors.append(exc)

        threads = [threading.Thread(target=bump) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not errors
        assert substrate.read("runs").data["n"] == 800


class TestDescribe:
    def test_it_names_the_document(self):
        assert "runs" in MemorySubstrate().describe("runs")


class TestThePlugin:
    def test_it_installs_the_substrate_at_app_ready(self):
        """The whole of "bring your own storage": one assignment, at one hook."""
        plugin = MemoryStatePlugin()
        assert plugin.substrate is None

        class _App:
            substrate = None

        app = _App()
        plugin._on_app_ready(app)

        assert isinstance(app.substrate, MemorySubstrate)
        assert app.substrate is plugin.substrate

    def test_it_registers_on_app_ready_and_not_before(self):
        registered = []

        class _Hooks:
            def register_global(self, event, handler):
                registered.append((event, handler))

        class _App:
            hook_registry = _Hooks()
            substrate = None

        plugin = MemoryStatePlugin()
        plugin(_App())

        assert len(registered) == 1
        from functualize._events.hooks import HookEvent

        assert registered[0][0] == HookEvent.APP_READY
        assert plugin.substrate is None, "installing before APP_READY is too early"
