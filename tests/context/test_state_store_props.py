"""Property-based tests for StateStore module.

Property 11: State_Store Keys and Clear Consistency
**Validates: Requirements 6.5, 6.6**

Property 12: State_Store Typed Get
**Validates: Requirements 6.7**
"""

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from functualize.job._state_store import StateStore

# --- Strategies ---

# Strategy for valid state keys (non-empty strings)
state_keys = st.text(
    alphabet=st.characters(categories=("L", "N", "Pd", "Pc")),
    min_size=1,
    max_size=50,
)

# Strategy for JSON-serializable values
json_values: st.SearchStrategy[object] = st.recursive(
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(max_size=50),
    lambda children: (
        st.lists(children, max_size=5)
        | st.dictionaries(st.text(max_size=10), children, max_size=5)
    ),
    max_leaves=10,
)


# Feature: enriched-runcontext, Property 11: State_Store Keys and Clear Consistency
# After N set operations with unique keys, keys() returns exactly those N key names.
# After clear(), keys() returns an empty list and all previous gets return None.
# keys() always returns a list (never raises) regardless of store state.
# The keys list is independent of insertion order (just contains the key names).
# **Validates: Requirements 6.5, 6.6**
class TestStateStoreKeysAndClearConsistency:
    """Property 11: State_Store Keys and Clear Consistency."""

    @given(
        items=st.dictionaries(
            keys=state_keys,
            values=json_values,
            min_size=1,
            max_size=20,
        )
    )
    def test_keys_returns_exactly_n_keys_after_n_unique_sets(
        self, items: dict[str, object]
    ) -> None:
        """After N set operations with unique keys, keys() returns exactly those N key names.

        **Validates: Requirements 6.5**
        """
        store = StateStore()
        for key, value in items.items():
            store.set(key, value)

        result_keys = store.keys()
        assert len(result_keys) == len(items)
        assert set(result_keys) == set(items.keys())

    @given(
        items=st.dictionaries(
            keys=state_keys,
            values=json_values,
            min_size=1,
            max_size=20,
        )
    )
    def test_clear_makes_keys_empty_and_gets_return_none(
        self, items: dict[str, object]
    ) -> None:
        """After clear(), keys() returns an empty list and all previous gets return None.

        **Validates: Requirements 6.6**
        """
        store = StateStore()
        for key, value in items.items():
            store.set(key, value)

        # Verify data is there first
        assert len(store.keys()) == len(items)

        # Clear and verify
        store.clear()
        assert store.keys() == []

        # All previous gets should return None
        for key in items:
            assert store.get(key, object) is None

    @given(
        items=st.dictionaries(
            keys=state_keys,
            values=json_values,
            min_size=0,
            max_size=15,
        ),
        do_clear=st.booleans(),
    )
    def test_keys_always_returns_list(
        self, items: dict[str, object], do_clear: bool
    ) -> None:
        """keys() always returns a list (never raises) regardless of store state.

        **Validates: Requirements 6.5**
        """
        store = StateStore()
        for key, value in items.items():
            store.set(key, value)

        if do_clear:
            store.clear()

        result = store.keys()
        assert isinstance(result, list)

    @given(
        items=st.lists(
            st.tuples(state_keys, json_values),
            min_size=1,
            max_size=20,
            unique_by=lambda x: x[0],
        )
    )
    def test_keys_independent_of_insertion_order(
        self, items: list[tuple[str, object]]
    ) -> None:
        """The keys list is independent of insertion order (just contains the key names).

        **Validates: Requirements 6.5**
        """
        store1 = StateStore()
        store2 = StateStore()

        # Insert in original order
        for key, value in items:
            store1.set(key, value)

        # Insert in reversed order
        for key, value in reversed(items):
            store2.set(key, value)

        # Both should have the same set of keys
        assert set(store1.keys()) == set(store2.keys())
        # The set of key names should match regardless of order
        expected_keys = {k for k, _ in items}
        assert set(store1.keys()) == expected_keys
        assert set(store2.keys()) == expected_keys


# --- Additional Strategies for Property 12 ---

# Strategy for JSON-serializable strings (non-empty to avoid bool subclass issues)
json_strings = st.text(min_size=1, max_size=100)
json_ints = st.integers(min_value=-(2**53), max_value=2**53).filter(
    lambda v: not isinstance(v, bool)
)
json_floats = st.floats(allow_nan=False, allow_infinity=False)
json_bools = st.booleans()
json_lists = st.lists(st.integers(min_value=-100, max_value=100), max_size=10)
json_dicts = st.dictionaries(
    keys=st.text(min_size=1, max_size=10),
    values=st.integers(min_value=-100, max_value=100),
    max_size=5,
)

# Types available for mismatch testing
all_checkable_types: list[type[object]] = [str, int, float, list, dict, bool]


# Feature: enriched-runcontext, Property 12: State_Store Typed Get
# When get(key, type_) is called with the correct type matching the stored value,
# it returns the value. When called with a mismatching type, it raises TypeError
# with the key name, expected type, and actual type. When called for a non-existent
# key, it returns None regardless of the type parameter.
# **Validates: Requirements 6.7**
class TestStateStoreTypedGet:
    """Property 12: State_Store Typed Get."""

    @given(key=state_keys, value=json_strings)
    def test_get_correct_type_str(self, key: str, value: str) -> None:
        """get(key, str) returns the stored string value.

        **Validates: Requirements 6.7**
        """
        store = StateStore()
        store.set(key, value)
        assert store.get(key, str) == value

    @given(key=state_keys, value=json_ints)
    def test_get_correct_type_int(self, key: str, value: int) -> None:
        """get(key, int) returns the stored int value.

        **Validates: Requirements 6.7**
        """
        store = StateStore()
        store.set(key, value)
        assert store.get(key, int) == value

    @given(key=state_keys, value=json_floats)
    def test_get_correct_type_float(self, key: str, value: float) -> None:
        """get(key, float) returns the stored float value.

        **Validates: Requirements 6.7**
        """
        store = StateStore()
        store.set(key, value)
        assert store.get(key, float) == value

    @given(key=state_keys, value=json_bools)
    def test_get_correct_type_bool(self, key: str, value: bool) -> None:
        """get(key, bool) returns the stored bool value.

        **Validates: Requirements 6.7**
        """
        store = StateStore()
        store.set(key, value)
        assert store.get(key, bool) == value

    @given(key=state_keys, value=json_lists)
    def test_get_correct_type_list(self, key: str, value: list[int]) -> None:
        """get(key, list) returns the stored list value.

        **Validates: Requirements 6.7**
        """
        store = StateStore()
        store.set(key, value)
        assert store.get(key, list) == value

    @given(key=state_keys, value=json_dicts)
    def test_get_correct_type_dict(self, key: str, value: dict[str, int]) -> None:
        """get(key, dict) returns the stored dict value.

        **Validates: Requirements 6.7**
        """
        store = StateStore()
        store.set(key, value)
        assert store.get(key, dict) == value

    @given(
        key=state_keys,
        value=json_strings,
        wrong_type=st.sampled_from([int, list, dict]),
    )
    def test_type_mismatch_raises_with_details_str(
        self, key: str, value: str, wrong_type: type[object]
    ) -> None:
        """get(key, wrong_type) on a stored str raises TypeError mentioning key,
        expected type, and actual type.

        **Validates: Requirements 6.7**
        """
        store = StateStore()
        store.set(key, value)

        with pytest.raises(TypeError, match=key) as exc_info:
            store.get(key, wrong_type)

        error_msg = str(exc_info.value)
        assert wrong_type.__name__ in error_msg
        assert "str" in error_msg

    @given(
        key=state_keys,
        value=json_ints,
        wrong_type=st.sampled_from([str, list, dict]),
    )
    def test_type_mismatch_raises_with_details_int(
        self, key: str, value: int, wrong_type: type[object]
    ) -> None:
        """get(key, wrong_type) on a stored int raises TypeError mentioning key,
        expected type, and actual type.

        **Validates: Requirements 6.7**
        """
        store = StateStore()
        store.set(key, value)

        with pytest.raises(TypeError, match=key) as exc_info:
            store.get(key, wrong_type)

        error_msg = str(exc_info.value)
        assert wrong_type.__name__ in error_msg
        assert "int" in error_msg

    @given(
        key=state_keys,
        value=json_lists,
        wrong_type=st.sampled_from([str, int, float, dict]),
    )
    def test_type_mismatch_raises_with_details_list(
        self, key: str, value: list[int], wrong_type: type[object]
    ) -> None:
        """get(key, wrong_type) on a stored list raises TypeError mentioning key,
        expected type, and actual type.

        **Validates: Requirements 6.7**
        """
        store = StateStore()
        store.set(key, value)

        with pytest.raises(TypeError, match=key) as exc_info:
            store.get(key, wrong_type)

        error_msg = str(exc_info.value)
        assert wrong_type.__name__ in error_msg
        assert "list" in error_msg

    @given(
        key=state_keys,
        type_param=st.sampled_from(all_checkable_types),
    )
    def test_nonexistent_key_returns_none(
        self, key: str, type_param: type[object]
    ) -> None:
        """get(key, type_) returns None for a non-existent key regardless of type.

        **Validates: Requirements 6.7**
        """
        store = StateStore()
        result = store.get(key, type_param)
        assert result is None

    @given(
        key=state_keys,
        other_key=state_keys,
        type_param=st.sampled_from(all_checkable_types),
    )
    def test_nonexistent_key_returns_none_when_store_has_other_keys(
        self, key: str, other_key: str, type_param: type[object]
    ) -> None:
        """get(key, type_) returns None for a missing key even when other keys exist.

        **Validates: Requirements 6.7**
        """
        assume(key != other_key)

        store = StateStore()
        store.set(other_key, "placeholder")

        result = store.get(key, type_param)
        assert result is None
