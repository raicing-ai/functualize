"""The storage seam: three methods, a lock that spans keys, and a real CAS.

`store-substrate`/T1.

`JsonFileSubstrate` must reproduce today's behaviour exactly — same paths, same
locks, same atomic replace — because T2 moves the stores onto it and nothing
observable may change. So much of this file is "it does what the stores already
do", which is the point.

Two things are *new*, and both are load-bearing:

- **`lock(*keys)`.** An external review of `scope-record-lifecycle` found a
  lock-order inversion that no store can fix, because the caller chooses which
  batch to open first. A substrate that hands out a lock per key reproduces it;
  one that can satisfy several keys with a single lock removes it by
  construction. These tests pin the port's shape, not the one implementation.
- **`write(expect=)`.** A remote store cannot offer `flock` and needs
  compare-and-swap instead. The tempting shortcut is for the filesystem
  implementation to ignore `expect` — which would ship a parameter nothing
  honours and no test can fail on. So it is tested here as behaviour: a second
  writer in between genuinely gets `False`.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from functualize._primitives import substrate as substrate_module
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.errors import SubstrateUnreadableError
from functualize._types.protocols import Stored, StoreSubstrate


@pytest.fixture
def substrate(tmp_path: Path) -> JsonFileSubstrate:
    return JsonFileSubstrate(tmp_path / ".functualize")


def _data(stored: Stored | None) -> dict[str, Any] | None:
    return None if stored is None else stored.data


class TestReadAndWrite:
    def test_round_trip(self, substrate: JsonFileSubstrate) -> None:
        substrate.write("scopes", {"scopes": {"a": {"status": "running"}}})
        assert _data(substrate.read("scopes")) == {
            "scopes": {"a": {"status": "running"}}
        }

    def test_an_unwritten_key_reads_as_none(self, substrate: JsonFileSubstrate) -> None:
        """None and `{}` are different answers, and stores rely on it.

        Nothing has been stored here, versus something empty was. A missing
        `scopes.json` reads as "no scopes"; an unparseable one refuses.
        """
        assert substrate.read("never-written") is None

    def test_an_empty_document_is_not_none(self, substrate: JsonFileSubstrate) -> None:
        substrate.write("empty", {})
        assert _data(substrate.read("empty")) == {}

    def test_writing_replaces(self, substrate: JsonFileSubstrate) -> None:
        substrate.write("k", {"v": 1})
        substrate.write("k", {"v": 2})
        assert _data(substrate.read("k")) == {"v": 2}

    def test_write_reports_success(self, substrate: JsonFileSubstrate) -> None:
        """The bool is the CAS verdict, so an unconditional write is always True."""
        assert substrate.write("k", {"v": 1}) is True

    def test_it_creates_the_directory(self, tmp_path: Path) -> None:
        sub = JsonFileSubstrate(tmp_path / "does" / "not" / "exist")
        sub.write("k", {"v": 1})
        assert _data(sub.read("k")) == {"v": 1}

    def test_nested_keys_become_nested_paths(
        self, substrate: JsonFileSubstrate
    ) -> None:
        """`scope-state/<id>` is the one key family with a slash in it."""
        substrate.write("scope-state/wf-1", {"state": {"k": 1}})
        assert _data(substrate.read("scope-state/wf-1")) == {"state": {"k": 1}}
        assert (substrate.root / "scope-state" / "wf-1.json").exists()


class TestCompareAndSwap:
    """`expect` is honoured, not accepted and dropped.

    A filesystem gets exclusion from `flock` and could ignore `expect`
    entirely. It does not, because a port member that no shipped implementation
    honours is a gate that cannot fail — the remote substrate in T7 would be the
    first thing ever to exercise it.
    """

    def test_a_matching_revision_writes(self, substrate: JsonFileSubstrate) -> None:
        substrate.write("k", {"v": 1})
        stored = substrate.read("k")
        assert stored is not None
        assert substrate.write("k", {"v": 2}, expect=stored.revision) is True
        assert _data(substrate.read("k")) == {"v": 2}

    def test_a_stale_revision_refuses(self, substrate: JsonFileSubstrate) -> None:
        """The whole point: someone else wrote between the read and the write."""
        substrate.write("k", {"v": 1})
        stored = substrate.read("k")
        assert stored is not None
        substrate.write("k", {"v": "someone else"})  # the interleaved writer

        assert substrate.write("k", {"v": 2}, expect=stored.revision) is False
        assert _data(substrate.read("k")) == {"v": "someone else"}, (
            "a refused compare-and-swap still wrote"
        )

    def test_expecting_a_document_that_is_gone_refuses(
        self, substrate: JsonFileSubstrate
    ) -> None:
        substrate.write("k", {"v": 1})
        stored = substrate.read("k")
        assert stored is not None
        substrate.path_for("k").unlink()

        assert substrate.write("k", {"v": 2}, expect=stored.revision) is False

    def test_expecting_over_an_unreadable_document_refuses(
        self, substrate: JsonFileSubstrate
    ) -> None:
        """Refuses rather than raising — and rather than overwriting.

        Whatever is there was not written by this caller's read-modify-write, so
        the compare has failed; that is the ordinary CAS answer. Raising would
        make `write` a second place that decides whether unreadable is fatal,
        which is the store's call.
        """
        substrate.write("k", {"v": 1})
        stored = substrate.read("k")
        assert stored is not None
        substrate.path_for("k").write_text("{not json")

        assert substrate.write("k", {"v": 2}, expect=stored.revision) is False
        assert substrate.path_for("k").read_text() == "{not json"

    def test_no_expect_overwrites_unconditionally(
        self, substrate: JsonFileSubstrate
    ) -> None:
        """`expect=None` is "I hold the lock", not "compare against nothing"."""
        substrate.write("k", {"v": 1})
        substrate.write("k", {"v": 2})
        assert substrate.write("k", {"v": 3}) is True

    def test_the_revision_follows_the_content(
        self, substrate: JsonFileSubstrate
    ) -> None:
        substrate.write("k", {"v": 1})
        first = substrate.read("k")
        substrate.write("k", {"v": 2})
        second = substrate.read("k")
        assert first is not None and second is not None
        assert first.revision != second.revision

    def test_rewriting_identical_content_keeps_the_revision(
        self, substrate: JsonFileSubstrate
    ) -> None:
        """It is a content token, so an idempotent write does not invalidate it.

        A counter would refuse the second caller here even though the document
        it read is exactly the document that is there.
        """
        substrate.write("k", {"v": 1})
        first = substrate.read("k")
        substrate.write("k", {"v": 1})
        second = substrate.read("k")
        assert first is not None and second is not None
        assert first.revision == second.revision

    def test_revisions_differ_between_keys(self, substrate: JsonFileSubstrate) -> None:
        substrate.write("a", {"v": 1})
        substrate.write("b", {"v": 2})
        a, b = substrate.read("a"), substrate.read("b")
        assert a is not None and b is not None
        assert a.revision != b.revision


class TestItRefusesRatherThanDeciding:
    """Whether unreadable is fatal is the **store's** call, not storage's.

    `fresh_format` degrades to an empty envelope because its content is
    recomputable; `scope_format` refuses because a scope is the only trace of an
    in-flight run. A substrate that chose for them would take a decision about
    meaning it has no standing to take.
    """

    def test_unparseable_raises(self, substrate: JsonFileSubstrate) -> None:
        substrate.write("k", {"v": 1})
        substrate.path_for("k").write_text("{not json")
        with pytest.raises(SubstrateUnreadableError):
            substrate.read("k")

    def test_a_non_object_raises(self, substrate: JsonFileSubstrate) -> None:
        substrate.write("k", {"v": 1})
        substrate.path_for("k").write_text("[1, 2, 3]")
        with pytest.raises(SubstrateUnreadableError):
            substrate.read("k")

    def test_the_error_names_the_key(self, substrate: JsonFileSubstrate) -> None:
        """A key, not a path — a substrate over S3 has no path to report."""
        substrate.write("scopes", {})
        substrate.path_for("scopes").write_text("{not json")
        with pytest.raises(SubstrateUnreadableError) as exc:
            substrate.read("scopes")
        assert exc.value.key == "scopes"

    def test_the_file_is_left_in_place(self, substrate: JsonFileSubstrate) -> None:
        """A refusal must be repeatable.

        If reading moved the file aside, the next read would find nothing, take
        it as "never written", and carry on — silently, which is the failure
        `scope_format`'s refusal exists to prevent.
        """
        substrate.write("k", {})
        substrate.path_for("k").write_text("{not json")
        with pytest.raises(SubstrateUnreadableError):
            substrate.read("k")
        assert substrate.path_for("k").read_text() == "{not json"


class TestAKeyCannotEscape:
    @pytest.mark.parametrize("bad", ["../outside", "a/../../b", "/absolute", ""])
    def test_traversal_is_rejected(
        self, substrate: JsonFileSubstrate, bad: str
    ) -> None:
        """Rejected rather than sanitised.

        A key that could name a document outside the root is a bug at its
        source; quietly rewriting it would hide that. The same call
        `scope_state_path` makes for scope ids.
        """
        with pytest.raises(ValueError, match="substrate key"):
            substrate.path_for(bad)

    def test_a_bad_key_is_rejected_by_read_and_write(
        self, substrate: JsonFileSubstrate
    ) -> None:
        """Checked at the boundary, not only by the path helper."""
        with pytest.raises(ValueError, match="substrate key"):
            substrate.read("../escape")
        with pytest.raises(ValueError, match="substrate key"):
            substrate.write("../escape", {})

    def test_a_dot_inside_a_segment_is_fine(self, substrate: JsonFileSubstrate) -> None:
        """`..` is a segment, not a substring — a scope id may contain dots."""
        substrate.write("scope-state/build.v2", {"state": {}})
        assert _data(substrate.read("scope-state/build.v2")) == {"state": {}}


class TestLockSpansKeys:
    """The shape that lets a substrate remove the lock-order inversion.

    These pin the **port**, not `JsonFileSubstrate`'s per-file answer: a
    single-lock substrate must satisfy them too.
    """

    def test_one_key_excludes_another_writer(
        self, substrate: JsonFileSubstrate
    ) -> None:
        substrate.write("k", {"v": 0})
        order: list[str] = []

        def waiter() -> None:
            with substrate.lock("k"):
                order.append("second")

        with substrate.lock("k"):
            thread = threading.Thread(target=waiter)
            thread.start()
            # The waiter cannot get in while this block holds the lock.
            thread.join(timeout=0.3)
            order.append("first")
        thread.join(timeout=15)

        assert order == ["first", "second"], (
            f"the second writer entered while the first held the lock: {order}"
        )

    def test_several_keys_are_all_held(self, substrate: JsonFileSubstrate) -> None:
        with substrate.lock("a", "b", "c"):
            for key in ("a", "b", "c"):
                assert substrate.path_for(key).with_suffix(".json.lock").exists()

    def test_keys_are_acquired_in_a_stable_order(
        self, substrate: JsonFileSubstrate, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sorted, so the many-lock implementation cannot deadlock against itself.

        Two callers asking for the same set in different orders still acquire in
        one order. It does **not** help against a caller that takes one lock,
        does something, then takes another — that inversion is only removed by a
        substrate with a single lock, which is what this port makes possible.

        Asserted on the acquisition *order* rather than by racing two threads,
        because the race cannot fail here: `file_lock` gives up after ten
        seconds and proceeds, so an inverted pair stalls and loses a write
        instead of hanging. A timing assertion on that would be flaky, and a
        liveness assertion passes whether or not the keys are sorted — measured:
        deleting the `sorted()` failed nothing.
        """
        asked: list[str] = []
        real = substrate_module.file_lock

        @contextmanager
        def spy(path: Path | str, timeout: float = 10.0) -> Iterator[None]:
            asked.append(Path(path).name)
            with real(path, timeout):
                yield

        monkeypatch.setattr(substrate_module, "file_lock", spy)

        with substrate.lock("b", "a", "c"):
            pass

        assert asked == ["a.json", "b.json", "c.json"], (
            f"keys were acquired in the order given, not sorted: {asked}"
        )

    def test_the_same_set_acquires_alike_whatever_the_order_asked(
        self, substrate: JsonFileSubstrate, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The property sorting exists for, stated as the equality it is."""
        runs: list[list[str]] = []
        real = substrate_module.file_lock

        @contextmanager
        def spy(path: Path | str, timeout: float = 10.0) -> Iterator[None]:
            runs[-1].append(Path(path).name)
            with real(path, timeout):
                yield

        monkeypatch.setattr(substrate_module, "file_lock", spy)

        for order in (("scopes", "scope-state/x"), ("scope-state/x", "scopes")):
            runs.append([])
            with substrate.lock(*order):
                pass

        assert runs[0] == runs[1], (
            f"two callers locking the same pair disagreed on the order: {runs}"
        )

    def test_locking_nothing_is_allowed(self, substrate: JsonFileSubstrate) -> None:
        """A store batching zero keys should not have to special-case it."""
        with substrate.lock():
            pass

    def test_the_lock_is_released_on_an_exception(
        self, substrate: JsonFileSubstrate
    ) -> None:
        with pytest.raises(RuntimeError), substrate.lock("k"):
            raise RuntimeError("boom")
        with substrate.lock("k"):  # must not block
            pass

    def test_write_does_not_take_the_lock(self, substrate: JsonFileSubstrate) -> None:
        """A store holds the lock across read-modify-write, so `write` must not.

        `file_lock` opens a fresh descriptor and `flock`s it, so a nested
        acquire would spin for the full ten-second timeout, warn that writes can
        now be lost, and proceed. The guard here is the clock: anything near ten
        seconds means `write` started locking again.
        """
        with substrate.lock("k"):
            started = threading.Event()

            def writer() -> None:
                started.set()
                substrate.write("k", {"v": 1})

            thread = threading.Thread(target=writer)
            thread.start()
            thread.join(timeout=3)
            assert started.is_set()
            assert not thread.is_alive(), (
                "write blocked on a lock the caller already holds"
            )

        assert _data(substrate.read("k")) == {"v": 1}


class TestItSatisfiesTheProtocol:
    def test_the_filesystem_implementation_is_a_substrate(
        self, substrate: JsonFileSubstrate
    ) -> None:
        assert isinstance(substrate, StoreSubstrate)

    def test_a_minimal_implementation_also_satisfies_it(self) -> None:
        """Three members is the whole contract.

        Asserted with an in-memory stand-in written here rather than shipped:
        the point is that the port is small enough to implement, not that this
        particular one exists.
        """

        class InMemory:
            def __init__(self) -> None:
                self.docs: dict[str, tuple[dict[str, Any], int]] = {}
                self.one_lock = threading.RLock()
                self._next = 0

            def read(self, key: str) -> Stored | None:
                found = self.docs.get(key)
                return (
                    None if found is None else Stored(data=found[0], revision=found[1])
                )

            def write(
                self, key: str, payload: dict[str, Any], *, expect: int | None = None
            ) -> bool:
                found = self.docs.get(key)
                if expect is not None and (found is None or found[1] != expect):
                    return False
                self._next += 1
                self.docs[key] = (json.loads(json.dumps(payload)), self._next)
                return True

            @contextmanager
            def lock(self, *keys: str):  # noqa: ANN202 - structural check only
                with self.one_lock:
                    yield

        assert isinstance(InMemory(), StoreSubstrate)

    def test_a_single_lock_substrate_is_expressible(self) -> None:
        """The property the whole port exists for.

        One lock covering every key removes the lock-order inversion by
        construction, instead of asking callers to acquire in a careful order.
        `lock` being variadic is what makes it sayable.
        """
        acquisitions: list[tuple[str, ...]] = []

        class OneLock:
            def __init__(self) -> None:
                self._lock = threading.RLock()

            def read(self, key: str) -> Stored | None:
                return None

            def write(
                self, key: str, payload: dict[str, Any], *, expect: int | None = None
            ) -> bool:
                return True

            @contextmanager
            def lock(self, *keys: str):  # noqa: ANN202 - structural check only
                acquisitions.append(keys)
                with self._lock:
                    yield

        sub = OneLock()
        assert isinstance(sub, StoreSubstrate)
        with sub.lock("scopes"), sub.lock("scope-state/a"):
            pass  # re-entrant: one lock, taken twice, cannot self-deadlock

        assert acquisitions == [("scopes",), ("scope-state/a",)]
