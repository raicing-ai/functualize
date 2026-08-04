"""Unit tests for RunContext subscript access (rc[Type], rc[Type, 'q'], rc['name']).

Tests the __getitem__ and __contains__ dunder methods added to support
DI-style resolution through the RunContext facade.
"""

import logging
from unittest.mock import MagicMock

import pytest

from functualize._config.job_config import JobConfigView
from functualize._primitives.di import DIRegistry, MissingProviderError
from functualize.job.context import RunContext


@pytest.fixture
def mock_config():
    """Create a mock JobConfigView instance."""
    config = MagicMock(spec=JobConfigView)
    return config


@pytest.fixture
def mock_logger():
    """Create a mock Logger instance."""
    return MagicMock(spec=logging.Logger)


@pytest.fixture
def registry():
    """Create a fresh DIRegistry for testing."""
    return DIRegistry()


@pytest.fixture
def rc_with_registry(mock_config, mock_logger, registry):
    """Create a RunContext with an attached DIRegistry."""
    return RunContext(
        name="test-job",
        config=mock_config,
        logger=mock_logger,
        _di_registry=registry,
    )


@pytest.fixture
def rc_without_registry(mock_config, mock_logger):
    """Create a RunContext without a DIRegistry (backward-compatible)."""
    return RunContext(
        name="test-job",
        config=mock_config,
        logger=mock_logger,
    )


# --- Sample types for DI testing ---


class CacheService:
    """Sample capability type."""

    def __init__(self, backend: str = "memory"):
        self.backend = backend


class DatabaseService:
    """Another sample capability type."""

    def __init__(self, url: str = "sqlite://"):
        self.url = url


# --- __getitem__ tests ---


class TestGetItemTypeResolution:
    """Tests for rc[Type] — unqualified type lookup."""

    def test_resolve_registered_type(self, rc_with_registry, registry):
        cache = CacheService("redis")
        registry.provide(CacheService, cache)
        assert rc_with_registry[CacheService] is cache

    def test_resolve_returns_same_instance(self, rc_with_registry, registry):
        cache = CacheService()
        registry.provide(CacheService, cache)
        assert rc_with_registry[CacheService] is rc_with_registry[CacheService]

    def test_resolve_unregistered_type_raises(self, rc_with_registry):
        with pytest.raises(MissingProviderError):
            rc_with_registry[CacheService]

    def test_resolve_multiple_types(self, rc_with_registry, registry):
        cache = CacheService()
        db = DatabaseService("postgres://localhost")
        registry.provide(CacheService, cache)
        registry.provide(DatabaseService, db)
        assert rc_with_registry[CacheService] is cache
        assert rc_with_registry[DatabaseService] is db


class TestGetItemQualifiedResolution:
    """Tests for rc[Type, 'qualifier'] — qualified type lookup."""

    def test_resolve_qualified_type(self, rc_with_registry, registry):
        redis_cache = CacheService("redis")
        registry.provide(CacheService, redis_cache, qualifier="redis")
        assert rc_with_registry[CacheService, "redis"] is redis_cache

    def test_resolve_different_qualifiers(self, rc_with_registry, registry):
        redis_cache = CacheService("redis")
        memcached = CacheService("memcached")
        registry.provide(CacheService, redis_cache, qualifier="redis")
        registry.provide(CacheService, memcached, qualifier="memcached")
        assert rc_with_registry[CacheService, "redis"] is redis_cache
        assert rc_with_registry[CacheService, "memcached"] is memcached

    def test_resolve_missing_qualifier_raises(self, rc_with_registry, registry):
        registry.provide(CacheService, CacheService("redis"), qualifier="redis")
        with pytest.raises(MissingProviderError):
            rc_with_registry[CacheService, "nonexistent"]


class TestGetItemNamedResolution:
    """Tests for rc['name'] — named string lookup."""

    def test_resolve_named_value(self, rc_with_registry, registry):
        registry.provide_named("app_version", "1.2.3")
        assert rc_with_registry["app_version"] == "1.2.3"

    def test_resolve_named_complex_value(self, rc_with_registry, registry):
        config = {"host": "localhost", "port": 8080}
        registry.provide_named("server_config", config)
        assert rc_with_registry["server_config"] is config

    def test_resolve_missing_named_raises(self, rc_with_registry):
        with pytest.raises(MissingProviderError):
            rc_with_registry["nonexistent"]


class TestGetItemNoRegistry:
    """Tests for subscript access without a DI registry attached."""

    def test_type_access_raises_runtime_error(self, rc_without_registry):
        with pytest.raises(RuntimeError, match="no DI registry"):
            rc_without_registry[CacheService]

    def test_qualified_access_raises_runtime_error(self, rc_without_registry):
        with pytest.raises(RuntimeError, match="no DI registry"):
            rc_without_registry[CacheService, "redis"]

    def test_named_access_raises_runtime_error(self, rc_without_registry):
        with pytest.raises(RuntimeError, match="no DI registry"):
            rc_without_registry["some_name"]


# --- __contains__ tests ---


class TestContainsType:
    """Tests for Type in rc — type containment check."""

    def test_registered_type_returns_true(self, rc_with_registry, registry):
        registry.provide(CacheService, CacheService())
        assert CacheService in rc_with_registry

    def test_unregistered_type_returns_false(self, rc_with_registry):
        assert CacheService not in rc_with_registry

    def test_qualified_type_still_detected(self, rc_with_registry, registry):
        registry.provide(CacheService, CacheService(), qualifier="redis")
        assert CacheService in rc_with_registry


class TestContainsNamed:
    """Tests for 'name' in rc — named containment check."""

    def test_registered_name_returns_true(self, rc_with_registry, registry):
        registry.provide_named("app_version", "1.0.0")
        assert "app_version" in rc_with_registry

    def test_unregistered_name_returns_false(self, rc_with_registry):
        assert "nonexistent" not in rc_with_registry


class TestContainsNoRegistry:
    """Tests for containment when no registry is attached."""

    def test_type_returns_false(self, rc_without_registry):
        assert CacheService not in rc_without_registry

    def test_name_returns_false(self, rc_without_registry):
        assert "anything" not in rc_without_registry


# --- Backward compatibility ---


class TestBackwardCompatibility:
    """Tests ensuring existing methods still work without a DI registry."""

    def test_log_works_without_registry(self, rc_without_registry, mock_logger):
        rc_without_registry.log("hello", level="info")
        mock_logger.info.assert_called_once_with("hello")

    def test_run_status_works_without_registry(self, rc_without_registry):
        from functualize._types.enums import RunStatus

        assert rc_without_registry.run_status == RunStatus.RUNNING

    def test_init_without_di_registry_param(self, mock_config, mock_logger):
        """Verify RunContext can still be created without _di_registry."""
        rc = RunContext(name="test", config=mock_config, logger=mock_logger)
        assert rc._di_registry is None
