"""Property-based tests for AppState class.

Tests Properties 22, 23, and 24 from the design document.
Validates: Requirements 8.1, 8.3, 8.4, 8.5
"""

import threading
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._app.state import AppState


@pytest.fixture(autouse=True)
def _reset_state():
    """Ensure AppState is clean before and after each test."""
    AppState.reset()
    yield
    AppState.reset()


# Strategy for generating arbitrary JSON-like values that AppState can store
json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(),
    lambda children: st.lists(children) | st.dictionaries(st.text(), children),
    max_leaves=5,
)

# Strategy for valid state keys (non-empty strings)
state_keys = st.text(min_size=1, max_size=50)


# Feature: functualize, Property 22: AppState Round-Trip
# For any key-value pair, calling AppState.set(key, value) followed by
# AppState.get(key) SHALL return the same value.
# Validates: Requirements 8.1
class TestAppStateRoundTrip:
    """Property 22: AppState Round-Trip."""

    @given(key=state_keys, value=json_values)
    @settings(max_examples=100)
    def test_set_then_get_returns_same_value(self, key: str, value: Any):
        """For any key-value pair, set followed by get returns the same value."""
        # Feature: functualize, Property 22: AppState Round-Trip
        # **Validates: Requirements 8.1**
        AppState.reset()
        AppState.set(key, value)
        result = AppState.get(key)
        assert result == value

    @given(
        key=state_keys,
        value1=json_values,
        value2=json_values,
    )
    @settings(max_examples=100)
    def test_last_set_wins(self, key: str, value1: Any, value2: Any):
        """For any key set multiple times, get returns the last value set."""
        # Feature: functualize, Property 22: AppState Round-Trip
        # **Validates: Requirements 8.1**
        AppState.reset()
        AppState.set(key, value1)
        AppState.set(key, value2)
        result = AppState.get(key)
        assert result == value2


# Feature: functualize, Property 23: AppState Reset and Unset Behavior
# For any AppState with stored values, calling reset() SHALL cause all
# subsequent get() calls to return None. For any key never set, get(key)
# SHALL return None.
# Validates: Requirements 8.3, 8.4
class TestAppStateResetAndUnset:
    """Property 23: AppState Reset and Unset Behavior."""

    @given(
        data=st.dictionaries(state_keys, json_values, min_size=1, max_size=10),
    )
    @settings(max_examples=100)
    def test_reset_clears_all_values(self, data: dict[str, Any]):
        """After reset(), all previously set keys return None."""
        # Feature: functualize, Property 23: AppState Reset and Unset Behavior
        # **Validates: Requirements 8.3, 8.4**
        AppState.reset()
        for key, value in data.items():
            AppState.set(key, value)

        AppState.reset()

        for key in data:
            assert AppState.get(key) is None

    @given(key=state_keys)
    @settings(max_examples=100)
    def test_get_unset_key_returns_none(self, key: str):
        """For any key never set, get(key) returns None."""
        # Feature: functualize, Property 23: AppState Reset and Unset Behavior
        # **Validates: Requirements 8.3, 8.4**
        AppState.reset()
        assert AppState.get(key) is None


# Feature: functualize, Property 24: AppState Thread Safety
# For any set of concurrent get() and set() operations from multiple threads,
# the AppState SHALL not raise exceptions or corrupt internal state (every
# get() returns either None or a value previously passed to set() for that key).
# Validates: Requirements 8.5
class TestAppStateThreadSafety:
    """Property 24: AppState Thread Safety."""

    @given(
        data=st.dictionaries(
            st.text(
                min_size=1, max_size=10, alphabet=st.characters(categories=("L", "N"))
            ),
            st.integers(),
            min_size=2,
            max_size=5,
        ),
    )
    @settings(max_examples=100)
    def test_concurrent_get_set_no_exceptions_or_corruption(self, data: dict[str, int]):
        """Concurrent get/set operations never raise or corrupt state."""
        # Feature: functualize, Property 24: AppState Thread Safety
        # **Validates: Requirements 8.5**
        AppState.reset()
        errors: list[Exception] = []
        keys = list(data.keys())
        values = list(data.values())
        # Track all values ever written per key
        valid_values: dict[str, set[int]] = {k: {v} for k, v in data.items()}

        barrier = threading.Barrier(len(keys) * 2)

        def writer(key: str, value: int):
            try:
                barrier.wait(timeout=5)
                for i in range(20):
                    new_val = value + i
                    valid_values[key].add(new_val)
                    AppState.set(key, new_val)
            except Exception as e:
                errors.append(e)

        def reader(key: str):
            try:
                barrier.wait(timeout=5)
                for _ in range(20):
                    result = AppState.get(key)
                    # Must be None or a value previously set for this key
                    assert result is None or result in valid_values[key], (
                        f"Got unexpected value {result!r} for key {key!r}"
                    )
            except Exception as e:
                errors.append(e)

        threads: list[threading.Thread] = []
        for key, value in zip(keys, values, strict=True):
            threads.append(threading.Thread(target=writer, args=(key, value)))
            threads.append(threading.Thread(target=reader, args=(key,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == [], f"Thread errors: {errors}"

    @given(
        keys=st.lists(
            st.text(
                min_size=1, max_size=10, alphabet=st.characters(categories=("L", "N"))
            ),
            min_size=1,
            max_size=5,
        ),
    )
    @settings(max_examples=100)
    def test_concurrent_reset_with_get_set_no_exceptions(self, keys: list[str]):
        """Concurrent reset with get/set never raises exceptions."""
        # Feature: functualize, Property 24: AppState Thread Safety
        # **Validates: Requirements 8.5**
        AppState.reset()
        errors: list[Exception] = []
        barrier = threading.Barrier(3)

        def setter():
            try:
                barrier.wait(timeout=5)
                for i in range(20):
                    for key in keys:
                        AppState.set(key, i)
            except Exception as e:
                errors.append(e)

        def resetter():
            try:
                barrier.wait(timeout=5)
                for _ in range(10):
                    AppState.reset()
            except Exception as e:
                errors.append(e)

        def getter():
            try:
                barrier.wait(timeout=5)
                for _ in range(20):
                    for key in keys:
                        result = AppState.get(key)
                        # After reset, get returns None; after set, returns an int
                        assert result is None or isinstance(result, int), (
                            f"Got unexpected type {type(result)} for key {key!r}"
                        )
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=setter),
            threading.Thread(target=resetter),
            threading.Thread(target=getter),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == [], f"Thread errors: {errors}"
