"""Unit tests for functualize-state domain SDK.

Tests the state protocols, namespace isolation, and in-memory testing backend.
"""

from __future__ import annotations

from functualize_state._namespace import StateNamespace
from functualize_state.testing._in_memory import InMemoryState


class TestInMemoryBackend:
    """Tests for the InMemoryState test double."""

    def test_get_missing_returns_default(self):
        state = InMemoryState()
        assert state.get("missing") is None
        assert state.get("missing", "default") == "default"

    def test_set_and_get(self):
        state = InMemoryState()
        state.set("key", "value")
        assert state.get("key") == "value"

    def test_delete(self):
        state = InMemoryState()
        state.set("key", "value")
        state.delete("key")
        assert state.get("key") is None


class TestStateNamespace:
    """Tests for the StateNamespace prefix isolation."""

    def test_prefixes_keys(self):
        backend = InMemoryState()
        ns = StateNamespace(backend, prefix="app.")
        ns.set("name", "functualize")
        # The key in the backend should be prefixed
        assert backend.get("app.name") == "functualize"

    def test_get_uses_prefix(self):
        backend = InMemoryState()
        backend.set("app.version", "1.0")
        ns = StateNamespace(backend, prefix="app.")
        assert ns.get("version") == "1.0"

    def test_delete_uses_prefix(self):
        backend = InMemoryState()
        backend.set("app.key", "val")
        ns = StateNamespace(backend, prefix="app.")
        ns.delete("key")
        assert backend.get("app.key") is None
