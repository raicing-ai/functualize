"""`require_transition` accepts exactly the four tables — no more, no less.

`runtime-schema-migrations`/T4 (AC1). The tests sweep the **whole product**
``(states ∪ {None}) × states`` per machine rather than a list of moves that are
supposed to work, because the two defects are opposite and only one of them is
visible in a hand-written list:

- a pair in the table that the check refuses — the check and the data have
  drifted, and the writer guarded by it (`ScopeStore.set_scope_status`) refuses a
  move the engine really makes;
- a pair the check accepts that is *not* in the table — the same drift from the
  other side, and the one that would let an illegal write through while every
  consumer of the table says it cannot happen.

The tables themselves, their absorbing/evictable sets and the Rows they come
from are `tests/types/test_lifecycle_tables.py`; this file is about the refusal.

`require_transition` has two production callers — the scope machine's writer and
the run machine's — and those call paths are held by their own suites
(`tests/primitives/test_scope_transitions.py`,
`tests/primitives/test_run_transitions.py`). What this file establishes is
the function itself, driven directly against the four tables: the sweep below is
about the refusal's verdict, not about who calls it.
"""

from __future__ import annotations

import itertools
from enum import StrEnum

import pytest

from functualize._primitives.transitions import require_transition
from functualize._types.enums import RunStatus
from functualize._types.errors import IllegalTransition
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
_IDS = [machine.name for machine in MACHINES]


def _product(machine: Machine) -> set[tuple[str | None, str]]:
    """Every pair the check can be asked about, absent-record case included."""
    return set(itertools.product({None} | set(machine.states), machine.states))


class TestTheFullProduct:
    @pytest.mark.parametrize("machine", MACHINES, ids=_IDS)
    def test_it_accepts_the_table_and_refuses_everything_else(
        self, machine: Machine
    ) -> None:
        accepted: set[tuple[str | None, str]] = set()
        refused: set[tuple[str | None, str]] = set()

        for current, target in sorted(
            _product(machine), key=lambda pair: (pair[0] or "", pair[1])
        ):
            try:
                returned = require_transition(machine, current, target)
            except IllegalTransition as refusal:
                assert (
                    refusal.machine,
                    refusal.current,
                    refusal.target,
                ) == (machine.name, current, target)
                refused.add((current, target))
            else:
                assert returned == target
                accepted.add((current, target))

        assert accepted == set(machine.transitions)
        assert accepted | refused == _product(machine)
        assert refused, f"{machine.name} refuses nothing, so the check is dead code"

    def test_the_sweep_is_not_vacuous(self) -> None:
        """Each machine has a state that is illegal from another, and says so.

        Not a property of the check — a guard on the test above: a table that
        accepted the whole product would make every assertion in it true and
        prove nothing.
        """
        for machine in MACHINES:
            assert set(machine.transitions) < _product(machine)


class TestWhatNoStateNames:
    @pytest.mark.parametrize("machine", MACHINES, ids=_IDS)
    def test_an_unknown_target_is_refused(self, machine: Machine) -> None:
        """`RUN` is why this is parametrized rather than written once.

        Every run state that has not finished may move to any *state* — the
        widest row in the four tables — and the temptation is to implement that
        as "any target at all". It is not the same claim: `pending` is not a
        run state and no run may be moved to it. The current state is a live one
        on purpose, so the refusal is about the target and nothing else.
        """
        live = next(iter(machine.states - machine.absorbing))
        with pytest.raises(IllegalTransition) as raised:
            require_transition(machine, live, "pending")
        assert (raised.value.current, raised.value.target) == (live, "pending")

    def test_a_stored_status_no_longer_in_the_vocabulary_refuses_its_next_write(
        self,
    ) -> None:
        """`contracts.md`: an old row is not rewritten, it refuses on the next write."""
        with pytest.raises(IllegalTransition) as raised:
            require_transition(SCOPE, "pending", ScopeStatus.RUNNING)
        assert raised.value.current == "pending"
        assert raised.value.machine == "scope"


class TestTheReturnValue:
    def test_it_returns_the_target_it_checked(self) -> None:
        """So a writer assigns the answer rather than the value it hoped for."""
        assert require_transition(SCOPE, "blocked", ScopeStatus.RUNNING) is (
            ScopeStatus.RUNNING
        )

    def test_a_str_enum_and_its_text_are_the_same_key(self) -> None:
        """The engine passes strings, the store may pass members, and both work.

        `StrEnum` members hash as the text they store, so a table written from
        `ScopeStatus` and a caller holding `WalkState.RUNNING == "running"`
        agree without a conversion step — and a mixed call is one key too.
        """
        assert require_transition(SCOPE, ScopeStatus.BLOCKED, ScopeStatus.RUNNING)
        assert require_transition(SCOPE, "blocked", "running") == "running"
        assert require_transition(SCOPE, ScopeStatus.BLOCKED, "running") == "running"

    @pytest.mark.parametrize("machine", MACHINES, ids=_IDS)
    def test_every_machine_returns_a_target_it_accepts(self, machine: Machine) -> None:
        """Driven from the table itself, so a new row is covered the day it is added."""
        for current, target in machine.transitions:
            assert require_transition(machine, current, target) == target


class TestEachVocabularyReachesItsOwnTable:
    """The three text vocabularies, checked against the tables rather than restated.

    Each enum is driven through the check from a live state, and the answer has
    to match what the table says about that enum's *text* — in both directions.
    A vocabulary member the table has no row for must be refused, not accepted
    because "its machine allows everything".
    """

    @pytest.mark.parametrize(
        ("machine", "live", "vocabulary"),
        [
            (SCOPE, "running", ScopeStatus),
            (ATTEMPT, "running", AttemptStatus),
            (INPUT_REQUEST, "open", InputRequestStatus),
        ],
        ids=["scope", "attempt", "input_request"],
    )
    def test_a_vocabulary_member_is_accepted_exactly_where_its_text_is(
        self,
        machine: Machine,
        live: str,
        vocabulary: type[StrEnum],
    ) -> None:
        targets = {target for current, target in machine.transitions if current == live}
        for status in vocabulary:
            if status.value in targets:
                assert require_transition(machine, live, status) == status
            else:
                with pytest.raises(IllegalTransition):
                    require_transition(machine, live, status)

    def test_the_run_machine_takes_lower_cased_run_status(self) -> None:
        """The run machine adopts `RunStatus`, lower-cased (`schema.md` §1.2).

        `RunStatus` is a plain `Enum` whose values are capitalised, and the store
        writes `status.value.lower()`, so the conversion stays at the caller and
        the table holds the lower-case text. Pinned because the other direction
        fails *silently* elsewhere: a caller that forgets `.lower()` gets a
        refusal here rather than a run that looks like it never started.
        """
        for status in RunStatus:
            text = status.value.lower()
            assert require_transition(RUN, "running", text) == text
            with pytest.raises(IllegalTransition):
                require_transition(RUN, "running", status.value)

    def test_a_machines_vocabulary_is_not_another_machines_legal_move(self) -> None:
        """The failure mode a shared "status" string invites.

        `attempt` has no `blocked` state, so the scope's pause point is not a
        move an attempt can make — one spelling of `running` across three
        vocabularies is exactly why the tables are per-machine.
        """
        with pytest.raises(IllegalTransition):
            require_transition(ATTEMPT, "running", "blocked")
