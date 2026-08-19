"""Property-based tests for StateStore scope determines visibility.

Property 10: State_Store Scope Determines Visibility
**Validates: Requirements 6.3, 6.4**

Verifies that:
- When two references share the same StateStore (via WorkflowScope),
  state written by one is visible to the other.
- When each reference has its own independent StateStore (standalone),
  state does not leak between separate instances.
- State persistence through a shared scope: store → retrieve cycle works
  across multiple access points.
"""

from hypothesis import given
from hypothesis import strategies as st

from functualize.job._state_store import StateStore
from functualize.job._workflow_scope import WorkflowScope

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

# Strategy for scope IDs
scope_ids = st.text(
    alphabet=st.characters(categories=("L", "N", "Pd", "Pc")),
    min_size=1,
    max_size=30,
)


# Feature: enriched-runcontext, Property 10: State_Store Scope Determines Visibility
# When two access points share the same StateStore via WorkflowScope, state written
# by one is visible to the other. When standalone StateStores are used, state does
# not leak between separate instances. Store → retrieve cycle works across multiple
# access points sharing a scope.
# **Validates: Requirements 6.3, 6.4**
class TestStateStoreScopeDeterminesVisibility:
    """Property 10: State_Store Scope Determines Visibility."""

    @given(
        scope_id=scope_ids,
        items=st.dictionaries(
            keys=state_keys,
            values=json_values,
            min_size=1,
            max_size=15,
        ),
    )
    def test_shared_scope_state_visible_across_access_points(
        self, scope_id: str, items: dict[str, object]
    ) -> None:
        """When two references share the same WorkflowScope, state written by
        one is visible to the other (shared state_store reference).

        **Validates: Requirements 6.3**
        """
        scope = WorkflowScope(scope_id)
        # Two references to the same state_store through the scope
        store_ref_a = scope.state_store
        store_ref_b = scope.state_store

        # Writer A sets all items
        for key, value in items.items():
            store_ref_a.set(key, value)

        # Reader B can see all items written by A
        for key, value in items.items():
            retrieved = store_ref_b.get(key, object)
            assert retrieved == value

        # Keys are consistent across both references
        assert set(store_ref_a.keys()) == set(store_ref_b.keys())
        assert set(store_ref_b.keys()) == set(items.keys())

    @given(
        items_a=st.dictionaries(
            keys=state_keys,
            values=json_values,
            min_size=1,
            max_size=10,
        ),
        items_b=st.dictionaries(
            keys=state_keys,
            values=json_values,
            min_size=1,
            max_size=10,
        ),
    )
    def test_standalone_stores_do_not_leak_state(
        self, items_a: dict[str, object], items_b: dict[str, object]
    ) -> None:
        """When two independent StateStores are used (standalone, no shared scope),
        state does not leak between them.

        **Validates: Requirements 6.4**
        """
        store_a = StateStore()
        store_b = StateStore()

        # Write different data to each
        for key, value in items_a.items():
            store_a.set(key, value)

        for key, value in items_b.items():
            store_b.set(key, value)

        # Store A should only contain its own items
        assert set(store_a.keys()) == set(items_a.keys())
        for key, value in items_a.items():
            assert store_a.get(key, object) == value

        # Store B should only contain its own items
        assert set(store_b.keys()) == set(items_b.keys())
        for key, value in items_b.items():
            assert store_b.get(key, object) == value

        # Keys unique to A should not exist in B
        only_in_a = set(items_a.keys()) - set(items_b.keys())
        for key in only_in_a:
            assert store_b.get(key, object) is None

        # Keys unique to B should not exist in A
        only_in_b = set(items_b.keys()) - set(items_a.keys())
        for key in only_in_b:
            assert store_a.get(key, object) is None

    @given(
        scope_id=scope_ids,
        items=st.lists(
            st.tuples(state_keys, json_values),
            min_size=1,
            max_size=15,
            unique_by=lambda x: x[0],
        ),
    )
    def test_store_retrieve_cycle_across_multiple_access_points(
        self, scope_id: str, items: list[tuple[str, object]]
    ) -> None:
        """State persistence through a shared scope: store → retrieve cycle
        works across multiple access points.

        Multiple separate references to the same WorkflowScope's state_store
        all see the same consistent state after writes.

        **Validates: Requirements 6.3**
        """
        scope = WorkflowScope(scope_id)

        # Simulate multiple access points (different "job" references)
        access_points: list[StateStore] = [scope.state_store for _ in range(3)]

        # Each access point writes a portion of the items
        for i, (key, value) in enumerate(items):
            writer = access_points[i % len(access_points)]
            writer.set(key, value)

        # All access points should see all items
        for ap in access_points:
            assert set(ap.keys()) == {k for k, _ in items}
            for key, value in items:
                assert ap.get(key, object) == value

    @given(
        scope_id_a=scope_ids,
        scope_id_b=scope_ids,
        items_a=st.dictionaries(
            keys=state_keys,
            values=json_values,
            min_size=1,
            max_size=10,
        ),
        items_b=st.dictionaries(
            keys=state_keys,
            values=json_values,
            min_size=1,
            max_size=10,
        ),
    )
    def test_different_scopes_have_independent_state_stores(
        self,
        scope_id_a: str,
        scope_id_b: str,
        items_a: dict[str, object],
        items_b: dict[str, object],
    ) -> None:
        """Two different WorkflowScopes have independent state stores —
        state written in one scope is not visible in the other.

        **Validates: Requirements 6.3, 6.4**
        """
        scope_a = WorkflowScope(scope_id_a)
        scope_b = WorkflowScope(scope_id_b)

        for key, value in items_a.items():
            scope_a.state_store.set(key, value)

        for key, value in items_b.items():
            scope_b.state_store.set(key, value)

        # Scope A should only see its own state
        assert set(scope_a.state_store.keys()) == set(items_a.keys())

        # Scope B should only see its own state
        assert set(scope_b.state_store.keys()) == set(items_b.keys())

        # Keys unique to A should not appear in B's store
        only_in_a = set(items_a.keys()) - set(items_b.keys())
        for key in only_in_a:
            assert scope_b.state_store.get(key, object) is None

    @given(
        scope_id=scope_ids,
        key=state_keys,
        value_1=json_values,
        value_2=json_values,
    )
    def test_overwrite_visible_through_shared_scope(
        self, scope_id: str, key: str, value_1: object, value_2: object
    ) -> None:
        """When one access point overwrites a key, the new value is visible
        to all other access points sharing the same scope.

        **Validates: Requirements 6.3**
        """
        scope = WorkflowScope(scope_id)
        writer_a = scope.state_store
        writer_b = scope.state_store
        reader = scope.state_store

        # First writer sets initial value
        writer_a.set(key, value_1)
        assert reader.get(key, object) == value_1

        # Second writer overwrites
        writer_b.set(key, value_2)
        assert reader.get(key, object) == value_2
        # First writer also sees the overwrite
        assert writer_a.get(key, object) == value_2
