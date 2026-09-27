"""`IllegalTransition` says which pair was refused — T2.

`schema.md` §1: a pair the machine's table does not name "is refused with
`IllegalTransition(machine, current, target)`". The three arguments are the
contract, so this file checks that all three survive: in the message a person
reads, on the attributes a caller reads, and across a pickle — an error raised
inside a worker has to be reconstructible where it is reported, and the default
`BaseException` round trip cannot do that for a constructor with three facts.

An absent record is the case worth stating twice. `None` is a *state* in these
tables (a row that does not exist yet), not the absence of an answer, so it has
to arrive as `None` and read as words, in both directions.
"""

from __future__ import annotations

import pickle

from functualize._types.errors import IllegalTransition


class TestItNamesTheRefusedMove:
    def test_the_message_names_the_machine_the_current_and_the_target(self) -> None:
        """The shape `contracts.md` records, character for character."""
        error = IllegalTransition("scope", "cancelled", "running")
        assert str(error) == (
            "scope: 'cancelled' -> 'running' is not a legal transition"
        )

    def test_an_absent_record_reads_as_words_not_as_none(self) -> None:
        """`None` in a message reads as "the value is missing", which is the
        opposite of what it means here: the record has not been written."""
        message = str(IllegalTransition("input_request", None, "accepted"))
        assert "an absent record" in message
        assert "input_request" in message
        assert "'accepted'" in message

    def test_the_attributes_are_the_three_facts(self) -> None:
        error = IllegalTransition("attempt", "succeeded", "running")
        assert (error.machine, error.current, error.target) == (
            "attempt",
            "succeeded",
            "running",
        )

    def test_an_absent_current_stays_none(self) -> None:
        """A ``"None"`` spelling would pass a truthiness check the wrong way."""
        error = IllegalTransition("scope", None, "running")
        assert error.current is None
        assert error.machine == "scope"
        assert error.target == "running"


class TestItSurvivesARoundTrip:
    def test_it_pickles(self) -> None:
        error = IllegalTransition("scope", "completed", "blocked")
        restored = pickle.loads(pickle.dumps(error))
        assert type(restored) is IllegalTransition
        assert (restored.machine, restored.current, restored.target) == (
            "scope",
            "completed",
            "blocked",
        )
        assert str(restored) == str(error)

    def test_it_pickles_with_an_absent_current(self) -> None:
        restored = pickle.loads(pickle.dumps(IllegalTransition("run", None, "blocked")))
        assert restored.current is None
        assert restored.target == "blocked"

    def test_the_round_trip_is_not_the_default_one(self) -> None:
        """The guard that keeps the two tests above from proving nothing.

        `BaseException` reconstructs by calling the class with `self.args` —
        here the one rendered message, against a three-argument constructor. So
        the tests above only mean something while `__reduce__` states the
        arguments itself.
        """
        assert IllegalTransition("scope", "cancelled", "running").__reduce__() == (
            IllegalTransition,
            ("scope", "cancelled", "running"),
        )
