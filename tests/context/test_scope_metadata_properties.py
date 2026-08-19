"""Property-based tests for StateStore replacement and JobResult metadata.

Property 14: StateStore replacement — new store used, no data migration
**Validates: Requirements 7.5**

Property 21: JobResult metadata — maximum 64 keys enforced
**Validates: Requirements 15.5**
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from hypothesis import given
from hypothesis import strategies as st

from functualize.job._workflow_scope import WorkflowScope
from functualize.job.context import RunContext

# --- Strategies ---

# Strategy for valid scope IDs (non-empty strings)
scope_ids = st.text(
    alphabet=st.characters(categories=("L", "N", "Pd", "Pc")),
    min_size=1,
    max_size=50,
)

# Strategy for state keys (non-empty strings suitable for dict keys)
state_keys = st.text(
    alphabet=st.characters(categories=("L", "N", "Pd", "Pc")),
    min_size=1,
    max_size=30,
)

# Strategy for JSON-serializable values
json_values: st.SearchStrategy[object] = st.recursive(
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(max_size=20),
    lambda children: (
        st.lists(children, max_size=3)
        | st.dictionaries(st.text(max_size=10), children, max_size=3)
    ),
    max_leaves=5,
)

# Strategy for metadata keys (unique, non-empty strings)
metadata_keys = st.text(
    alphabet=st.characters(categories=("L", "N", "Pd", "Pc")),
    min_size=1,
    max_size=30,
)


# --- Helpers ---


class ConformingStore:
    """A minimal in-memory store satisfying StateStoreProtocol."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._job_namespaces: dict[str, dict[str, Any]] = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def keys(self) -> list[str]:
        return list(self._data.keys())

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)

    def clear(self) -> None:
        self._data.clear()

    def get_job_state(self, job_name: str, key: str, default: Any = None) -> Any:
        namespace = self._job_namespaces.get(job_name, {})
        return namespace.get(key, default)

    def list_job_namespaces(self) -> list[str]:
        return list(self._job_namespaces.keys())


# --- Property 14: StateStore replacement — new store used, no data migration ---


# Feature: plugin-ecosystem-enablement, Property 14: StateStore replacement
# For any WorkflowScope with state written to the original store, after
# replace_state_store(new_store) is called with a protocol-conforming store,
# all subsequent state operations SHALL use the new store, and the new store
# SHALL NOT contain data from the previous store.
# **Validates: Requirements 7.5**
class TestStateStoreReplacement:
    """Property 14: StateStore replacement — new store used, no data migration."""

    @given(
        scope_id=scope_ids,
        initial_data=st.dictionaries(
            keys=state_keys,
            values=json_values,
            min_size=1,
            max_size=10,
        ),
    )
    def test_new_store_does_not_contain_previous_data(
        self, scope_id: str, initial_data: dict[str, object]
    ) -> None:
        """After replace_state_store, the new store does NOT contain data from the old store.

        **Validates: Requirements 7.5**
        """
        scope = WorkflowScope(scope_id)

        # Write data to the original store
        for key, value in initial_data.items():
            scope.state_store.set(key, value)

        # Replace with a new conforming store
        new_store = ConformingStore()
        scope.replace_state_store(new_store)

        # New store should be empty — no data migration
        assert new_store.to_dict() == {}
        assert new_store.keys() == []

        # None of the old keys should be accessible via the new store
        for key in initial_data:
            assert scope.state_store.get(key) is None

    @given(
        scope_id=scope_ids,
        initial_data=st.dictionaries(
            keys=state_keys,
            values=json_values,
            min_size=1,
            max_size=10,
        ),
        new_data=st.dictionaries(
            keys=state_keys,
            values=json_values,
            min_size=1,
            max_size=10,
        ),
    )
    def test_subsequent_ops_use_new_store(
        self,
        scope_id: str,
        initial_data: dict[str, object],
        new_data: dict[str, object],
    ) -> None:
        """After replacement, all subsequent state operations use the new store.

        **Validates: Requirements 7.5**
        """
        scope = WorkflowScope(scope_id)

        # Write data to the original store
        for key, value in initial_data.items():
            scope.state_store.set(key, value)

        # Replace with a new conforming store
        new_store = ConformingStore()
        scope.replace_state_store(new_store)

        # Write new data — should go to the new store
        for key, value in new_data.items():
            scope.state_store.set(key, value)

        # The new store should contain exactly the new data
        for key, value in new_data.items():
            assert new_store.get(key) == value

        # The scope's state_store property should point to the new store
        assert scope.state_store is new_store

    @given(
        scope_id=scope_ids,
        initial_data=st.dictionaries(
            keys=state_keys,
            values=json_values,
            min_size=1,
            max_size=10,
        ),
        new_key=state_keys,
        new_value=json_values,
    )
    def test_new_store_get_set_delete_keys_operations(
        self,
        scope_id: str,
        initial_data: dict[str, object],
        new_key: str,
        new_value: object,
    ) -> None:
        """All CRUD operations (get, set, delete, keys) go through the new store after replacement.

        **Validates: Requirements 7.5**
        """
        scope = WorkflowScope(scope_id)

        # Write to original store
        for key, value in initial_data.items():
            scope.state_store.set(key, value)

        # Replace
        new_store = ConformingStore()
        scope.replace_state_store(new_store)

        # set via scope goes to new store
        scope.state_store.set(new_key, new_value)
        assert new_store.get(new_key) == new_value

        # get via scope reads from new store
        assert scope.state_store.get(new_key) == new_value

        # keys via scope reflects new store. StateStoreProtocol exposes
        # membership through `keys()` — which returns a list — and defines no
        # `__contains__`, so a conforming store is not required to answer `in`.
        store_keys = scope.state_store.keys()
        assert new_key in store_keys

        # delete via scope operates on new store
        scope.state_store.delete(new_key)
        assert new_store.get(new_key) is None

    @given(
        scope_id=scope_ids,
        initial_data=st.dictionaries(
            keys=state_keys,
            values=json_values,
            min_size=1,
            max_size=10,
        ),
    )
    def test_original_store_data_preserved_after_replacement(
        self, scope_id: str, initial_data: dict[str, object]
    ) -> None:
        """The original store retains its data after replacement (it is not cleared).

        **Validates: Requirements 7.5**
        """
        scope = WorkflowScope(scope_id)
        original_store = scope.state_store

        # Write data to original store
        for key, value in initial_data.items():
            original_store.set(key, value)

        # Replace
        new_store = ConformingStore()
        scope.replace_state_store(new_store)

        # Original store should still have its data (no side-effects)
        for key, value in initial_data.items():
            assert original_store.get(key) == value


# --- Property 21: JobResult metadata — maximum 64 keys enforced ---


# Feature: plugin-ecosystem-enablement, Property 21: JobResult metadata max 64 keys
# For any sequence of metadata key-value writes during execution, the resulting
# JobResult.metadata SHALL contain at most 64 keys, with excess writes silently
# discarded.
# **Validates: Requirements 15.5**
class TestJobResultMetadataMaxKeys:
    """Property 21: JobResult metadata — maximum 64 keys enforced."""

    @given(
        keys=st.lists(
            metadata_keys,
            min_size=65,
            max_size=150,
            unique=True,
        ),
    )
    def test_metadata_never_exceeds_64_keys(self, keys: list[str]) -> None:
        """Writing more than 64 unique keys results in at most 64 keys stored.

        **Validates: Requirements 15.5**
        """
        config = MagicMock()
        config.set_prefix = MagicMock()
        logger = MagicMock()
        rc = RunContext(name="test-job", config=config, logger=logger)

        # Write all keys
        for i, key in enumerate(keys):
            rc.set_result_metadata(key, f"value_{i}")

        # At most 64 keys stored
        assert len(rc.result_metadata) <= 64

    @given(
        keys=st.lists(
            metadata_keys,
            min_size=1,
            max_size=64,
            unique=True,
        ),
    )
    def test_metadata_within_limit_all_stored(self, keys: list[str]) -> None:
        """Writing up to 64 unique keys stores all of them.

        **Validates: Requirements 15.5**
        """
        config = MagicMock()
        config.set_prefix = MagicMock()
        logger = MagicMock()
        rc = RunContext(name="test-job", config=config, logger=logger)

        # Write keys within limit
        for i, key in enumerate(keys):
            rc.set_result_metadata(key, f"value_{i}")

        # All keys should be stored
        assert len(rc.result_metadata) == len(keys)
        for i, key in enumerate(keys):
            assert rc.result_metadata[key] == f"value_{i}"

    @given(
        keys=st.lists(
            metadata_keys,
            min_size=65,
            max_size=150,
            unique=True,
        ),
    )
    def test_excess_writes_silently_discarded(self, keys: list[str]) -> None:
        """Keys beyond the 64 limit are silently discarded (no exception raised).

        **Validates: Requirements 15.5**
        """
        config = MagicMock()
        config.set_prefix = MagicMock()
        logger = MagicMock()
        rc = RunContext(name="test-job", config=config, logger=logger)

        # Should not raise — excess writes are silently discarded
        for i, key in enumerate(keys):
            rc.set_result_metadata(key, f"value_{i}")

        # First 64 keys are stored, the rest are discarded
        assert len(rc.result_metadata) == 64
        # The first 64 keys should be in the metadata
        for i, key in enumerate(keys[:64]):
            assert key in rc.result_metadata
            assert rc.result_metadata[key] == f"value_{i}"
        # Keys beyond 64 should NOT be in the metadata
        for key in keys[64:]:
            assert key not in rc.result_metadata

    @given(
        keys=st.lists(
            metadata_keys,
            min_size=64,
            max_size=64,
            unique=True,
        ),
        update_index=st.integers(min_value=0, max_value=63),
    )
    def test_updating_existing_key_at_limit_succeeds(
        self, keys: list[str], update_index: int
    ) -> None:
        """Updating an existing key when at the 64-key limit always succeeds.

        **Validates: Requirements 15.5**
        """
        config = MagicMock()
        config.set_prefix = MagicMock()
        logger = MagicMock()
        rc = RunContext(name="test-job", config=config, logger=logger)

        # Fill to the limit
        for i, key in enumerate(keys):
            rc.set_result_metadata(key, f"value_{i}")

        assert len(rc.result_metadata) == 64

        # Updating an existing key should succeed
        target_key = keys[update_index]
        rc.set_result_metadata(target_key, "updated_value")

        assert rc.result_metadata[target_key] == "updated_value"
        assert len(rc.result_metadata) == 64
