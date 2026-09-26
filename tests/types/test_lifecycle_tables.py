"""The runtime state machines are the tables the spec wrote down — T1.

`schema.md` §1 is the source of truth; this file is the cross-check that the
constant in `_types/lifecycle.py` is the same table. Four claims per machine,
and one per machine that only its own table can make:

- every transition goes between named states, with `None` standing for the
  absent record and nothing else standing for anything;
- every named subset is a subset of the states — an absorbing or evictable
  state that is not a state is a typo that would silently never match;
- nothing leaves an absorbing state, which is the whole content of "absorbing";
- each machine has exactly one creation edge, so "how does this machine start"
  has one answer a reader can point at.

The status vocabularies are checked for the property the store depends on: a
member *is* the stored string, lower-cased, so a comparison against a row's text
decides on the same five spellings the machine declares.

`SCOPE` is pinned **row for row** and the run machine **against
`RunStatus`**, because those two have an authority outside this file: a
hand-written table a reader can diff against §1.1, and an enum the schema
adopts rather than redefines. For either, "the constant is self-consistent" is
not the property — "the constant matches the document" is.

The last test sweeps the module's imports, because `_types` importing anything
above it is a contract `lint-imports` reads with `exclude_type_checking_imports`
— a deferred import would leave all seven contracts green (the same blind spot
`tests/types/test_persistence_port_imports.py` exists for).
"""

from __future__ import annotations

import ast
import sys
from enum import StrEnum
from pathlib import Path

import pytest

from functualize._types.enums import RunStatus
from functualize._types.lifecycle import (
    ATTEMPT,
    INPUT_REQUEST,
    RUN,
    SCOPE,
    AttemptStatus,
    InputRequestStatus,
    Machine,
    ScopeStatus,
)

MACHINES = (SCOPE, RUN, ATTEMPT, INPUT_REQUEST)

_SRC = Path(__file__).resolve().parents[2] / "src"

MODULE = _SRC / "functualize" / "_types" / "lifecycle.py"

#: `schema.md` §1.1, transcribed. The one deliberate copy of a constant in this
#: file: it is the *document* that is being held to, so a change to the table
#: has to be made in the two places a reviewer can see side by side.
SCOPE_ROWS = frozenset(
    {
        (None, "running"),
        ("running", "running"),
        ("running", "blocked"),
        ("running", "completed"),
        ("running", "failed"),
        ("running", "cancelled"),
        ("blocked", "running"),
        ("blocked", "cancelled"),
        ("failed", "running"),
        ("completed", "running"),
        ("completed", "completed"),
    }
)


# ----------------------------------------------------------------------
# The stored vocabularies
# ----------------------------------------------------------------------


class TestTheStoredVocabularies:
    @pytest.mark.parametrize(
        "status",
        [*ScopeStatus, *AttemptStatus, *InputRequestStatus],
        ids=lambda s: f"{type(s).__name__}.{s.name}",
    )
    def test_every_member_is_the_lowercase_of_its_name(self, status: StrEnum) -> None:
        """The stored string, not a decorated one.

        `_types/enums.py`'s `RunStatus` stores `"Success"`, so the decorated
        spelling is the one to hand; a scope row's `status` column holds
        `"running"`, and the two are compared as text.
        """
        assert status.value == status.name.lower()

    def test_a_member_is_the_stored_string(self) -> None:
        """`StrEnum`, which is why the choke point can compare without a lookup.

        A `str`-mixin enum's members hash and compare as their value, so
        `row["status"] in ScopeStatus` decides on the text on disk.
        """
        assert isinstance(ScopeStatus.RUNNING, str)
        assert ScopeStatus.RUNNING in {"running"}
        assert frozenset({ScopeStatus.BLOCKED}) == {"blocked"}


# ----------------------------------------------------------------------
# What every machine owes
# ----------------------------------------------------------------------


class TestEveryMachine:
    @pytest.mark.parametrize("machine", MACHINES, ids=lambda m: m.name)
    def test_every_transition_goes_between_named_states(self, machine: Machine) -> None:
        named = machine.states | {None}
        strays = {
            (current, target)
            for current, target in machine.transitions
            if current not in named or target not in machine.states
        }
        assert not strays, (
            f"{machine.name} names states it does not declare: {sorted(strays, key=str)}"
        )

    @pytest.mark.parametrize("machine", MACHINES, ids=lambda m: m.name)
    def test_every_named_subset_is_a_subset(self, machine: Machine) -> None:
        for label, subset in (
            ("absorbing", machine.absorbing),
            ("evictable", machine.evictable),
        ):
            assert subset <= machine.states, (
                f"{machine.name}'s {label} set names {sorted(subset - machine.states)} "
                "as states"
            )

    @pytest.mark.parametrize("machine", MACHINES, ids=lambda m: m.name)
    def test_nothing_leaves_an_absorbing_state(self, machine: Machine) -> None:
        leaving = {
            (current, target)
            for current, target in machine.transitions
            if current in machine.absorbing
        }
        assert not leaving, (
            f"{machine.name} declares {sorted(machine.absorbing)} absorbing and "
            f"leaves it: {sorted(leaving, key=str)}"
        )

    @pytest.mark.parametrize("machine", MACHINES, ids=lambda m: m.name)
    def test_it_has_exactly_one_way_to_be_created(self, machine: Machine) -> None:
        """One start state per machine, and it is a state it declares.

        "A record that does not exist yet may be written as *anything*" is the
        shape this rules out: an absent record has one first value, and a table
        saying otherwise could not be checked at all.
        """
        creation = [
            target for current, target in machine.transitions if current is None
        ]
        assert len(creation) == 1, f"{machine.name} starts {creation}"
        assert creation[0] in machine.states

    def test_only_scope_names_an_evictable_set(self) -> None:
        """`schema.md` §1: "Each machine is ... and an **absorbing** set (Scope
        also names an **evictable** set)".

        A policy on the other three would be a policy with no reader; this is
        here so that adding one is a deliberate act and not a default that
        nobody noticed.
        """
        assert [m.name for m in MACHINES if m.evictable] == ["scope"]


# ----------------------------------------------------------------------
# Scope — row for row against `schema.md` §1.1
# ----------------------------------------------------------------------


class TestTheScopeTable:
    def test_the_rows_are_the_documented_rows(self) -> None:
        assert SCOPE.transitions == SCOPE_ROWS

    def test_the_states_are_the_five_stored_strings(self) -> None:
        assert SCOPE.states == {
            "running",
            "blocked",
            "completed",
            "failed",
            "cancelled",
        }

    def test_only_cancelled_is_absorbing(self) -> None:
        """D1 = A. A finished scope may be re-entered; only cancelling is final."""
        assert SCOPE.absorbing == {"cancelled"}

    def test_the_evictable_set_is_the_documented_one(self) -> None:
        assert SCOPE.evictable == {"completed", "failed", "cancelled"}

    def test_the_evictable_set_is_wider_than_the_absorbing_one(self) -> None:
        """The separation D1 = A created, stated as the difference.

        `cancelled` is both; `completed` and `failed` are evictable and are no
        longer absorbing. Reading the two sets as one would either keep a
        finished scope for ever or refuse the retry that D1 = A allows.
        """
        assert SCOPE.absorbing <= SCOPE.evictable
        assert SCOPE.evictable - SCOPE.absorbing == {"completed", "failed"}

    def test_the_retry_edges_are_both_present(self) -> None:
        """The two `# TRANSITIONAL(workflow-persistence-atomic)` rows.

        Their *presence* is the property: D1 = A makes a failed scope and a
        completed one re-enterable, and a table missing either edge would
        refuse the resume the scope store accepts — the check would be a
        behaviour change rather than a description of one.
        """
        for edge in (("failed", "running"), ("completed", "running")):
            assert edge in SCOPE.transitions

    def test_a_completed_scope_may_be_completed_again(self) -> None:
        """The end-of-walk stamp fires twice; the pair has to be legal."""
        assert ("completed", "completed") in SCOPE.transitions

    def test_the_states_that_stopped_being_reachable_are_refused(self) -> None:
        """The four edges D2 = 1 removed.

        Each was reachable only because a resumed walk did not stamp `running`;
        with every entry stamping it (T3), a scope is `running` before it
        blocks, fails or finishes, so none of these can be the pair being
        checked.
        """
        for edge in (
            ("blocked", "completed"),
            ("blocked", "failed"),
            ("failed", "completed"),
            ("failed", "blocked"),
        ):
            assert edge not in SCOPE.transitions


# ----------------------------------------------------------------------
# Run — built from the enum the schema adopts
# ----------------------------------------------------------------------


class TestTheRunTable:
    def test_the_absorbing_set_is_the_enums_terminal_set(self) -> None:
        assert RUN.absorbing == {s.value.lower() for s in RunStatus if s.terminal}

    def test_the_states_are_every_run_status_lowercased(self) -> None:
        """The spelling the run log stores (`RunStatus.value.lower()`)."""
        assert RUN.states == {s.value.lower() for s in RunStatus}

    def test_the_live_states_are_the_four_the_table_names(self) -> None:
        assert RUN.states - RUN.absorbing == {
            "running",
            "blocked",
            "skipped",
            "unknown",
        }

    def test_a_run_may_end_as_any_status(self) -> None:
        for current in RUN.states - RUN.absorbing:
            assert {t for c, t in RUN.transitions if c == current} == RUN.states


# ----------------------------------------------------------------------
# The module names no layer above `_types`
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


class TestItImportsNothingAboveItsLayer:
    def test_it_imports_stdlib_and_the_run_enum_only(self) -> None:
        """The module's own claim, checked rather than asserted.

        `_types/lifecycle.py` may hold the run table only because it may name
        `RunStatus`; anything else — a store, an engine, even
        `_primitives/transitions.py` — would put a layer above `_types` in
        reach of everything that imports the vocabulary.
        """
        imported = _modules(MODULE.read_text(encoding="utf-8"))
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
        the sweep has to reach inside one — the same blind spot the persistence
        port guard exists for.
        """
        deferred = (
            "if TYPE_CHECKING:\n    from functualize._primitives.scope_store import X\n"
        )
        assert _modules(deferred) == {"functualize._primitives.scope_store"}
