"""Property-based tests for AI domain state namespacing.

Tests Property 31 from the Phase 2–5 Domain SDKs design document.

Property 31: AI domain state namespacing — For any key k and value v, when
the AI domain writes via StateNamespace("ai:", backend), the underlying backend
stores under "ai:" + k. Keys from the "ai:" namespace are isolated from other
prefixes.

**Validates: Requirements 26.1, 26.3**
"""

from __future__ import annotations

from typing import Any

from functualize_ai._state_fallback import EphemeralStateBackend
from functualize_state import InMemoryState, StateNamespace
from hypothesis import given, settings
from hypothesis import strategies as st

# --- Strategies ---

# Strategy for valid state keys (non-empty, no colon prefix to avoid prefix collisions)
state_keys = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S"),
        blacklist_characters=":",
    ),
    min_size=1,
    max_size=50,
)

# Strategy for JSON-like values suitable for state storage
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
    min_size=1,
    max_size=10,
)


# --- Property 31: AI domain state namespacing ---


class TestAIDomainWritesWithAIPrefix:
    """Property 31a: AI domain writes via StateNamespace("ai:", backend) store
    under "ai:" + k in the underlying backend.

    **Validates: Requirements 26.1, 26.3**
    """

    @given(key=state_keys, value=json_values)
    @settings(max_examples=200)
    def test_ai_namespace_set_stores_at_ai_prefixed_key(
        self, key: str, value: Any
    ) -> None:
        """When the AI domain writes via StateNamespace("ai:", backend),
        the underlying backend stores under "ai:" + k.

        **Validates: Requirements 26.1, 26.3**
        """
        backend = InMemoryState()
        ai_ns = StateNamespace(backend, "ai:")

        ai_ns.set(key, value)

        # The underlying backend should have the key stored as "ai:" + key
        assert backend.get("ai:" + key) == value

    @given(key=state_keys, value=json_values)
    @settings(max_examples=200)
    def test_ai_namespace_get_retrieves_from_ai_prefixed_key(
        self, key: str, value: Any
    ) -> None:
        """When the AI domain reads via StateNamespace("ai:", backend),
        it retrieves from "ai:" + k in the underlying backend.

        **Validates: Requirements 26.1, 26.3**
        """
        backend = InMemoryState()
        ai_ns = StateNamespace(backend, "ai:")

        # Store directly in backend at "ai:" + key
        backend.set("ai:" + key, value)

        # Reading through the namespace should return the same value
        assert ai_ns.get(key) == value

    @given(key=state_keys, value=json_values)
    @settings(max_examples=200)
    def test_ai_namespace_roundtrip_with_ephemeral_backend(
        self, key: str, value: Any
    ) -> None:
        """StateNamespace("ai:", EphemeralStateBackend) also stores under
        "ai:" + k — verifying the fallback backend works the same way.

        **Validates: Requirements 26.1, 26.3**
        """
        backend = EphemeralStateBackend()
        ai_ns = StateNamespace(backend, "ai:")

        ai_ns.set(key, value)

        # The underlying EphemeralStateBackend should have "ai:" + key
        assert backend.get("ai:" + key) == value
        # And reading through the namespace returns the same value
        assert ai_ns.get(key) == value


class TestAINamespaceIsolationFromOtherPrefixes:
    """Property 31b: Keys from the "ai:" namespace are isolated from other prefixes.
    Different namespaces don't interfere with each other.

    **Validates: Requirements 26.1, 26.3**
    """

    @given(
        ai_entries=state_entries,
        tasks_entries=state_entries,
    )
    @settings(max_examples=200)
    def test_ai_namespace_isolated_from_tasks_namespace(
        self,
        ai_entries: dict[str, Any],
        tasks_entries: dict[str, Any],
    ) -> None:
        """Writing to "ai:" namespace does not affect "tasks:" namespace and
        vice versa.

        **Validates: Requirements 26.1, 26.3**
        """
        backend = InMemoryState()
        ai_ns = StateNamespace(backend, "ai:")
        tasks_ns = StateNamespace(backend, "tasks:")

        # Write to both namespaces
        for k, v in ai_entries.items():
            ai_ns.set(k, v)
        for k, v in tasks_entries.items():
            tasks_ns.set(k, v)

        # AI namespace sees only its own keys
        ai_keys = sorted(ai_ns.keys())
        assert ai_keys == sorted(ai_entries.keys())

        # Tasks namespace sees only its own keys
        tasks_keys = sorted(tasks_ns.keys())
        assert tasks_keys == sorted(tasks_entries.keys())

    @given(
        ai_entries=state_entries,
        user_entries=state_entries,
    )
    @settings(max_examples=200)
    def test_ai_namespace_isolated_from_unprefixed_user_state(
        self,
        ai_entries: dict[str, Any],
        user_entries: dict[str, Any],
    ) -> None:
        """Writing to "ai:" namespace does not affect unprefixed user state
        (rc.state.set(key, value) writes to general namespace without prefix).

        **Validates: Requirements 26.1, 26.3**
        """
        backend = InMemoryState()
        ai_ns = StateNamespace(backend, "ai:")

        # Write AI domain state
        for k, v in ai_entries.items():
            ai_ns.set(k, v)

        # Write user state directly (no prefix, simulating rc.state.set)
        for k, v in user_entries.items():
            backend.set(k, v)

        # AI namespace only sees its own keys
        ai_keys = sorted(ai_ns.keys())
        assert ai_keys == sorted(ai_entries.keys())

        # User keys are accessible directly from backend
        for k, v in user_entries.items():
            assert backend.get(k) == v

    @given(key=state_keys, ai_value=json_values, tasks_value=json_values)
    @settings(max_examples=200)
    def test_same_key_name_different_namespaces_no_collision(
        self, key: str, ai_value: Any, tasks_value: Any
    ) -> None:
        """The same logical key name can be used in both "ai:" and "tasks:"
        namespaces without collision.

        **Validates: Requirements 26.1, 26.3**
        """
        backend = InMemoryState()
        ai_ns = StateNamespace(backend, "ai:")
        tasks_ns = StateNamespace(backend, "tasks:")

        # Both namespaces use the same key name
        ai_ns.set(key, ai_value)
        tasks_ns.set(key, tasks_value)

        # Each namespace reads its own value
        assert ai_ns.get(key) == ai_value
        assert tasks_ns.get(key) == tasks_value

        # The underlying backend stores them with distinct prefixed keys
        assert backend.get("ai:" + key) == ai_value
        assert backend.get("tasks:" + key) == tasks_value

    @given(
        ai_entries=state_entries,
        tasks_entries=state_entries,
    )
    @settings(max_examples=200)
    def test_deleting_from_ai_namespace_does_not_affect_tasks(
        self,
        ai_entries: dict[str, Any],
        tasks_entries: dict[str, Any],
    ) -> None:
        """Deleting keys from "ai:" namespace does not affect "tasks:" namespace.

        **Validates: Requirements 26.1, 26.3**
        """
        backend = InMemoryState()
        ai_ns = StateNamespace(backend, "ai:")
        tasks_ns = StateNamespace(backend, "tasks:")

        # Write to both namespaces
        for k, v in ai_entries.items():
            ai_ns.set(k, v)
        for k, v in tasks_entries.items():
            tasks_ns.set(k, v)

        # Delete all AI keys
        for k in ai_entries:
            ai_ns.delete(k)

        # AI namespace is now empty
        assert ai_ns.keys() == []

        # Tasks namespace is unaffected
        assert sorted(tasks_ns.keys()) == sorted(tasks_entries.keys())
        for k, v in tasks_entries.items():
            assert tasks_ns.get(k) == v

    @given(key=state_keys, value=json_values)
    @settings(max_examples=200)
    def test_ai_budget_key_pattern_isolated(self, key: str, value: Any) -> None:
        """The AI budget tracking key (budget_spent) stored via "ai:" namespace
        is isolated from other prefixes — demonstrating the real usage pattern.

        **Validates: Requirements 26.1, 26.3**
        """
        backend = InMemoryState()
        ai_ns = StateNamespace(backend, "ai:")
        tasks_ns = StateNamespace(backend, "tasks:")

        # Simulate AI budget tracking
        ai_ns.set("budget_spent", 1.5)

        # Writing a "budget_spent" key in tasks namespace doesn't collide
        tasks_ns.set("budget_spent", value)

        # Each sees its own value
        assert ai_ns.get("budget_spent") == 1.5
        assert tasks_ns.get("budget_spent") == value

        # The underlying backend stores them separately
        assert backend.get("ai:budget_spent") == 1.5
        assert backend.get("tasks:budget_spent") == value
