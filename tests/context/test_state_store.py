"""Unit tests for the StateStore module."""

import pytest

from functualize.job._state_store import StateStore
from functualize.job.context import InvalidStateTransitionError


class TestStateStoreGet:
    """Tests for StateStore.get() method."""

    def test_get_returns_none_for_missing_key(self) -> None:
        store = StateStore()
        assert store.get("missing", str) is None

    def test_get_returns_value_with_correct_type(self) -> None:
        store = StateStore()
        store.set("name", "alice")
        assert store.get("name", str) == "alice"

    def test_get_raises_type_error_on_type_mismatch(self) -> None:
        store = StateStore()
        store.set("count", 42)
        with pytest.raises(TypeError, match="expected str, got int"):
            store.get("count", str)

    def test_get_with_list_type(self) -> None:
        store = StateStore()
        store.set("items", [1, 2, 3])
        assert store.get("items", list) == [1, 2, 3]

    def test_get_with_dict_type(self) -> None:
        store = StateStore()
        store.set("data", {"a": 1})
        assert store.get("data", dict) == {"a": 1}

    def test_get_with_bool_type(self) -> None:
        store = StateStore()
        store.set("flag", True)
        assert store.get("flag", bool) is True

    def test_get_with_int_type(self) -> None:
        store = StateStore()
        store.set("count", 99)
        assert store.get("count", int) == 99

    def test_get_with_float_type(self) -> None:
        store = StateStore()
        store.set("ratio", 3.14)
        assert store.get("ratio", float) == 3.14


class TestStateStoreSet:
    """Tests for StateStore.set() method."""

    def test_set_stores_json_serializable_value(self) -> None:
        store = StateStore()
        store.set("key", "value")
        assert store.get("key", str) == "value"

    def test_set_overwrites_existing_value(self) -> None:
        store = StateStore()
        store.set("key", "old")
        store.set("key", "new")
        assert store.get("key", str) == "new"

    def test_set_raises_type_error_for_non_serializable(self) -> None:
        store = StateStore()
        with pytest.raises(TypeError, match="not JSON-serializable"):
            store.set("key", object())

    def test_set_raises_type_error_for_set_value(self) -> None:
        store = StateStore()
        with pytest.raises(TypeError, match="not JSON-serializable"):
            store.set("key", {1, 2, 3})

    def test_set_raises_invalid_state_transition_when_closed(self) -> None:
        store = StateStore()
        store._close()
        with pytest.raises(InvalidStateTransitionError, match="closed Workflow_Scope"):
            store.set("key", "value")

    def test_set_accepts_none_value(self) -> None:
        store = StateStore()
        store.set("key", None)
        # None is JSON-serializable, get returns None but key exists
        assert "key" in store.keys()  # noqa: SIM118

    def test_set_accepts_nested_structures(self) -> None:
        store = StateStore()
        value = {"nested": {"list": [1, 2, 3], "flag": True}}
        store.set("complex", value)
        assert store.get("complex", dict) == value


class TestStateStoreKeys:
    """Tests for StateStore.keys() method."""

    def test_keys_returns_empty_list_initially(self) -> None:
        store = StateStore()
        assert store.keys() == []

    def test_keys_returns_stored_key_names(self) -> None:
        store = StateStore()
        store.set("a", 1)
        store.set("b", 2)
        assert sorted(store.keys()) == ["a", "b"]

    def test_keys_returns_copy_not_reference(self) -> None:
        store = StateStore()
        store.set("x", 1)
        keys = store.keys()
        keys.append("fake")
        assert store.keys() == ["x"]


class TestStateStoreClear:
    """Tests for StateStore.clear() method."""

    def test_clear_removes_all_state(self) -> None:
        store = StateStore()
        store.set("a", 1)
        store.set("b", 2)
        store.clear()
        assert store.keys() == []
        assert store.get("a", int) is None

    def test_clear_raises_invalid_state_transition_when_closed(self) -> None:
        store = StateStore()
        store.set("a", 1)
        store._close()
        with pytest.raises(InvalidStateTransitionError, match="closed Workflow_Scope"):
            store.clear()


class TestStateStoreToDict:
    """Tests for StateStore.to_dict() method."""

    def test_to_dict_returns_empty_dict_initially(self) -> None:
        store = StateStore()
        assert store.to_dict() == {}

    def test_to_dict_returns_copy_of_state(self) -> None:
        store = StateStore()
        store.set("x", 10)
        store.set("y", "hello")
        result = store.to_dict()
        assert result == {"x": 10, "y": "hello"}
        # Verify it's a copy
        result["z"] = "injected"
        assert "z" not in store.keys()  # noqa: SIM118


class TestStateStoreLoad:
    """Tests for StateStore._load() method."""

    def test_load_replaces_existing_data(self) -> None:
        store = StateStore()
        store.set("old", "value")
        store._load({"new": "data"})
        assert store.get("old", str) is None
        assert store.get("new", str) == "data"

    def test_load_makes_a_copy(self) -> None:
        store = StateStore()
        data = {"key": "value"}
        store._load(data)
        data["mutated"] = "yes"
        assert store.get("mutated", str) is None


class TestStateStoreClose:
    """Tests for StateStore._close() method."""

    def test_close_prevents_set(self) -> None:
        store = StateStore()
        store._close()
        with pytest.raises(InvalidStateTransitionError):
            store.set("key", "value")

    def test_close_prevents_clear(self) -> None:
        store = StateStore()
        store._close()
        with pytest.raises(InvalidStateTransitionError):
            store.clear()

    def test_close_allows_get(self) -> None:
        store = StateStore()
        store.set("key", "value")
        store._close()
        # Read operations still work
        assert store.get("key", str) == "value"

    def test_close_allows_keys(self) -> None:
        store = StateStore()
        store.set("key", "value")
        store._close()
        assert store.keys() == ["key"]

    def test_close_allows_to_dict(self) -> None:
        store = StateStore()
        store.set("key", "value")
        store._close()
        assert store.to_dict() == {"key": "value"}

    def test_init_with_closed_flag(self) -> None:
        store = StateStore(_closed=True)
        with pytest.raises(InvalidStateTransitionError):
            store.set("key", "value")
