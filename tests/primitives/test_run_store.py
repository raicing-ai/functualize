"""The run log: a third file, and the one that discards.

`state.json` discards on a bad version, `scopes.json` refuses, and this file
discards — and getting that wrong is the expensive mistake, not an
organisational preference. A scope is the only trace of work in flight; losing
it spends a human's approval on a run that no longer exists. A run record is an
observation of something that already happened.

The consequence worth testing rather than asserting in prose: if run records
lived in `scopes.json`, the **strictest** policy would govern the **most
voluminous** data, and one corrupt run log would block every workflow in the
project. `TestTheReadRuleIsTheOppositeOfScopes` pins both halves against each
other, so a future refactor that merges the files fails here with the reason.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize._primitives.run_format import (
    EVENTS_PER_RUN_LIMIT,
    RUNS_FILENAME,
    RUNS_KEY,
    RUNS_LIMIT,
    RUNS_VERSION,
    empty_runs,
    stamp_runs,
)
from functualize._primitives.run_store import RunStore, new_run_id, runner_identity
from functualize._primitives.scope_format import SCOPES_KEY
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.errors import ScopeStoreUnreadableError


@pytest.fixture
def store(tmp_path: Path) -> RunStore:
    return RunStore(JsonFileSubstrate(tmp_path))


class TestTheEnvelope:
    def test_a_missing_file_reads_as_no_runs(self, store: RunStore) -> None:
        assert store.run_ids() == []
        assert store.substrate.read(RUNS_KEY) is None, (
            "reading must not create the document"
        )

    def test_it_stamps_the_version_on_write(self, store: RunStore) -> None:
        store.open_run({"job": "build", "surface": "func.job"})

        data = store.substrate.read(RUNS_KEY).data
        assert data["format_version"] == RUNS_VERSION
        assert set(data) == {"format_version", "runs", "events"}

    def test_the_documents_share_one_substrate(self, tmp_path: Path) -> None:
        """One upward walk, one root — they cannot land in different modes.

        This used to assert that two independent resolutions agreed. They no
        longer *can* disagree: there is one substrate and the stores are handed
        it, so what is left to check is that the sibling layout is unchanged
        and that a `RunStore` and a `ScopeStore` built for one project really
        are built on the same object.
        """
        (tmp_path / ".functualize").mkdir()
        substrate = JsonFileSubstrate.for_project(tmp_path)

        assert substrate.path_for(RUNS_KEY).name == RUNS_FILENAME
        assert substrate.path_for(RUNS_KEY).parent == tmp_path / ".functualize"
        assert RunStore.for_project(tmp_path).substrate.path_for(
            RUNS_KEY
        ) == ScopeStore.for_project(tmp_path).substrate.path_for(RUNS_KEY)


class TestTheReadRuleIsTheOppositeOfScopes:
    """The discard rule, asserted against the refusal it is the opposite of."""

    @pytest.mark.parametrize(
        ("label", "content"),
        [
            ("truncated json", '{"format_version": 1, "runs": {'),
            ("not an envelope", '["a", "list"]'),
            ("a version from the future", '{"format_version": 99, "runs": {}}'),
            (
                "runs is not a mapping",
                '{"format_version": 1, "runs": [], "events": {}}',
            ),
        ],
    )
    def test_an_unusable_run_log_reads_as_empty(
        self, label: str, content: str, tmp_path: Path
    ) -> None:
        substrate = JsonFileSubstrate(tmp_path)
        substrate.path_for(RUNS_KEY).parent.mkdir(parents=True, exist_ok=True)
        substrate.path_for(RUNS_KEY).write_text(content)

        assert RunStore(substrate)._read() == empty_runs(), label

    def test_the_bytes_are_left_in_place(self, tmp_path: Path) -> None:
        """Discarding the content is not destroying it.

        A human debugging a bad write must still find what was written.
        """
        substrate = JsonFileSubstrate(tmp_path)
        path = substrate.path_for(RUNS_KEY)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json at all")

        RunStore(substrate)._read()

        assert path.read_text() == "not json at all"

    def test_the_same_input_makes_scopes_refuse(self, tmp_path: Path) -> None:
        """The falsifier for the rule above, and the reason for the third file.

        If this ever stops raising, the two files have converged on one policy —
        and whichever one they converged on is wrong for the other's data.
        """
        substrate = JsonFileSubstrate(tmp_path)
        path = substrate.path_for(SCOPES_KEY)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"format_version": 99, "scopes": {}}')

        with pytest.raises(ScopeStoreUnreadableError):
            ScopeStore(substrate).scope_ids()


class TestRunRecords:
    def test_a_run_opens_running_and_closes_with_its_status(
        self, store: RunStore
    ) -> None:
        run_id = store.open_run({"job": "build", "surface": "func.job"})

        opened = store.get_run(run_id)
        assert opened is not None
        assert opened["status"] == "running"
        assert opened["started_at"] and opened["ended_at"] is None

        store.close_run(run_id, "success", return_value_reusable=True)

        closed = store.get_run(run_id)
        assert closed is not None
        assert closed["status"] == "success"
        assert closed["ended_at"]
        assert closed["return_value_reusable"] is True

    def test_closing_an_unknown_run_is_ignored(self, store: RunStore) -> None:
        """A writer that died between open and close has already said enough.

        Raising would turn a lost observation into a failed run.
        """
        store.close_run("run-nonexistent", "success")

        assert store.run_ids() == []

    def test_argument_values_are_never_stored(self, store: RunStore) -> None:
        """The history ring's rule, applied here — and a run log is read by more
        people than a job's caller."""
        run_id = store.open_run(
            {
                "job": "deploy",
                "surface": "func.job",
                "args_hash": "abc123",
                "kwargs": {"token": "hunter2"},
                "arguments": {"token": "hunter2"},
            }
        )

        record = store.get_run(run_id)
        assert record is not None
        assert record["args_hash"] == "abc123"
        assert "kwargs" not in record
        assert "arguments" not in record
        assert "hunter2" not in store.substrate.path_for(RUNS_KEY).read_text()

    def test_children_are_findable_from_their_parent(self, store: RunStore) -> None:
        """The relationship history drops on purpose.

        A nested `rc.invoke` child and a parallel batch item both belong to the
        run that launched them, and this is where that tree is answerable.
        """
        parent = store.open_run({"job": "release", "surface": "func.job"})
        child = store.open_run(
            {"job": "build", "surface": "engine.step", "parent_run_id": parent}
        )
        store.open_run({"job": "unrelated", "surface": "func.job"})

        children = store.children_of(parent)

        assert [c["run_id"] for c in children] == [child]

    def test_recent_runs_are_newest_first(self, store: RunStore) -> None:
        ids = [
            store.open_run({"job": f"j{i}", "surface": "func.job"}) for i in range(5)
        ]

        recent = store.recent_runs(limit=3)

        assert [r["run_id"] for r in recent] == list(reversed(ids[-3:]))


class TestRunIds:
    def test_they_sort_in_the_order_they_were_minted(self) -> None:
        """A **monotonic** ULID, which a plain one is not.

        Several ids minted in one millisecond share a timestamp prefix, and a
        freshly drawn random tail then orders them arbitrarily — which is how
        this was written first, and what `test_recent_runs_are_newest_first`
        caught. `rc.invoke_parallel` opens a batch of runs in a few
        microseconds, so a millisecond collision is the common case here rather
        than the exotic one.
        """
        ids = [new_run_id() for _ in range(200)]

        assert ids == sorted(ids), "ids must sort in mint order"
        assert all(i.startswith("run-") for i in ids)

    def test_a_backwards_clock_does_not_reorder_them(self, monkeypatch) -> None:
        """NTP, or a VM resume. An id that sorts *before* runs already recorded
        would put a new run in the middle of the log."""
        import functualize._primitives.run_store as module

        first = new_run_id()
        monkeypatch.setattr(module.time, "time", lambda: 0.0)
        second = new_run_id()

        assert second > first

    def test_they_avoid_the_ambiguous_letters(self) -> None:
        """Crockford base32: no I, L, O or U, so an id read aloud or copied out
        of a log cannot become a different one."""
        body = new_run_id().removeprefix("run-")

        assert not set(body) & set("ILOU")

    def test_they_are_unique(self) -> None:
        assert len({new_run_id() for _ in range(500)}) == 500


class TestTheRings:
    def test_runs_are_capped_newest_kept(self, store: RunStore) -> None:
        for i in range(RUNS_LIMIT + 20):
            store.open_run({"job": f"j{i}", "surface": "func.job"})

        ids = store.run_ids()
        assert len(ids) == RUNS_LIMIT
        assert ids == sorted(ids), "the ring must keep chronological order"

    def test_events_are_capped_per_run(self, store: RunStore) -> None:
        run_id = store.open_run({"job": "walk", "surface": "func.job"})
        for i in range(EVENTS_PER_RUN_LIMIT + 10):
            store.append_event(run_id, {"event_name": "step.done", "resource": str(i)})

        events = store.events_for(run_id)
        assert len(events) == EVENTS_PER_RUN_LIMIT
        assert events[-1]["resource"] == str(EVENTS_PER_RUN_LIMIT + 9)

    def test_an_evicted_runs_events_go_with_it(self, tmp_path: Path) -> None:
        """Events outliving the run they describe is a leak that only shows up
        on a long-lived project — the worst place to find one.

        The oldest id is used deliberately: ULIDs sort chronologically, so a
        run named with all zeros is the first thing the ring evicts.
        """
        substrate = JsonFileSubstrate(tmp_path)
        oldest = "run-0000000000AAAAAAAAAAAAAAAA"
        substrate.write(
            RUNS_KEY,
            stamp_runs(
                {
                    "runs": {oldest: {"job": "old", "status": "success"}},
                    "events": {oldest: [{"seq": 1, "event_name": "job.execute.end"}]},
                }
            ),
        )
        store = RunStore(substrate)
        assert len(store.events_for(oldest)) == 1, "fixture precondition"

        for i in range(RUNS_LIMIT + 5):
            store.open_run({"job": f"j{i}", "surface": "func.job"})

        assert oldest not in store.run_ids(), "fixture precondition: it was evicted"
        assert store.events_for(oldest) == [], (
            "an evicted run's events should not outlive it"
        )

    def test_an_orphans_events_are_kept(self, tmp_path: Path) -> None:
        """The distinction the first draft of `_trim` did not make.

        A run this file has never *seen* is not the same as one it evicted. The
        subscriber that writes events and the code that opens records are
        deliberately uncoordinated (the bus does no file I/O, spec AC-5), so an
        event can legitimately arrive first. Deleting it would make the log lie
        about what it observed — and these two tests are what stop either rule
        being restated as the other.
        """
        store = RunStore(JsonFileSubstrate(tmp_path))
        store.append_event("run-never-opened", {"event_name": "job.execute.start"})

        store.open_run({"job": "unrelated", "surface": "func.job"})

        assert len(store.events_for("run-never-opened")) == 1


class TestEvents:
    def test_seq_is_monotonic_per_run(self, store: RunStore) -> None:
        """Replay order without comparing timestamps — which two processes on
        two clocks cannot do reliably."""
        a = store.open_run({"job": "a", "surface": "func.job"})
        b = store.open_run({"job": "b", "surface": "func.job"})

        assert store.append_event(a, {"event_name": "one"}) == 1
        assert store.append_event(b, {"event_name": "one"}) == 1
        assert store.append_event(a, {"event_name": "two"}) == 2

        assert [e["seq"] for e in store.events_for(a)] == [1, 2]
        assert [e["seq"] for e in store.events_for(b)] == [1]

    def test_an_event_for_an_unopened_run_is_kept(self, store: RunStore) -> None:
        """The subscriber that writes events and the code that opens records are
        deliberately uncoordinated — the bus does no file I/O (spec AC-5).
        Dropping the event would make the log lie about what it saw.
        """
        store.append_event("run-never-opened", {"event_name": "job.execute.start"})

        assert len(store.events_for("run-never-opened")) == 1


class TestTheBatch:
    def test_it_writes_once_at_the_end(self, store: RunStore) -> None:
        with store.batch() as batched:
            first = batched.open_run({"job": "a", "surface": "func.job"})
            batched.append_event(first, {"event_name": "start"})
            batched.close_run(first, "success")

        record = store.get_run(first)
        assert record is not None and record["status"] == "success"
        assert len(store.events_for(first)) == 1

    def test_an_exception_discards_the_block(self, store: RunStore) -> None:
        """All-or-nothing, so a reader never finds half of one node's writes."""
        with pytest.raises(RuntimeError), store.batch() as batched:
            batched.open_run({"job": "a", "surface": "func.job"})
            raise RuntimeError("boom")

        assert store.run_ids() == []


def test_runner_identity_names_a_machine_and_a_process() -> None:
    """Not a uuid: when a lease looks stuck the question is *which machine and
    which process*, and an opaque token sends the reader to a log to find out."""
    identity = runner_identity()

    assert "/pid-" in identity
    assert identity.split("/pid-")[1].isdigit()
