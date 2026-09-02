"""The rule that decides whether a caller's keywords are acceptable.

`unexpected_keyword_error` is the launch-time half of argument binding: it
answers "may the caller supply these keywords?" without answering "is every
required argument present?". The second question cannot be asked before
dependency injection has run, because a job function's parameters are mostly
capabilities the engine fills.

The four cases below are the whole contract. The fifth asserts the message
matches what a real call produces — by *comparing against a real call*, never
against a frozen string, so the two cannot drift if CPython rewords it.
"""

from __future__ import annotations

import pytest

from functualize._engine.validation import unexpected_keyword_error


def accepts_version(log: object, version: str = "0.0.0") -> None:
    """A signature with one DI-shaped parameter and one caller-suppliable one."""


def accepts_anything(log: object, **kwargs: object) -> None:
    """A signature that swallows arbitrary keywords."""


def di_only(log: object) -> None:
    """A signature whose only parameter the engine would fill."""


class TestTheRule:
    """R1's table: the four behaviors the spec names, in order."""

    def test_an_unaccepted_keyword_is_refused(self) -> None:
        """B1 — the defect this feature exists to close."""
        error = unexpected_keyword_error(accepts_version, {"zzz_nonsense": 1})

        assert isinstance(error, TypeError)
        assert "zzz_nonsense" in str(error)

    def test_var_keyword_accepts_anything(self) -> None:
        """B5 — Python's own rule is the rule; this only changes when it runs."""
        assert unexpected_keyword_error(accepts_anything, {"zzz_nonsense": 1}) is None

    def test_a_missing_argument_is_not_an_error(self) -> None:
        """B3 — completeness is decided after DI, not at launch.

        `di_only` cannot be *called* with no arguments, but it can be *launched*
        with none: the engine fills `log` later. A check that failed here would
        reject every valid workflow launch.
        """
        assert unexpected_keyword_error(di_only, {}) is None

    def test_an_accepted_keyword_passes(self) -> None:
        """B6 — a valid call is untouched."""
        assert unexpected_keyword_error(accepts_version, {"version": "1.4.0"}) is None

    def test_a_di_parameter_may_be_supplied_explicitly(self) -> None:
        """Declared is declared.

        The engine injects only names the caller did not provide, so supplying
        a capability parameter by hand has always been legal. The launch check
        must not quietly outlaw it.
        """
        assert unexpected_keyword_error(di_only, {"log": object()}) is None


class TestTheMessage:
    """The wording is a parity claim, so it is tested as one."""

    @pytest.mark.parametrize("bad_kwarg", ["zzz_nonsense", "verison", "x"])
    def test_it_matches_what_a_real_call_says(self, bad_kwarg: str) -> None:
        """`bind_partial` drops the `fn()` prefix; the helper puts it back.

        Compared against a real call rather than a frozen literal: if CPython
        rewords this message, both sides move together and the test still means
        what it says.
        """
        with pytest.raises(TypeError) as caught:
            di_only(**{bad_kwarg: 1})  # type: ignore[arg-type]
        from_real_call = str(caught.value)

        error = unexpected_keyword_error(di_only, {bad_kwarg: 1})

        assert error is not None
        assert str(error) == from_real_call
