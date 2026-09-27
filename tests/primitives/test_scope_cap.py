"""`scopes.json` is bounded, and the bound cannot evict a live run.

`scope-record-lifecycle`/T2, AC-2. `scopes.json` was the only one of the three
stores with no cap — `state_format` has `HISTORY_LIMIT = 200` and `run_format`
has `RUNS_LIMIT = 500`. It reached 2,188 records on a real project, at 58 ms per
state write.

The half that needs the most care is the refusal: a workflow parked at a gate
must survive **any** amount of unrelated traffic. Evicting it spends a human's
approval on a run that no longer exists, which is the failure durable state
exists to prevent. So an over-cap file holding nothing finished stays over cap.

`runtime-schema-migrations`/T5 added the policy those caps read
(`_types/retention.py`, AC7), which is why the last two classes here are about
one value rather than about `scopes.json`: the same policy bounds the scope
ring, the scope event ring and the run log, and both trims are exercised with a
smaller one so "the policy is read" is proven rather than assumed. The run-log
case lives here because the two files' caps are one value; the run log's own
behaviour is `tests/primitives/test_run_store.py`.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from functualize._primitives.run_format import RUNS_VERSION, stamp_runs
from functualize._primitives.scope_format import (
    EVENTS_PER_SCOPE_LIMIT,
    SCOPES_KEY,
    SCOPES_LIMIT,
    TERMINAL_SCOPE_STATUSES,
    normalize_scopes,
    stamp_scopes,
)
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.lifecycle import SCOPE, ScopeStatus
from functualize._types.retention import DEFAULT_RETENTION, RetentionPolicy

_RETENTION = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "functualize"
    / "_types"
    / "retention.py"
)


def _envelope(records: dict[str, str]) -> dict[str, object]:
    """An envelope of `{scope_id: status}`, in the order given."""
    return {"scopes": {sid: {"status": status} for sid, status in records.items()}}


def _write(substrate: JsonFileSubstrate, records: dict[str, str]) -> dict[str, object]:
    substrate.write(SCOPES_KEY, stamp_scopes(_envelope(records)))
    stored = substrate.read(SCOPES_KEY)
    assert stored is not None
    return normalize_scopes(stored.data, where=substrate.describe(SCOPES_KEY))


class TestTheCapBounds:
    def test_a_file_under_the_cap_is_untouched(self, tmp_path: Path) -> None:
        path = JsonFileSubstrate(tmp_path)
        records = {f"done-{i:04d}": "completed" for i in range(SCOPES_LIMIT)}
        assert len(_write(path, records)["scopes"]) == SCOPES_LIMIT

    def test_going_over_evicts_down_to_the_cap(self, tmp_path: Path) -> None:
        path = JsonFileSubstrate(tmp_path)
        records = {f"done-{i:04d}": "completed" for i in range(SCOPES_LIMIT + 50)}
        assert len(_write(path, records)["scopes"]) == SCOPES_LIMIT

    def test_the_oldest_go_first(self, tmp_path: Path) -> None:
        """Oldest is insertion order — scope ids do not sort chronologically.

        Run ids are ULIDs and sort by time; a scope id is `<job>-<hex8>` and
        does not. Dict order is the creation order, and JSON preserves it.
        """
        path = JsonFileSubstrate(tmp_path)
        records = {f"done-{i:04d}": "completed" for i in range(SCOPES_LIMIT + 10)}
        kept = _write(path, records)["scopes"]

        assert "done-0000" not in kept
        assert "done-0009" not in kept
        assert "done-0010" in kept
        assert f"done-{SCOPES_LIMIT + 9:04d}" in kept


class TestALiveScopeIsNeverEvicted:
    """The half that makes the cap safe. AC-2 states it as a requirement."""

    def test_a_blocked_scope_survives_the_cap_being_exceeded(
        self, tmp_path: Path
    ) -> None:
        """One parked workflow, buried under twice the cap in finished runs."""
        path = JsonFileSubstrate(tmp_path)
        records: dict[str, str] = {"parked": "blocked"}
        records.update({f"done-{i:04d}": "completed" for i in range(SCOPES_LIMIT * 2)})

        kept = _write(path, records)["scopes"]

        assert "parked" in kept, (
            "a workflow blocked at a gate was evicted by unrelated traffic — "
            "its resume point and any deposited approval are gone"
        )
        assert len(kept) == SCOPES_LIMIT

    def test_a_running_scope_survives_too(self, tmp_path: Path) -> None:
        """`running` is live as well — a run in flight is not a candidate."""
        path = JsonFileSubstrate(tmp_path)
        records: dict[str, str] = {"inflight": "running"}
        records.update({f"done-{i:04d}": "completed" for i in range(SCOPES_LIMIT + 5)})

        assert "inflight" in _write(path, records)["scopes"]

    def test_an_all_live_file_stays_over_the_cap(self, tmp_path: Path) -> None:
        """The deliberate non-guarantee, asserted so nobody "fixes" it.

        A file over the cap holding nothing finished stays over the cap. The
        alternative — evicting something live to satisfy a number — is the
        failure this whole feature exists to prevent.
        """
        path = JsonFileSubstrate(tmp_path)
        over = SCOPES_LIMIT + 25
        records = {f"live-{i:04d}": "blocked" for i in range(over)}

        assert len(_write(path, records)["scopes"]) == over

    def test_only_finished_statuses_are_evictable(self, tmp_path: Path) -> None:
        """Pins the vocabulary rather than trusting the constant's name.

        `_primitives` cannot import `app._workflow_view.TERMINAL_STATES` (the
        derived display vocabulary), so the eviction set is read from the scope
        machine and the display set is not this file's question. What is
        asserted is the split D1 = A made: each status the machine calls
        *evictable* really is evicted, and the two live ones really are not.
        """
        for status in sorted(TERMINAL_SCOPE_STATUSES):
            path = JsonFileSubstrate(tmp_path / status)
            records = {"candidate": status}
            records.update({f"done-{i:04d}": "completed" for i in range(SCOPES_LIMIT)})
            assert "candidate" not in _write(path, records)["scopes"], (
                f"{status!r} is in TERMINAL_SCOPE_STATUSES but was not evicted"
            )

        for status in ("running", "blocked"):
            path = JsonFileSubstrate(tmp_path / status)
            records = {"candidate": status}
            records.update({f"done-{i:04d}": "completed" for i in range(SCOPES_LIMIT)})
            assert "candidate" in _write(path, records)["scopes"], (
                f"{status!r} is live and must never be evicted"
            )


class TestTheCapAppliesThroughTheStore:
    """Not just the format helper — the object everything actually uses."""

    def test_writing_through_scopestore_trims(self, tmp_path: Path) -> None:
        path = JsonFileSubstrate(tmp_path)
        store = ScopeStore(path)
        with store.batch():
            for i in range(SCOPES_LIMIT + 20):
                store.ensure_scope(f"done-{i:04d}")
                store.set_scope_status(f"done-{i:04d}", "completed")

        stored = path.read(SCOPES_KEY)
        assert stored is not None
        on_disk = stored.data["scopes"]
        assert len(on_disk) == SCOPES_LIMIT


# ----------------------------------------------------------------------
# One policy value (T5, AC7)
# ----------------------------------------------------------------------


class TestThePolicyIsOneValue:
    def test_the_three_cap_constants_are_the_policys_count(self) -> None:
        """The constants stay importable — their *value* moves to the policy.

        `_cli/builtins.py` prints `Scopes: N of SCOPES_LIMIT`,
        `scope_store.py` bounds a scope's events, and several test files import
        one or the other, so the names have to stay. What changed is where the
        number comes from: three literals spelling `500` were three answers.
        """
        assert DEFAULT_RETENTION.max_records == SCOPES_LIMIT
        assert DEFAULT_RETENTION.max_records == EVENTS_PER_SCOPE_LIMIT

    def test_the_eviction_set_is_the_scope_machines_evictable_set(self) -> None:
        """D1 = A split absorbing from evictable, and the cap names the machine's.

        `TERMINAL_SCOPE_STATUSES` was a literal three-element set whose comment
        called it "values a scope can never leave" — untrue since a plain
        `resume <id>` re-enters a completed scope. The set a cap may drop is a
        property of the scope machine (`_types/lifecycle.py`, `schema.md` §1.1),
        so this reads it from there.
        """
        assert SCOPE.evictable == TERMINAL_SCOPE_STATUSES
        assert set(SCOPE.evictable) == {"completed", "failed", "cancelled"}
        assert SCOPE.absorbing == {ScopeStatus.CANCELLED}


class TestASmallerPolicyIsHonoured:
    """Both trims, driven by a policy a caller could really hand over."""

    def test_the_scope_ring_honours_a_smaller_policy(self) -> None:
        policy = RetentionPolicy(max_records=3)
        records = {f"done-{i:04d}": "completed" for i in range(6)}

        kept = stamp_scopes(_envelope(records), policy)["scopes"]

        assert list(kept) == ["done-0003", "done-0004", "done-0005"]

    def test_the_run_log_honours_a_smaller_policy(self) -> None:
        """Runs and their events together — an evicted run takes its log along."""
        policy = RetentionPolicy(max_records=2)
        envelope = {
            "format_version": RUNS_VERSION,
            "runs": {f"01J{i:04d}": {"status": "success"} for i in range(5)},
            "events": {f"01J{i:04d}": [{"n": i}] for i in range(5)},
        }

        trimmed = stamp_runs(envelope, policy)

        assert list(trimmed["runs"]) == ["01J0003", "01J0004"]
        assert list(trimmed["events"]) == ["01J0003", "01J0004"]

    def test_the_default_policy_is_evictable_only(self) -> None:
        """The safety property, stated as the default rather than as behaviour.

        A live scope survives a smaller cap exactly as it survives the default
        one (`TestALiveScopeIsNeverEvicted` above); this is the flag that says
        why, so a later change to `False` has to be deliberate.
        """
        assert DEFAULT_RETENTION.evictable_only is True
        assert DEFAULT_RETENTION.max_age is None

    def test_a_policy_that_drops_live_scopes_drops_them(self) -> None:
        """`evictable_only=False` is what it says, not a flag nobody reads.

        Nothing in the document backend asks for it — a maintenance caller
        trimming a store it owns would — and the difference is the whole point
        of the field, so it is proven here rather than left to the relational
        statement to discover.
        """
        policy = RetentionPolicy(max_records=2, evictable_only=False)
        records: dict[str, str] = {"parked": "blocked"}
        records.update({f"done-{i:04d}": "completed" for i in range(3)})

        kept = stamp_scopes(_envelope(records), policy)["scopes"]

        assert "parked" not in kept, "nothing is protected when the policy says so"
        assert list(kept) == ["done-0001", "done-0002"]


# ----------------------------------------------------------------------
# The policy module names no layer above `_types`
# ----------------------------------------------------------------------


def _modules(text: str) -> set[str]:
    """Every module named by an import in ``text``, deferred ones included."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                found.add("." * node.level + (node.module or ""))
            elif node.module:
                found.add(node.module)
    return found


class TestThePolicyModuleImportsNothingAboveItsLayer:
    """`_types` is the stdlib-only vocabulary layer (ADR-026)."""

    def test_it_imports_stdlib_only(self) -> None:
        imported = _modules(_RETENTION.read_text(encoding="utf-8"))
        offenders = {
            module
            for module in imported
            if module.split(".")[0] not in sys.stdlib_module_names
            and module != "functualize._types.enums"
        }
        assert not offenders, offenders

    def test_the_sweep_sees_a_deferred_import(self) -> None:
        """The guard that keeps the test above from passing on a blind sweep.

        `lint-imports` keeps `if TYPE_CHECKING:` imports out of its graph, so
        the sweep has to reach inside one.
        """
        deferred = (
            "if TYPE_CHECKING:\n"
            "    from functualize._primitives.scope_format import X\n"
        )
        assert _modules(deferred) == {"functualize._primitives.scope_format"}
