"""Tests for AI graceful degradation when State domain is absent or fails.

Validates Requirements 25.1, 25.2, 25.3:
- 25.1: Fall back to in-memory ScopeStore when State domain not installed
- 25.2: Emit boot-time warning about ephemeral data
- 25.3: When State domain IS installed but fails at runtime, fail entirely
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from functualize_ai._state_fallback import (
    EphemeralStateBackend,
    StrictStateBackendWrapper,
    resolve_ai_state_backend,
)

# ---------------------------------------------------------------------------
# Tests: EphemeralStateBackend
# ---------------------------------------------------------------------------


class TestEphemeralStateBackend:
    """EphemeralStateBackend provides a basic in-memory key-value store."""

    def test_get_returns_default_for_missing_key(self) -> None:
        backend = EphemeralStateBackend()
        assert backend.get("missing") is None
        assert backend.get("missing", 42) == 42

    def test_set_and_get_roundtrip(self) -> None:
        backend = EphemeralStateBackend()
        backend.set("key1", "value1")
        assert backend.get("key1") == "value1"

    def test_set_overwrites_existing(self) -> None:
        backend = EphemeralStateBackend()
        backend.set("key", "old")
        backend.set("key", "new")
        assert backend.get("key") == "new"

    def test_delete_removes_key(self) -> None:
        backend = EphemeralStateBackend()
        backend.set("key", "value")
        backend.delete("key")
        assert backend.get("key") is None

    def test_delete_nonexistent_is_noop(self) -> None:
        backend = EphemeralStateBackend()
        backend.delete("nonexistent")  # Should not raise

    def test_keys_empty(self) -> None:
        backend = EphemeralStateBackend()
        assert backend.keys() == []

    def test_keys_returns_all_keys(self) -> None:
        backend = EphemeralStateBackend()
        backend.set("a", 1)
        backend.set("b", 2)
        assert sorted(backend.keys()) == ["a", "b"]

    def test_keys_with_prefix_filter(self) -> None:
        backend = EphemeralStateBackend()
        backend.set("ai:budget", 10.0)
        backend.set("ai:checkpoint", "data")
        backend.set("tasks:list", [])
        assert sorted(backend.keys("ai:")) == ["ai:budget", "ai:checkpoint"]

    def test_keys_with_empty_prefix_returns_all(self) -> None:
        backend = EphemeralStateBackend()
        backend.set("a", 1)
        backend.set("b", 2)
        assert sorted(backend.keys("")) == ["a", "b"]


# ---------------------------------------------------------------------------
# Tests: StrictStateBackendWrapper
# ---------------------------------------------------------------------------


class TestStrictStateBackendWrapper:
    """StrictStateBackendWrapper delegates to real backend and propagates errors."""

    def test_get_delegates(self) -> None:
        mock_backend = MagicMock()
        mock_backend.get.return_value = "result"
        wrapper = StrictStateBackendWrapper(mock_backend)
        assert wrapper.get("key", "default") == "result"
        mock_backend.get.assert_called_once_with("key", "default")

    def test_set_delegates(self) -> None:
        mock_backend = MagicMock()
        wrapper = StrictStateBackendWrapper(mock_backend)
        wrapper.set("key", "value")
        mock_backend.set.assert_called_once_with("key", "value")

    def test_delete_delegates(self) -> None:
        mock_backend = MagicMock()
        wrapper = StrictStateBackendWrapper(mock_backend)
        wrapper.delete("key")
        mock_backend.delete.assert_called_once_with("key")

    def test_keys_delegates(self) -> None:
        mock_backend = MagicMock()
        mock_backend.keys.return_value = ["ai:budget"]
        wrapper = StrictStateBackendWrapper(mock_backend)
        assert wrapper.keys("ai:") == ["ai:budget"]
        mock_backend.keys.assert_called_once_with("ai:")

    def test_get_propagates_runtime_error(self) -> None:
        """Requirement 25.3: Runtime errors from real backend are NOT swallowed."""
        mock_backend = MagicMock()
        mock_backend.get.side_effect = OSError("SQLite disk I/O error")
        wrapper = StrictStateBackendWrapper(mock_backend)
        with pytest.raises(OSError, match="SQLite disk I/O error"):
            wrapper.get("key")

    def test_set_propagates_runtime_error(self) -> None:
        """Requirement 25.3: Runtime errors from real backend are NOT swallowed."""
        mock_backend = MagicMock()
        mock_backend.set.side_effect = OSError("database is locked")
        wrapper = StrictStateBackendWrapper(mock_backend)
        with pytest.raises(OSError, match="database is locked"):
            wrapper.set("key", "value")

    def test_delete_propagates_runtime_error(self) -> None:
        mock_backend = MagicMock()
        mock_backend.delete.side_effect = RuntimeError("connection lost")
        wrapper = StrictStateBackendWrapper(mock_backend)
        with pytest.raises(RuntimeError, match="connection lost"):
            wrapper.delete("key")

    def test_keys_propagates_runtime_error(self) -> None:
        mock_backend = MagicMock()
        mock_backend.keys.side_effect = OSError("corruption detected")
        wrapper = StrictStateBackendWrapper(mock_backend)
        with pytest.raises(OSError, match="corruption detected"):
            wrapper.keys("ai:")


# ---------------------------------------------------------------------------
# Tests: resolve_ai_state_backend
# ---------------------------------------------------------------------------


class TestResolveAiStateBackend:
    """Tests for the resolve_ai_state_backend function."""

    def test_returns_ephemeral_when_no_backend_provided(self) -> None:
        """Requirement 25.1: Falls back to in-memory when State domain absent."""
        result = resolve_ai_state_backend(state_backend=None)
        assert isinstance(result, EphemeralStateBackend)

    def test_emits_warning_when_falling_back(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Requirement 25.2: Boot-time warning about ephemeral data."""
        with caplog.at_level(logging.WARNING, logger="functualize_ai._state_fallback"):
            resolve_ai_state_backend(state_backend=None)
        assert any("ephemeral" in record.message.lower() for record in caplog.records)
        assert any(
            "functualize-state-sqlite" in record.message for record in caplog.records
        )

    def test_returns_strict_wrapper_when_backend_provided(self) -> None:
        """Requirement 25.3: Wraps real backend strictly (no silent fallback)."""
        mock_backend = MagicMock()
        result = resolve_ai_state_backend(state_backend=mock_backend)
        assert isinstance(result, StrictStateBackendWrapper)

    def test_no_warning_when_backend_provided(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No ephemeral warning when State domain IS installed."""
        mock_backend = MagicMock()
        with caplog.at_level(logging.WARNING, logger="functualize_ai._state_fallback"):
            resolve_ai_state_backend(state_backend=mock_backend)
        assert not any(
            "ephemeral" in record.message.lower() for record in caplog.records
        )

    def test_ephemeral_backend_is_functional(self) -> None:
        """The fallback ephemeral backend actually stores and retrieves data."""
        backend = resolve_ai_state_backend(state_backend=None)
        backend.set("ai:budget_spent", 1.5)
        assert backend.get("ai:budget_spent") == 1.5

    def test_strict_wrapper_delegates_correctly(self) -> None:
        """The strict wrapper properly delegates operations."""
        mock_backend = MagicMock()
        mock_backend.get.return_value = 2.5
        wrapper = resolve_ai_state_backend(state_backend=mock_backend)
        result = wrapper.get("ai:budget_spent", 0.0)
        assert result == 2.5
        mock_backend.get.assert_called_once_with("ai:budget_spent", 0.0)


# ---------------------------------------------------------------------------
# Tests: Integration with StateNamespace
# ---------------------------------------------------------------------------


class TestTheStateDomainProbeIsGone:
    """`store-substrate`/T6.

    Three tests here checked that the fallback backends compose with
    `StateNamespace` from `functualize-state`. That package is retired — a
    backend-agnostic key-value protocol can only offer the intersection of
    every backend, which is worth least exactly where a database is worth most
    (`contributor/adr/022`) — so the collaborator they integrated with does not
    exist. They are deleted rather than rewritten against a stand-in, which
    would have asserted that the fallback works with something nothing uses.

    What is still worth pinning is that the *probe* went with it: a function
    that asked whether a deleted package was importable would answer "no"
    forever, and the AI plugin would silently use ephemeral storage on every
    install.
    """

    def test_there_is_no_domain_availability_probe(self) -> None:
        import functualize_ai._state_fallback as module

        assert not hasattr(module, "is_state_domain_available")

