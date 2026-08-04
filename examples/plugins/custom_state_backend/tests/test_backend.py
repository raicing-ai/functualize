"""Tests for the custom MemoryTTLBackend state plugin."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from functualize_state import StateBackend, StateNamespace
from functualize_state_memory import MemoryTTLBackend


class TestProtocolCompliance:
    """Verify the backend satisfies the StateBackend protocol."""

    def test_is_state_backend(self):
        backend = MemoryTTLBackend()
        assert isinstance(backend, StateBackend)

    def test_has_required_methods(self):
        backend = MemoryTTLBackend()
        assert hasattr(backend, "get")
        assert hasattr(backend, "set")
        assert hasattr(backend, "delete")
        assert hasattr(backend, "keys")


class TestBasicOperations:
    """Test standard StateBackend get/set/delete/keys operations."""

    def test_set_and_get(self):
        backend = MemoryTTLBackend()
        backend.set("key1", "value1")
        assert backend.get("key1") == "value1"

    def test_get_missing_returns_default(self):
        backend = MemoryTTLBackend()
        assert backend.get("missing") is None
        assert backend.get("missing", default="fallback") == "fallback"

    def test_delete_removes_key(self):
        backend = MemoryTTLBackend()
        backend.set("key1", "value1")
        backend.delete("key1")
        assert backend.get("key1") is None

    def test_delete_nonexistent_is_noop(self):
        backend = MemoryTTLBackend()
        backend.delete("nonexistent")  # Should not raise

    def test_keys_returns_all_keys(self):
        backend = MemoryTTLBackend()
        backend.set("a", 1)
        backend.set("b", 2)
        backend.set("c", 3)
        assert sorted(backend.keys()) == ["a", "b", "c"]

    def test_keys_with_prefix(self):
        backend = MemoryTTLBackend()
        backend.set("user:alice", "data")
        backend.set("user:bob", "data")
        backend.set("config:theme", "dark")

        assert sorted(backend.keys(prefix="user:")) == ["user:alice", "user:bob"]
        assert backend.keys(prefix="config:") == ["config:theme"]
        assert backend.keys(prefix="missing:") == []


class TestTTLBehavior:
    """Test TTL expiration — the custom feature of this backend."""

    def test_key_expires_after_ttl(self):
        backend = MemoryTTLBackend(default_ttl=0.01)  # 10ms TTL
        backend.set("ephemeral", "data")

        # Key should exist immediately
        assert backend.get("ephemeral") == "data"

        # Wait for expiration
        time.sleep(0.02)

        # Key should be gone
        assert backend.get("ephemeral") is None

    def test_no_ttl_means_no_expiry(self):
        backend = MemoryTTLBackend(default_ttl=None)
        backend.set("permanent", "data")
        # Key persists indefinitely (no sleep needed to verify)
        assert backend.get("permanent") == "data"

    def test_per_key_ttl_override(self):
        backend = MemoryTTLBackend(default_ttl=60)  # 60s default
        backend.set("short", "data", ttl=0.01)  # 10ms override

        time.sleep(0.02)
        assert backend.get("short") is None

    def test_expired_keys_excluded_from_keys_list(self):
        backend = MemoryTTLBackend(default_ttl=0.01)
        backend.set("temp1", "a")
        backend.set("temp2", "b")

        time.sleep(0.02)
        assert backend.keys() == []

    def test_size_reflects_active_keys(self):
        backend = MemoryTTLBackend(default_ttl=0.01)
        backend.set("a", 1)
        backend.set("b", 2)

        assert backend.size == 2
        time.sleep(0.02)
        assert backend.size == 0


class TestWithStateNamespace:
    """Test that the backend works with StateNamespace (prefix isolation)."""

    def test_namespace_isolation(self):
        backend = MemoryTTLBackend()
        ns_a = StateNamespace(backend, prefix="a:")
        ns_b = StateNamespace(backend, prefix="b:")

        ns_a.set("key", "value_a")
        ns_b.set("key", "value_b")

        assert ns_a.get("key") == "value_a"
        assert ns_b.get("key") == "value_b"

    def test_namespace_keys_are_scoped(self):
        backend = MemoryTTLBackend()
        ns = StateNamespace(backend, prefix="test:")

        ns.set("one", 1)
        ns.set("two", 2)
        backend.set("other", 3)

        assert sorted(ns.keys()) == ["one", "two"]
