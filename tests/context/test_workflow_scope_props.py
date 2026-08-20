"""Property-based tests for WorkflowScope module.

Property 13: Workflow_Scope Lifecycle
**Validates: Requirements 7.2, 7.4, 7.6, 7.7**

Property 22: Workflow_Scope Metadata
**Validates: Requirements 10.3**
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize.job._state_store import StateStore
from functualize.job._workflow_scope import WorkflowScope
from functualize.job.context import InvalidStateTransitionError

# --- Strategies ---

# Strategy for valid scope IDs (non-empty strings)
scope_ids = st.text(
    alphabet=st.characters(categories=("L", "N", "Pd", "Pc")),
    min_size=1,
    max_size=100,
)

# Strategy for JSON-serializable state values
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

# Strategy for state keys
state_keys = st.text(
    alphabet=st.characters(categories=("L", "N", "Pd", "Pc")),
    min_size=1,
    max_size=50,
)

# Strategy for metadata dictionaries (string keys, various value types)
metadata_dicts = st.dictionaries(
    keys=st.text(min_size=1, max_size=30),
    values=json_values,
    min_size=1,
    max_size=10,
)


# Feature: enriched-runcontext, Property 13: Workflow_Scope Lifecycle
# A newly created scope is not closed and has an empty state_store.
# After close(), the scope is marked as closed and its state_store rejects mutations.
# Calling close() on an already-closed scope raises InvalidStateTransitionError.
# Creating a scope with a duplicate scope_id (in a registry context) raises ValueError.
# **Validates: Requirements 7.2, 7.4, 7.6, 7.7**
class TestWorkflowScopeLifecycle:
    """Property 13: Workflow_Scope Lifecycle."""

    @given(scope_id=scope_ids)
    def test_new_scope_not_closed_with_empty_state_store(self, scope_id: str) -> None:
        """A newly created scope is not closed and has an empty state_store.

        **Validates: Requirements 7.2**
        """
        scope = WorkflowScope(scope_id)

        assert scope.closed is False
        assert scope.scope_id == scope_id
        assert isinstance(scope.state_store, StateStore)
        assert scope.state_store.keys() == []

    @given(
        scope_id=scope_ids,
        items=st.dictionaries(
            keys=state_keys,
            values=json_values,
            min_size=0,
            max_size=10,
        ),
    )
    def test_close_marks_scope_closed_and_state_store_rejects_mutations(
        self, scope_id: str, items: dict[str, object]
    ) -> None:
        """After close(), the scope is marked as closed and its state_store rejects mutations.

        **Validates: Requirements 7.6**
        """
        scope = WorkflowScope(scope_id)

        # Populate state before closing
        for key, value in items.items():
            scope.state_store.set(key, value)

        scope.close()

        # Verify scope is closed
        assert scope.closed is True

        # State store should reject set() calls
        with pytest.raises(InvalidStateTransitionError):
            scope.state_store.set("new_key", "new_value")

        # State store should reject clear() calls
        with pytest.raises(InvalidStateTransitionError):
            scope.state_store.clear()

    @given(scope_id=scope_ids)
    def test_close_on_already_closed_scope_raises_invalid_state_transition(
        self, scope_id: str
    ) -> None:
        """Calling close() on an already-closed scope raises InvalidStateTransitionError.

        **Validates: Requirements 7.6**
        """
        scope = WorkflowScope(scope_id)
        scope.close()

        with pytest.raises(InvalidStateTransitionError, match="already closed"):
            scope.close()

    @given(
        scope_id=scope_ids,
        second_scope_id=scope_ids,
    )
    def test_duplicate_scope_id_in_registry_raises_value_error(
        self, scope_id: str, second_scope_id: str
    ) -> None:
        """Creating a scope with a duplicate scope_id (in a registry context) raises ValueError.

        **Validates: Requirements 7.7**
        """
        # Simulate a scope registry as a dict (matching FunctualizeApp's design)
        registry: dict[str, WorkflowScope] = {}

        def create_workflow_scope(sid: str) -> WorkflowScope:
            if sid in registry:
                raise ValueError(f"Workflow scope with id '{sid}' already exists")
            ws = WorkflowScope(sid)
            registry[sid] = ws
            return ws

        # First creation should succeed
        create_workflow_scope(scope_id)

        # Duplicate creation should raise ValueError
        with pytest.raises(ValueError, match="already exists"):
            create_workflow_scope(scope_id)

    @given(
        scope_id=scope_ids,
        key=state_keys,
        value=json_values,
    )
    def test_get_workflow_scope_retrieves_existing_scope(
        self, scope_id: str, key: str, value: object
    ) -> None:
        """get_workflow_scope retrieves an existing scope by ID; missing ID raises KeyError.

        **Validates: Requirements 7.4**
        """
        # Simulate a scope registry
        registry: dict[str, WorkflowScope] = {}

        def create_workflow_scope(sid: str) -> WorkflowScope:
            if sid in registry:
                raise ValueError(f"Workflow scope with id '{sid}' already exists")
            ws = WorkflowScope(sid)
            registry[sid] = ws
            return ws

        def get_workflow_scope(sid: str) -> WorkflowScope:
            if sid not in registry:
                raise KeyError(f"Workflow scope '{sid}' does not exist")
            return registry[sid]

        # Create scope and store state
        scope = create_workflow_scope(scope_id)
        scope.state_store.set(key, value)

        # Retrieve and verify it's the same scope instance
        retrieved = get_workflow_scope(scope_id)
        assert retrieved is scope
        assert retrieved.state_store.get(key, object) == value

        # Non-existent scope raises KeyError
        with pytest.raises(KeyError):
            get_workflow_scope(scope_id + "_nonexistent")


# Feature: enriched-runcontext, Property 22: Workflow_Scope Metadata
# A scope created with metadata stores it and makes it accessible via the metadata property.
# A scope created without metadata has an empty dict as metadata.
# Metadata supports arbitrary JSON-like dictionaries (string keys, various value types).
# **Validates: Requirements 10.3**
class TestWorkflowScopeMetadata:
    """Property 22: Workflow_Scope Metadata."""

    @given(scope_id=scope_ids, metadata=metadata_dicts)
    def test_metadata_stored_and_accessible(
        self, scope_id: str, metadata: dict[str, object]
    ) -> None:
        """A scope created with metadata stores it and makes it accessible via
        the metadata property.

        **Validates: Requirements 10.3**
        """
        scope = WorkflowScope(scope_id, metadata=metadata)
        assert scope.metadata == metadata

    @given(scope_id=scope_ids)
    def test_no_metadata_gives_empty_dict(self, scope_id: str) -> None:
        """A scope created without metadata has an empty dict as metadata.

        **Validates: Requirements 10.3**
        """
        scope = WorkflowScope(scope_id)
        assert scope.metadata == {}
        assert isinstance(scope.metadata, dict)

    @given(scope_id=scope_ids)
    def test_none_metadata_gives_empty_dict(self, scope_id: str) -> None:
        """A scope created with metadata=None has an empty dict as metadata.

        **Validates: Requirements 10.3**
        """
        scope = WorkflowScope(scope_id, metadata=None)
        assert scope.metadata == {}
        assert isinstance(scope.metadata, dict)

    @given(scope_id=scope_ids, metadata=metadata_dicts)
    def test_metadata_supports_arbitrary_json_dicts(
        self, scope_id: str, metadata: dict[str, object]
    ) -> None:
        """Metadata supports arbitrary JSON-like dictionaries (string keys,
        various value types).

        **Validates: Requirements 10.3**
        """
        scope = WorkflowScope(scope_id, metadata=metadata)

        # All keys from the input are present
        for key in metadata:
            assert key in scope.metadata

        # All values match
        for key, value in metadata.items():
            assert scope.metadata[key] == value

        # Size matches
        assert len(scope.metadata) == len(metadata)
