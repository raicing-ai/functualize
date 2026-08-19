"""Property-based tests for StateNamespace prefix isolation.

Tests Property 1 from the Phase 2–5 Domain SDKs design document.

Property 1: StateNamespace prefix isolation — For any prefix string p and any key k,
when a StateNamespace(backend, p) performs set(k, v), the underlying backend SHALL
store the value under the key p + k; and when get(k) is called, it SHALL return the
value stored at p + k in the backend; and keys() SHALL return only keys from the
backend that start with p, with the prefix stripped.

**Validates: Requirements 3.5, 26.4**
"""

from __future__ import annotations

from typing import Any

from functualize_state import InMemoryState, StateNamespace
from hypothesis import given
from hypothesis import strategies as st

# --- Strategies ---

# Strategy for non-empty prefix strings
prefix_strings = st.text(min_size=1, max_size=30)

# Strategy for valid state keys (non-empty strings)
state_keys = st.text(min_size=1, max_size=50)

# Strategy for JSON-like values
json_primitives = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**53), max_value=2**53),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=100),
)

json_values = st.recursive(
    json_primitives,
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(max_size=20), children, max_size=5),
    ),
    max_leaves=10,
)

# Strategy for generating a dict of state entries
state_entries = st.dictionaries(
    keys=state_keys,
    values=json_values,
    min_size=0,
    max_size=15,
)


# --- Property 1: StateNamespace prefix isolation ---


class TestStateNamespaceSetStoresAtPrefixedKey:
    """Property 1a: set(k, v) stores at prefix + k in the underlying backend.

    **Validates: Requirements 3.5, 26.4**
    """

    @given(prefix=prefix_strings, key=state_keys, value=json_values)
    def test_set_stores_value_at_prefixed_key_in_backend(
        self, prefix: str, key: str, value: Any
    ) -> None:
        """set(k, v) stores the value under prefix + k in the backend.

        **Validates: Requirements 3.5, 26.4**
        """
        backend = InMemoryState()
        ns = StateNamespace(backend, prefix)

        ns.set(key, value)

        # The backend should have the value stored at prefix + key
        assert backend.get(prefix + key) == value

    @given(prefix=prefix_strings, key=state_keys, value=json_values)
    def test_set_does_not_store_at_unprefixed_key(
        self, prefix: str, key: str, value: Any
    ) -> None:
        """set(k, v) does NOT store at key k directly (only at prefix + k).

        **Validates: Requirements 3.5, 26.4**
        """
        backend = InMemoryState()
        ns = StateNamespace(backend, prefix)

        ns.set(key, value)

        # Unless key == prefix + key (which only happens if prefix is empty,
        # but our prefix strategy has min_size=1), the unprefixed key should
        # not exist in the backend
        if prefix + key != key:
            assert backend.get(key) is None


class TestStateNamespaceGetReturnsPrefixedValue:
    """Property 1b: get(k) returns the value stored at prefix + k in the backend.

    **Validates: Requirements 3.5, 26.4**
    """

    @given(prefix=prefix_strings, key=state_keys, value=json_values)
    def test_get_returns_value_stored_at_prefixed_key(
        self, prefix: str, key: str, value: Any
    ) -> None:
        """get(k) returns the value at prefix + k from the backend.

        **Validates: Requirements 3.5, 26.4**
        """
        backend = InMemoryState()
        ns = StateNamespace(backend, prefix)

        # Store directly in backend at prefix + key
        backend.set(prefix + key, value)

        # Namespace get should return the same value
        assert ns.get(key) == value

    @given(prefix=prefix_strings, key=state_keys, value=json_values)
    def test_roundtrip_set_then_get(self, prefix: str, key: str, value: Any) -> None:
        """set(k, v) followed by get(k) returns v.

        **Validates: Requirements 3.5, 26.4**
        """
        backend = InMemoryState()
        ns = StateNamespace(backend, prefix)

        ns.set(key, value)
        result = ns.get(key)

        assert result == value

    @given(prefix=prefix_strings, key=state_keys)
    def test_get_returns_default_when_key_not_set(self, prefix: str, key: str) -> None:
        """get(k) returns the default when prefix + k is not in the backend.

        **Validates: Requirements 3.5, 26.4**
        """
        backend = InMemoryState()
        ns = StateNamespace(backend, prefix)

        sentinel = object()
        result = ns.get(key, sentinel)

        assert result is sentinel


class TestStateNamespaceKeysReturnsFilteredStrippedKeys:
    """Property 1c: keys() returns only keys from the backend that start with
    the prefix, with the prefix stripped.

    **Validates: Requirements 3.5, 26.4**
    """

    @given(prefix=prefix_strings, entries=state_entries)
    def test_keys_returns_only_prefixed_keys_stripped(
        self, prefix: str, entries: dict[str, Any]
    ) -> None:
        """keys() returns only keys starting with prefix, with prefix stripped.

        **Validates: Requirements 3.5, 26.4**
        """
        backend = InMemoryState()
        ns = StateNamespace(backend, prefix)

        # Store entries via the namespace (which adds the prefix)
        for k, v in entries.items():
            ns.set(k, v)

        result = ns.keys()

        # All original keys should be returned (stripped of prefix)
        assert sorted(result) == sorted(entries.keys())

    @given(
        prefix=prefix_strings,
        ns_entries=state_entries,
        other_entries=state_entries,
    )
    def test_keys_excludes_non_prefixed_backend_keys(
        self,
        prefix: str,
        ns_entries: dict[str, Any],
        other_entries: dict[str, Any],
    ) -> None:
        """keys() excludes backend keys that do not start with the prefix.

        **Validates: Requirements 3.5, 26.4**
        """
        backend = InMemoryState()
        ns = StateNamespace(backend, prefix)

        # Store entries via the namespace
        for k, v in ns_entries.items():
            ns.set(k, v)

        # Store other entries directly in the backend with a different prefix
        other_prefix = "OTHER_" + prefix + "_OTHER_"
        for k, v in other_entries.items():
            backend.set(other_prefix + k, v)

        result = ns.keys()

        # The namespace keys should only contain the ns_entries keys
        assert sorted(result) == sorted(ns_entries.keys())

    @given(
        prefix_a=prefix_strings,
        prefix_b=prefix_strings,
        entries_a=state_entries,
        entries_b=state_entries,
    )
    def test_two_namespaces_keys_are_isolated(
        self,
        prefix_a: str,
        prefix_b: str,
        entries_a: dict[str, Any],
        entries_b: dict[str, Any],
    ) -> None:
        """Two namespaces with different prefixes have isolated keys.

        **Validates: Requirements 3.5, 26.4**
        """
        # Ensure prefixes are distinct for proper isolation testing
        if prefix_a == prefix_b:
            prefix_b = prefix_b + "_other"

        # Ensure neither prefix is a prefix of the other to avoid ambiguity
        if prefix_a.startswith(prefix_b) or prefix_b.startswith(prefix_a):
            prefix_a = "NS_A:" + prefix_a
            prefix_b = "NS_B:" + prefix_b

        backend = InMemoryState()
        ns_a = StateNamespace(backend, prefix_a)
        ns_b = StateNamespace(backend, prefix_b)

        # Store entries in both namespaces
        for k, v in entries_a.items():
            ns_a.set(k, v)
        for k, v in entries_b.items():
            ns_b.set(k, v)

        # Each namespace sees only its own keys
        assert sorted(ns_a.keys()) == sorted(entries_a.keys())
        assert sorted(ns_b.keys()) == sorted(entries_b.keys())
