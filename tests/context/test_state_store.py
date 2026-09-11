"""Tests for the durable state store.

`_load` and the typed ``get(key, type)`` overload were removed with the
in-memory class: neither had a single caller in `src/`, `examples/` or `docs/`,
and re-implementing them on the durable store would have been building API for
nobody (*Pre-Release Stance*: delete rather than shim).
"""

import pytest

from functualize.job.context import InvalidStateTransitionError
from tests.context.conftest import new_state_store


def _closed_store():
    """A real store already sealed, as `WorkflowScope.close()` leaves it."""
    store = new_state_store()
    store._close()
    return store


class TestStateStoreGet:
    """Tests for FreshStore.get() method."""

    def test_get_returns_value_with_correct_type(self) -> None:
        store = new_state_store()
        store.set("name", "alice")
        assert store.get("name", str) == "alice"

    def test_get_with_list_type(self) -> None:
        store = new_state_store()
        store.set("items", [1, 2, 3])
        assert store.get("items", list) == [1, 2, 3]

    def test_get_with_dict_type(self) -> None:
        store = new_state_store()
        store.set("data", {"a": 1})
        assert store.get("data", dict) == {"a": 1}

    def test_get_with_bool_type(self) -> None:
        store = new_state_store()
        store.set("flag", True)
        assert store.get("flag", bool) is True

    def test_get_with_int_type(self) -> None:
        store = new_state_store()
        store.set("count", 99)
        assert store.get("count", int) == 99

    def test_get_with_float_type(self) -> None:
        store = new_state_store()
        store.set("ratio", 3.14)
        assert store.get("ratio", float) == 3.14


class TestStateStoreSet:
    """Tests for FreshStore.set() method."""

    def test_set_stores_json_serializable_value(self) -> None:
        store = new_state_store()
        store.set("key", "value")
        assert store.get("key", str) == "value"

    def test_set_overwrites_existing_value(self) -> None:
        store = new_state_store()
        store.set("key", "old")
        store.set("key", "new")
        assert store.get("key", str) == "new"

    def test_set_raises_type_error_for_non_serializable(self) -> None:
        store = new_state_store()
        with pytest.raises(TypeError, match="not JSON-serializable"):
            store.set("key", object())

    def test_set_raises_type_error_for_set_value(self) -> None:
        store = new_state_store()
        with pytest.raises(TypeError, match="not JSON-serializable"):
            store.set("key", {1, 2, 3})

    def test_set_raises_invalid_state_transition_when_closed(self) -> None:
        store = new_state_store()
        store._close()
        with pytest.raises(InvalidStateTransitionError, match="is closed"):
            store.set("key", "value")

    def test_set_accepts_none_value(self) -> None:
        store = new_state_store()
        store.set("key", None)
        # None is JSON-serializable, get returns None but key exists
        assert "key" in store.keys()  # noqa: SIM118

    def test_set_accepts_nested_structures(self) -> None:
        store = new_state_store()
        value = {"nested": {"list": [1, 2, 3], "flag": True}}
        store.set("complex", value)
        assert store.get("complex", dict) == value


class TestStateStoreKeys:
    """Tests for FreshStore.keys() method."""

    def test_keys_returns_empty_list_initially(self) -> None:
        store = new_state_store()
        assert store.keys() == []

    def test_keys_returns_stored_key_names(self) -> None:
        store = new_state_store()
        store.set("a", 1)
        store.set("b", 2)
        assert sorted(store.keys()) == ["a", "b"]

    def test_keys_returns_copy_not_reference(self) -> None:
        store = new_state_store()
        store.set("x", 1)
        keys = store.keys()
        keys.append("fake")
        assert store.keys() == ["x"]


class TestStateStoreClear:
    """Tests for FreshStore.clear() method."""

    def test_clear_removes_all_state(self) -> None:
        store = new_state_store()
        store.set("a", 1)
        store.set("b", 2)
        store.clear()
        assert store.keys() == []

    def test_clear_raises_invalid_state_transition_when_closed(self) -> None:
        store = new_state_store()
        store.set("a", 1)
        store._close()
        with pytest.raises(InvalidStateTransitionError, match="is closed"):
            store.clear()


class TestStateStoreToDict:
    """Tests for FreshStore.to_dict() method."""

    def test_to_dict_returns_empty_dict_initially(self) -> None:
        store = new_state_store()
        assert store.to_dict() == {}

    def test_to_dict_returns_copy_of_state(self) -> None:
        store = new_state_store()
        store.set("x", 10)
        store.set("y", "hello")
        result = store.to_dict()
        assert result == {"x": 10, "y": "hello"}
        # Verify it's a copy
        result["z"] = "injected"
        assert "z" not in store.keys()  # noqa: SIM118


class TestStateStoreClose:
    """Tests for FreshStore._close() method."""

    def test_close_prevents_set(self) -> None:
        store = new_state_store()
        store._close()
        with pytest.raises(InvalidStateTransitionError):
            store.set("key", "value")

    def test_close_prevents_clear(self) -> None:
        store = new_state_store()
        store._close()
        with pytest.raises(InvalidStateTransitionError):
            store.clear()

    def test_close_allows_get(self) -> None:
        store = new_state_store()
        store.set("key", "value")
        store._close()
        # Read operations still work
        assert store.get("key", str) == "value"

    def test_close_allows_keys(self) -> None:
        store = new_state_store()
        store.set("key", "value")
        store._close()
        assert store.keys() == ["key"]

    def test_close_allows_to_dict(self) -> None:
        store = new_state_store()
        store.set("key", "value")
        store._close()
        assert store.to_dict() == {"key": "value"}

    def test_init_with_closed_flag(self) -> None:
        store = _closed_store()
        with pytest.raises(InvalidStateTransitionError):
            store.set("key", "value")
