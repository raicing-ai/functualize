"""Property-based tests for ScopeStore module.

Property 11: State_Store Keys and Clear Consistency
**Validates: Requirements 6.5, 6.6**

Property 12: State_Store Typed Get
**Validates: Requirements 6.7**
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.context.conftest import new_state_store

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
        store = new_state_store()
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
        store = new_state_store()
        for key, value in items.items():
            store.set(key, value)

        # Verify data is there first
        assert len(store.keys()) == len(items)

        # Clear and verify
        store.clear()
        assert store.keys() == []

        # All previous gets should return None
        for key in items:
            assert store.get(key) is None

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
        store = new_state_store()
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
        store1 = new_state_store()
        store2 = new_state_store()

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
class TestStateStoreRoundTrip:
    """Every JSON type a job can store comes back unchanged.

    Was `TestStateStoreTypedGet`, which exercised a ``get(key, type)`` overload
    that checked the stored value's type and returned None when the key was
    missing. That overload had **no caller** in `src/`, `examples/` or `docs/`,
    and it was removed with the in-memory store rather than reimplemented on
    the durable one (*Pre-Release Stance*: delete rather than shim).

    The property worth keeping is the round trip: the store validates
    JSON-serializability at write time, so whatever it accepted it must return
    intact. The second argument to `get` is a plain default now, which is what
    a reader expects `get` to mean.
    """

    @given(key=state_keys, value=json_strings)
    def test_a_string_round_trips(self, key: str, value: str) -> None:
        store = new_state_store()
        store.set(key, value)
        assert store.get(key) == value

    @given(key=state_keys, value=st.integers())
    def test_an_int_round_trips(self, key: str, value: int) -> None:
        store = new_state_store()
        store.set(key, value)
        assert store.get(key) == value

    @given(key=state_keys, value=st.floats(allow_nan=False, allow_infinity=False))
    def test_a_float_round_trips(self, key: str, value: float) -> None:
        store = new_state_store()
        store.set(key, value)
        assert store.get(key) == value

    @given(key=state_keys, value=st.booleans())
    def test_a_bool_round_trips(self, key: str, value: bool) -> None:
        store = new_state_store()
        store.set(key, value)
        assert store.get(key) == value

    @given(key=state_keys, value=st.lists(st.integers(), max_size=10))
    def test_a_list_round_trips(self, key: str, value: list[int]) -> None:
        store = new_state_store()
        store.set(key, value)
        assert store.get(key) == value

    @given(
        key=state_keys,
        value=st.dictionaries(st.text(max_size=5), st.integers(), max_size=5),
    )
    def test_a_dict_round_trips(self, key: str, value: dict[str, int]) -> None:
        store = new_state_store()
        store.set(key, value)
        assert store.get(key) == value

    @given(key=state_keys)
    def test_a_missing_key_returns_the_default(self, key: str) -> None:
        """`get(key, sentinel)` returns the sentinel — a default, not a type."""
        store = new_state_store()
        sentinel = "not-there"
        assert store.get(key) is None
        assert store.get(key, sentinel) == sentinel

    @given(key=state_keys)
    def test_a_value_that_cannot_be_written_is_refused(self, key: str) -> None:
        """Validated at write time, where the offending call is on the stack."""
        store = new_state_store()
        with pytest.raises(TypeError, match="not JSON-serializable"):
            store.set(key, object())
