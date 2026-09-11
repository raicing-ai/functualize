"""Property-based tests for `State.keys()` — the no-wildcard branch.

`keys()` takes a **glob** now, and a pattern containing no ``*`` keeps the
older prefix meaning. These properties cover that branch: every strategy below
excludes ``*`` deliberately, so a generated pattern is always a plain prefix.

The glob branch — ``"fetch.*"`` stopping at a dot, ``"fetch.**"`` crossing it,
``"*.rows"`` across namespaces, and the reason a bare prefix is the sharp
option — is covered in `tests/integration/test_capability_duality.py`
(`TestKeysMatchesByGlob`) against a real store.

**Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5**
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize.job._state import State
from tests.context.conftest import new_state_store

# --- Strategies ---

# No ``*`` anywhere: a generated key or pattern containing one would exercise
# the glob branch, where "returns exactly the keys starting with p" is not the
# contract. That branch has its own tests; see the module docstring.
_no_star = st.characters(blacklist_characters="*")

# Strategy for valid state keys: non-empty strings
state_keys = st.text(alphabet=_no_star, min_size=1, max_size=50)

# Strategy for prefix strings (can be empty)
prefix_strings = st.text(alphabet=_no_star, min_size=0, max_size=30)

# Strategy for generating a dict of state entries
state_entries = st.dictionaries(
    keys=state_keys,
    values=st.integers() | st.text() | st.booleans(),
    min_size=0,
    max_size=20,
)

# Strategy for non-string values (for type enforcement testing)
non_string_values = (
    st.integers()
    | st.floats(allow_nan=False)
    | st.booleans()
    | st.lists(st.integers(), max_size=3)
    | st.dictionaries(st.text(max_size=5), st.integers(), max_size=3)
    | st.binary(max_size=10)
    | st.none()
)


# --- Property 10: State prefix filter correctness ---
# For any set of keys stored in State and for any prefix string p,
# calling State.keys(p) with no wildcard returns exactly the keys k
# where k.startswith(p) is True.
# **Validates: Requirements 4.1, 4.2, 4.3, 4.4**


class TestStatePrefixFilterCorrectness:
    """Property 10: State prefix filter correctness."""

    @given(entries=state_entries, prefix=prefix_strings)
    def test_keys_with_prefix_returns_exactly_matching_keys(
        self, entries: dict[str, object], prefix: str
    ) -> None:
        """keys(p) with no wildcard returns exactly the keys starting with p.

        **Validates: Requirements 4.1, 4.2, 4.3, 4.4**
        """
        state = State(new_state_store())
        for k, v in entries.items():
            state.set(k, v)

        result = state.keys(prefix)
        expected = [k for k in entries if k.startswith(prefix)]

        # Same set of keys (order is unspecified)
        assert sorted(result) == sorted(expected)

    @given(entries=state_entries)
    def test_empty_prefix_returns_all_keys(self, entries: dict[str, object]) -> None:
        """keys("") returns all stored keys (equivalent to no args).

        **Validates: Requirements 4.1, 4.3**
        """
        state = State(new_state_store())
        for k, v in entries.items():
            state.set(k, v)

        result_empty = state.keys("")
        result_no_arg = state.keys()

        assert sorted(result_empty) == sorted(result_no_arg)
        assert sorted(result_empty) == sorted(entries.keys())

    @given(entries=state_entries, prefix=st.text(min_size=1, max_size=30))
    def test_prefix_filter_is_case_sensitive(
        self, entries: dict[str, object], prefix: str
    ) -> None:
        """Prefix filtering uses case-sensitive startswith comparison.

        **Validates: Requirements 4.2**
        """
        state = State(new_state_store())
        for k, v in entries.items():
            state.set(k, v)

        result = state.keys(prefix)

        # Every returned key must start with the prefix (case-sensitive)
        for key in result:
            assert key.startswith(prefix)

        # No key that starts with prefix is missing from result
        for key in entries:
            if key.startswith(prefix):
                assert key in result

    @given(
        entries=st.dictionaries(
            keys=state_keys,
            values=st.integers(),
            min_size=1,
            max_size=10,
        ),
    )
    def test_prefix_no_match_returns_empty_list(self, entries: dict[str, int]) -> None:
        """If no keys match the prefix, returns an empty list.

        **Validates: Requirements 4.4**
        """
        state = State(new_state_store())
        for k, v in entries.items():
            state.set(k, v)

        # Use a prefix that cannot match any key (longer than all keys)
        impossible_prefix = "z" * 100
        result = state.keys(impossible_prefix)

        assert result == []


# --- Property 11: State prefix type enforcement ---
# For any value that is not a str, calling State.keys(non_str)
# raises a TypeError.
# **Validates: Requirements 4.5**


class TestStatePrefixTypeEnforcement:
    """Property 11: State prefix type enforcement."""

    @given(bad_pattern=non_string_values)
    def test_non_str_prefix_raises_type_error(self, bad_pattern: object) -> None:
        """A non-string pattern raises TypeError.

        **Validates: Requirements 4.5**
        """
        state = State(new_state_store())

        with pytest.raises(TypeError, match="pattern must be a str"):
            state.keys(bad_pattern)  # type: ignore[arg-type]

    @given(bad_pattern=st.integers())
    def test_integer_prefix_raises_type_error(self, bad_pattern: int) -> None:
        """Integer prefix raises TypeError with descriptive message.

        **Validates: Requirements 4.5**
        """
        state = State(new_state_store())

        with pytest.raises(TypeError, match="got int"):
            state.keys(bad_pattern)  # type: ignore[arg-type]
