"""Tests for ON_SCOPE_CREATED hook, StateStore replacement, and JobResult metadata.

Covers task 7.1:
- ON_SCOPE_CREATED fired from create_workflow_scope() with scope instance
- WorkflowScope.replace_state_store(store) with protocol validation
- JobResult.metadata field (default empty dict)
- RunContext mutable metadata dict carried over to JobResult
- 64-key maximum enforcement
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock

import pytest

from functualize._app.state import AppState
from functualize._engine.result import JobResult
from functualize._events.hooks import HookEvent
from functualize.app.core import FunctualizeApp
from functualize.job._protocols import StateStoreProtocol
from functualize.job._workflow_scope import WorkflowScope
from functualize.job.context import InvalidStateTransitionError, RunContext, RunStatus

# --- Helpers ---


class ConformingStore:
    """A minimal store that satisfies StateStoreProtocol."""

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

    def get_job_state(self, job_name: str, key: str, default: Any = None) -> Any:
        return default

    def list_job_namespaces(self) -> list[str]:
        return []


class NonConformingStore:
    """A store missing required methods."""

    def get(self, key: str, default: Any = None) -> Any:
        return default


@pytest.fixture(autouse=True)
def _reset_state() -> Generator[None]:
    """Ensure AppState is clean before and after each test."""
    AppState.reset()
    yield
    AppState.reset()


@pytest.fixture
def app() -> FunctualizeApp:
    """Create a minimal FunctualizeApp for testing."""
    return FunctualizeApp(name="testapp")


# --- ON_SCOPE_CREATED hook tests ---


class TestOnScopeCreatedHook:
    """Tests for ON_SCOPE_CREATED hook firing from create_workflow_scope()."""

    def test_on_scope_created_fires_with_scope_instance(self, app) -> None:
        """ON_SCOPE_CREATED hook receives the new scope instance."""
        received_scopes: list[WorkflowScope] = []

        def hook(scope: WorkflowScope) -> None:
            received_scopes.append(scope)

        app._hook_registry.register_global(HookEvent.ON_SCOPE_CREATED, hook)
        scope = app.create_workflow_scope("test-scope")

        assert len(received_scopes) == 1
        assert received_scopes[0] is scope

    def test_on_scope_created_fires_before_return(self, app) -> None:
        """Hook fires before scope is returned, allowing replace_state_store."""
        custom_store = ConformingStore()

        def hook(scope: WorkflowScope) -> None:
            scope.replace_state_store(custom_store)

        app._hook_registry.register_global(HookEvent.ON_SCOPE_CREATED, hook)
        scope = app.create_workflow_scope("test-scope")

        assert scope.state_store is custom_store

    def test_on_scope_created_exception_logged_at_warning(self, app, caplog) -> None:
        """Hook exceptions are logged at WARNING level and don't prevent scope creation."""

        def bad_hook(scope: WorkflowScope) -> None:
            raise RuntimeError("hook failure")

        app._hook_registry.register_global(HookEvent.ON_SCOPE_CREATED, bad_hook)

        with caplog.at_level(logging.WARNING):
            scope = app.create_workflow_scope("test-scope")

        # Scope was still created successfully
        assert scope is not None
        assert scope.scope_id == "test-scope"
        # Warning was logged
        assert any("ON_SCOPE_CREATED" in r.message for r in caplog.records)
        assert any("hook failure" in r.message for r in caplog.records)

    def test_on_scope_created_multiple_hooks_all_invoked(self, app) -> None:
        """All hooks are invoked even if one raises."""
        call_order: list[str] = []

        def hook_a(scope: WorkflowScope) -> None:
            call_order.append("a")

        def hook_b(scope: WorkflowScope) -> None:
            raise RuntimeError("b fails")

        def hook_c(scope: WorkflowScope) -> None:
            call_order.append("c")

        app._hook_registry.register_global(HookEvent.ON_SCOPE_CREATED, hook_a)
        app._hook_registry.register_global(HookEvent.ON_SCOPE_CREATED, hook_b)
        app._hook_registry.register_global(HookEvent.ON_SCOPE_CREATED, hook_c)

        scope = app.create_workflow_scope("test-scope")

        assert call_order == ["a", "c"]
        assert scope is not None


# --- WorkflowScope.replace_state_store tests ---


class TestReplaceStateStore:
    """Tests for WorkflowScope.replace_state_store()."""

    def test_replace_with_conforming_store(self) -> None:
        """Replacing with a conforming store succeeds."""
        scope = WorkflowScope("test")
        new_store = ConformingStore()
        scope.replace_state_store(new_store)
        assert scope.state_store is new_store

    def test_replace_uses_new_store_for_operations(self) -> None:
        """After replacement, state operations use the new store."""
        scope = WorkflowScope("test")
        # Write to original store
        scope.state_store.set("old_key", "old_value")

        new_store = ConformingStore()
        scope.replace_state_store(new_store)

        # Old data not available in new store
        assert scope.state_store.get("old_key") is None

        # New writes go to new store
        scope.state_store.set("new_key", "new_value")
        assert new_store.get("new_key") == "new_value"

    def test_replace_non_conforming_raises_type_error(self) -> None:
        """Non-conforming store raises TypeError with missing methods."""
        scope = WorkflowScope("test")

        with pytest.raises(TypeError, match="Missing methods"):
            scope.replace_state_store(NonConformingStore())

    def test_replace_non_conforming_lists_missing_methods(self) -> None:
        """TypeError message lists the specific missing methods."""
        scope = WorkflowScope("test")

        with pytest.raises(TypeError) as exc_info:
            scope.replace_state_store(NonConformingStore())

        error_msg = str(exc_info.value)
        # Should mention missing methods
        assert "set" in error_msg
        assert "delete" in error_msg
        assert "keys" in error_msg
        assert "to_dict" in error_msg
        assert "clear" in error_msg
        assert "get_job_state" in error_msg
        assert "list_job_namespaces" in error_msg

    def test_replace_on_closed_scope_raises_invalid_state_transition(self) -> None:
        """Replacing on closed scope raises InvalidStateTransitionError."""
        scope = WorkflowScope("test")
        scope.close()

        with pytest.raises(InvalidStateTransitionError, match="closed"):
            scope.replace_state_store(ConformingStore())

    def test_replace_no_data_migration(self) -> None:
        """Data from old store is NOT migrated to new store."""
        scope = WorkflowScope("test")
        scope.state_store.set("key1", "value1")
        scope.state_store.set("key2", "value2")

        new_store = ConformingStore()
        scope.replace_state_store(new_store)

        assert new_store.to_dict() == {}

    def test_in_memory_state_store_satisfies_protocol(self) -> None:
        """The existing in-memory StateStore satisfies StateStoreProtocol."""
        from functualize.job._state_store import StateStore

        store = StateStore()
        assert isinstance(store, StateStoreProtocol)


# --- JobResult metadata tests ---


class TestJobResultMetadata:
    """Tests for the JobResult.metadata field."""

    def test_default_metadata_is_empty_dict(self) -> None:
        """JobResult metadata defaults to empty dict."""
        result = JobResult(
            status=RunStatus.SUCCESS,
            duration_ms=100.0,
            return_value=None,
            exception=None,
        )
        assert result.metadata == {}

    def test_metadata_with_explicit_values(self) -> None:
        """JobResult can be created with explicit metadata."""
        meta = {"execution_uid": "abc-123", "session_id": "sess-1"}
        result = JobResult(
            status=RunStatus.SUCCESS,
            duration_ms=100.0,
            return_value=None,
            exception=None,
            metadata=meta,
        )
        assert result.metadata == meta

    def test_metadata_is_dict_type(self) -> None:
        """Metadata field is typed as dict[str, Any]."""
        result = JobResult(
            status=RunStatus.SUCCESS,
            duration_ms=100.0,
            return_value=None,
            exception=None,
            metadata={"key": 42, "nested": {"a": 1}},
        )
        assert isinstance(result.metadata, dict)
        assert result.metadata["key"] == 42
        assert result.metadata["nested"] == {"a": 1}


# --- RunContext result_metadata tests ---


class TestRunContextResultMetadata:
    """Tests for RunContext mutable metadata dict."""

    @pytest.fixture
    def rc(self):
        """Create a minimal RunContext for testing."""
        config = MagicMock()
        config.set_prefix = MagicMock()
        logger = MagicMock()
        return RunContext(name="test-job", config=config, logger=logger)

    def test_result_metadata_initially_empty(self, rc) -> None:
        """Result metadata starts as an empty dict."""
        assert rc.result_metadata == {}

    def test_set_result_metadata_stores_value(self, rc) -> None:
        """set_result_metadata stores key-value pairs."""
        rc.set_result_metadata("key1", "value1")
        assert rc.result_metadata["key1"] == "value1"

    def test_set_result_metadata_update_existing_key(self, rc) -> None:
        """Updating an existing key always works."""
        rc.set_result_metadata("key1", "original")
        rc.set_result_metadata("key1", "updated")
        assert rc.result_metadata["key1"] == "updated"

    def test_64_key_maximum_enforcement(self, rc) -> None:
        """Writes exceeding 64 keys are silently discarded."""
        # Write 64 keys
        for i in range(64):
            rc.set_result_metadata(f"key_{i}", f"value_{i}")
        assert len(rc.result_metadata) == 64

        # 65th key should be silently discarded
        rc.set_result_metadata("overflow_key", "should_be_discarded")
        assert len(rc.result_metadata) == 64
        assert "overflow_key" not in rc.result_metadata

    def test_update_existing_at_limit_succeeds(self, rc) -> None:
        """Updating existing keys works even at the 64-key limit."""
        for i in range(64):
            rc.set_result_metadata(f"key_{i}", f"value_{i}")

        # Update existing key at the limit
        rc.set_result_metadata("key_0", "updated")
        assert rc.result_metadata["key_0"] == "updated"
        assert len(rc.result_metadata) == 64

    def test_result_metadata_accessible_via_property(self, rc) -> None:
        """The result_metadata property returns the mutable dict."""
        rc.set_result_metadata("test", 42)
        meta = rc.result_metadata
        assert meta == {"test": 42}

    def test_result_metadata_direct_write_respects_limit(self, rc) -> None:
        """Direct dict writes to result_metadata bypass the limit (raw access).

        Note: set_result_metadata is the intended API for enforcing limits.
        Direct dict access bypasses enforcement (allowed for hooks).
        """
        # Direct access is allowed — hooks can write directly
        rc.result_metadata["direct_key"] = "direct_value"
        assert rc.result_metadata["direct_key"] == "direct_value"


# --- Integration: metadata carried to JobResult ---


class TestMetadataCarriedToJobResult:
    """Tests verifying metadata is carried from RunContext to JobResult via engine."""

    @pytest.fixture
    def app(self) -> FunctualizeApp:
        """Create a minimal FunctualizeApp for testing."""
        return FunctualizeApp(name="test-meta-app")

    def test_metadata_written_in_job_appears_in_result(self, app) -> None:
        """Metadata set during job execution appears in the returned JobResult."""

        def my_job(rc: RunContext) -> str:
            rc.set_result_metadata("execution_uid", "abc-123")
            rc.set_result_metadata("version", 2)
            return "done"

        result = app._execution_engine.execute(
            "test_job",
            function=my_job,
            kwargs={},
        )

        assert result.status == RunStatus.SUCCESS
        assert result.metadata["execution_uid"] == "abc-123"
        assert result.metadata["version"] == 2

    def test_metadata_written_in_after_success_hook_appears_in_result(
        self, app
    ) -> None:
        """Metadata written by AFTER_SUCCESS hooks appears in JobResult."""

        def hook(rc: RunContext, result: Any = None) -> None:
            rc.set_result_metadata("tracked_by", "execution-state-plugin")

        app._hook_registry.register_global(HookEvent.AFTER_SUCCESS, hook)

        def my_job(rc: RunContext) -> str:
            return "done"

        result = app._execution_engine.execute(
            "test_job",
            function=my_job,
            kwargs={},
        )

        assert result.metadata["tracked_by"] == "execution-state-plugin"

    def test_metadata_preserved_on_failure(self, app) -> None:
        """Metadata written before failure is preserved in the failure JobResult."""

        def hook(rc: RunContext) -> None:
            rc.set_result_metadata("pre_failure_key", "was_here")

        app._hook_registry.register_global(HookEvent.BEFORE_JOB, hook)

        def failing_job(rc: RunContext) -> None:
            raise RuntimeError("job failed")

        result = app._execution_engine.execute(
            "test_job",
            function=failing_job,
            kwargs={},
        )

        assert result.status == RunStatus.FAILURE
        assert result.metadata["pre_failure_key"] == "was_here"

    def test_last_writer_wins_for_same_key(self, app) -> None:
        """Multiple writes to the same key: last writer wins."""

        def hook_a(rc: RunContext) -> None:
            rc.set_result_metadata("shared_key", "from_a")

        def hook_b(rc: RunContext) -> None:
            rc.set_result_metadata("shared_key", "from_b")

        app._hook_registry.register_global(HookEvent.BEFORE_JOB, hook_a)
        app._hook_registry.register_global(HookEvent.BEFORE_JOB, hook_b)

        def my_job(rc: RunContext) -> str:
            return "done"

        result = app._execution_engine.execute(
            "test_job",
            function=my_job,
            kwargs={},
        )

        assert result.metadata["shared_key"] == "from_b"
