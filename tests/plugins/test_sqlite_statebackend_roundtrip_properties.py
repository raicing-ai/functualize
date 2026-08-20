"""Property-based tests for SQLite StateBackend round-trip.

Property 7: SQLite StateBackend round-trip
For any JSON-serializable key-value pair (k, v), after calling backend.set(k, v)
on the SQLite StateBackend, calling backend.get(k) SHALL return a value equal to v.

**Validates: Requirements 4.8**
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from functualize_state_sqlite import SQLiteStateBackend
from hypothesis import given
from hypothesis import strategies as st

# --- Strategies ---

# Strategy for valid state keys (non-empty strings, no null bytes)
state_keys = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S"),
        whitelist_characters="-_. /:",
    ),
    min_size=1,
    max_size=64,
)

# Strategy for JSON-serializable primitive values
json_primitives = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**53), max_value=2**53),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=100),
)

# Recursive strategy for nested JSON-serializable structures
json_values = st.recursive(
    json_primitives,
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(max_size=20), children, max_size=5),
    ),
    max_leaves=10,
)


def _make_backend() -> SQLiteStateBackend:
    """Create an SQLiteStateBackend using a temp directory."""
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test_state.db"
    return SQLiteStateBackend(db_path=db_path)


# --- Property 7: SQLite StateBackend round-trip ---


class TestSQLiteStateBackendRoundTrip:
    """Property 7: For any JSON-serializable key-value pair (k, v), after calling
    backend.set(k, v) on the SQLite StateBackend, calling backend.get(k) SHALL
    return a value equal to v.

    **Validates: Requirements 4.8**
    """

    @given(key=state_keys, value=json_values)
    def test_set_then_get_returns_equal_value(self, key: str, value: Any):
        """**Validates: Requirements 4.8**

        For any JSON-serializable key-value pair (k, v), after calling
        backend.set(k, v), calling backend.get(k) returns a value equal to v.
        """
        backend = _make_backend()
        try:
            backend.set(key, value)
            retrieved = backend.get(key)

            assert retrieved == value, (
                f"Round-trip failed for key={key!r}, value={value!r}, got={retrieved!r}"
            )
        finally:
            backend.close()

    @given(key=state_keys, value=json_values)
    def test_overwrite_returns_latest_value(self, key: str, value: Any):
        """**Validates: Requirements 4.8**

        Overwriting an existing key returns the latest value on get.
        """
        backend = _make_backend()
        try:
            # Write an initial value
            backend.set(key, "initial-sentinel")
            # Overwrite with the generated value
            backend.set(key, value)
            retrieved = backend.get(key)

            assert retrieved == value, (
                f"Overwrite failed for key={key!r}, value={value!r}, got={retrieved!r}"
            )
        finally:
            backend.close()

    @given(
        key=state_keys,
        value1=json_values,
        value2=json_values,
    )
    def test_distinct_keys_do_not_interfere(self, key: str, value1: Any, value2: Any):
        """**Validates: Requirements 4.8**

        Setting different keys does not cause interference — each key
        independently round-trips its own value.
        """
        # Create two distinct keys
        key1 = "a:" + key
        key2 = "b:" + key

        backend = _make_backend()
        try:
            backend.set(key1, value1)
            backend.set(key2, value2)

            assert backend.get(key1) == value1, (
                f"key1 interference: expected {value1!r}, got {backend.get(key1)!r}"
            )
            assert backend.get(key2) == value2, (
                f"key2 interference: expected {value2!r}, got {backend.get(key2)!r}"
            )
        finally:
            backend.close()
