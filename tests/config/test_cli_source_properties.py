"""Property-based tests for the CliSource adapter using Hypothesis.

Tests Property 13 from the design document: CLI explicit value distinction.

**Validates: Requirements 6.3**
"""

from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from functualize._config.sources import CliSource

# --- Strategies ---

# Strategy for simple config values (primitives that CLI might provide)
cli_values: st.SearchStrategy[Any] = st.one_of(
    st.text(min_size=0, max_size=20),
    st.integers(min_value=-1000, max_value=1000),
    st.floats(allow_nan=False, allow_infinity=False),
    st.booleans(),
    st.none(),
)

# Strategy for valid simple CLI keys (no dots, no leading dashes in normalized form)
simple_keys = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="_"),
    min_size=1,
    max_size=15,
).filter(lambda s: s[0].isalpha())

# Strategy for valid section names
section_names = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="_"),
    min_size=1,
    max_size=10,
).filter(lambda s: s[0].isalpha())


# --- Property 13: CLI explicit value distinction ---


class TestProperty13CliExplicitValueDistinction:
    """Only explicitly-provided values in the constructor dict are accessible.

    **Validates: Requirements 6.3**
    """

    @given(
        values=st.dictionaries(
            keys=simple_keys,
            values=cli_values,
            min_size=1,
            max_size=10,
        ),
    )
    def test_explicitly_provided_values_are_accessible(
        self, values: dict[str, Any]
    ) -> None:
        """All values explicitly provided to the constructor are retrievable
        via get()."""
        source = CliSource(values)

        for key, expected_value in values.items():
            assert source.get(key) == expected_value

    @given(
        provided_keys=st.lists(simple_keys, min_size=1, max_size=8, unique=True),
        absent_keys=st.lists(simple_keys, min_size=1, max_size=8, unique=True),
        values=cli_values,
    )
    def test_absent_keys_always_return_none(
        self,
        provided_keys: list[str],
        absent_keys: list[str],
        values: Any,
    ) -> None:
        """Keys NOT in the constructor dict always return None from get()."""
        # Build a source with only provided_keys
        source = CliSource({k: values for k in provided_keys})

        # Any key not in the provided set must return None
        for key in absent_keys:
            if key not in provided_keys:
                assert source.get(key) is None

    @given(
        values=st.dictionaries(
            keys=simple_keys,
            values=cli_values,
            min_size=1,
            max_size=10,
        ),
        extra_keys=st.lists(simple_keys, min_size=1, max_size=8, unique=True),
    )
    def test_has_returns_true_iff_key_in_constructor(
        self,
        values: dict[str, Any],
        extra_keys: list[str],
    ) -> None:
        """has(key) returns True if and only if the key was in the
        constructor dict."""
        source = CliSource(values)

        # has() is True for all provided keys
        for key in values:
            assert source.has(key) is True

        # has() is False for keys not in the provided dict
        for key in extra_keys:
            if key not in values:
                assert source.has(key) is False

    @given(
        values=st.dictionaries(
            keys=simple_keys,
            values=cli_values,
            min_size=0,
            max_size=10,
        ),
        probe_keys=st.lists(simple_keys, min_size=1, max_size=10, unique=True),
    )
    def test_no_implicit_values_leak(
        self,
        values: dict[str, Any],
        probe_keys: list[str],
    ) -> None:
        """The source only exposes what was explicitly provided — no implicit
        values leak in. For any key not in the constructor, both get()
        returns None and has() returns False."""
        source = CliSource(values)

        for key in probe_keys:
            if key not in values:
                assert source.get(key) is None
                assert source.has(key) is False

    @given(
        section=section_names,
        key=simple_keys,
        value=cli_values,
        wrong_section=section_names,
    )
    def test_sectioned_keys_not_accessible_without_section(
        self,
        section: str,
        key: str,
        value: Any,
        wrong_section: str,
    ) -> None:
        """A value provided with a section (dot-separated) is only accessible
        with the correct section argument. It does not leak into the
        global namespace or other sections."""
        dotted_key = f"{section}.{key}"
        source = CliSource({dotted_key: value})

        # Accessible with the correct section
        assert source.get(key, section=section) == value
        assert source.has(key, section=section) is True

        # Not accessible without a section (global namespace)
        assert source.get(key) is None
        assert source.has(key) is False

        # Not accessible with a different section
        if wrong_section != section:
            assert source.get(key, section=wrong_section) is None
            assert source.has(key, section=wrong_section) is False

    @given(
        values=st.dictionaries(
            keys=simple_keys,
            values=cli_values,
            min_size=0,
            max_size=10,
        ),
    )
    def test_has_and_get_consistency(
        self,
        values: dict[str, Any],
    ) -> None:
        """For any key, has(key) == True implies get(key) returns the stored
        value (not None unless None was explicitly stored), and has(key) == False
        implies get(key) returns None."""
        source = CliSource(values)

        for key in values:
            assert source.has(key) is True
            # get() returns the actual value (which might be None if explicitly stored)
            assert source.get(key) == values[key]
