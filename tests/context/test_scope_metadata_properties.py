"""Property-based tests for ScopeStore replacement and JobResult metadata.

Property 14: ScopeStore replacement — new store used, no data migration
**Validates: Requirements 7.5**

Property 21: JobResult metadata — maximum 64 keys enforced
**Validates: Requirements 15.5**
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from hypothesis import given
from hypothesis import strategies as st

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


# --- Property 14: ScopeStore replacement — new store used, no data migration ---


# Feature: plugin-ecosystem-enablement, Property 14: ScopeStore replacement
# For any WorkflowScope with state written to the original store, after
# replace_state_store(new_store) is called with a protocol-conforming store,
# all subsequent state operations SHALL use the new store, and the new store
# SHALL NOT contain data from the previous store.
# **Validates: Requirements 7.5**
# Property 14 — "ScopeStore replacement: new store used, no data migration" —
# is gone with `WorkflowScope.replace_state_store` (`store-substrate`/T5). Four
# Hypothesis cases described a swap that can no longer be expressed: a plugin
# supplies a substrate, and every store moves with it or none does. That the
# method and its protocol are absent is asserted once, in
# `tests/core/test_scope_state_metadata.py::TestTheSeamIsGone`, rather than
# restated as a property over generated data.


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
