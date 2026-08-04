"""Integration tests for ExecutionStatePlugin lifecycle.

Tests the full integration flow:
1. Plugin init → hook registration → DB initialization
2. Job execution → state recorded → queryable
3. Session resume within TTL
4. Nested execution parent_uid linkage via INVOKE_START/INVOKE_END
5. Error resilience (DB write failure doesn't crash job)

Requirements: 23.1, 23.2, 23.3, 23.4, 23.8, 23.11
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from functualize_state_sqlite.plugin import ExecutionStatePlugin
from functualize_state_sqlite.sqlite_backend import SQLiteBackend
from functualize_state_sqlite.tracker import ExecutionTracker

from functualize._events.hooks import HookEvent, HookRegistry

# ─── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """Return a temp directory for the SQLite database."""
    return tmp_path


@pytest.fixture
def hook_registry() -> HookRegistry:
    """Create a fresh HookRegistry."""
    return HookRegistry()


@pytest.fixture
def mock_app(hook_registry: HookRegistry, tmp_db_path: Path) -> MagicMock:
    """Create a mock app with a real HookRegistry and config that points to tmp dir."""
    app = MagicMock()
    app.hook_registry = hook_registry

    # resolve_model returns config pointing to our tmp db
    from functualize_state_sqlite.plugin import ExecutionStateConfig

    config = ExecutionStateConfig(
        db_path=str(tmp_db_path / ".functualize" / "execution.db"),
        session_ttl=1800.0,
    )
    app.resolve_model.return_value = config
    return app


@pytest.fixture
def plugin(mock_app: MagicMock) -> ExecutionStatePlugin:
    """Create and register the plugin with the mock app."""
    p = ExecutionStatePlugin()
    p(mock_app)
    return p


@pytest.fixture
def initialized_plugin(
    plugin: ExecutionStatePlugin, mock_app: MagicMock
) -> ExecutionStatePlugin:
    """Plugin that has gone through APP_READY (DB initialized)."""
    # Fire APP_READY to initialize the backend
    hooks = mock_app.hook_registry._global_hooks.get(HookEvent.APP_READY, [])
    for hook in hooks:
        hook(mock_app)
    return plugin


def _make_rc(name: str = "test-job") -> MagicMock:
    """Create a mock RunContext with the required attributes."""
    rc = MagicMock()
    rc.name = name
    rc.duration_ms = 100.0
    rc.set_result_metadata = MagicMock()
    rc.result_metadata = {}
    return rc


# ─── Full Lifecycle Tests ─────────────────────────────────────────────


class TestFullLifecycle:
    """Test plugin init → job execution → state recorded → queryable."""

    def test_plugin_registers_all_hooks(
        self, plugin: ExecutionStatePlugin, mock_app: MagicMock
    ):
        """Plugin registration hooks into all required lifecycle events."""
        registry = mock_app.hook_registry
        expected_events = [
            HookEvent.APP_READY,
            HookEvent.BEFORE_JOB,
            HookEvent.AFTER_SUCCESS,
            HookEvent.AFTER_FAILURE,
            HookEvent.ON_TEARDOWN,
            HookEvent.INVOKE_START,
            HookEvent.INVOKE_END,
            HookEvent.ON_SCOPE_CREATED,
        ]
        for event in expected_events:
            assert event in registry._global_hooks, f"Missing hook for {event}"
            assert len(registry._global_hooks[event]) >= 1

    def test_app_ready_initializes_backend(
        self, initialized_plugin: ExecutionStatePlugin
    ):
        """APP_READY hook initializes the SQLiteBackend and ExecutionTracker."""
        assert initialized_plugin.backend is not None
        assert initialized_plugin.backend.is_initialized
        assert initialized_plugin.tracker is not None

    def test_full_execution_recorded_and_queryable(
        self, initialized_plugin: ExecutionStatePlugin, mock_app: MagicMock
    ):
        """Full lifecycle: BEFORE_JOB records start, AFTER_SUCCESS records end, queryable."""
        plugin = initialized_plugin
        registry = mock_app.hook_registry
        rc = _make_rc("my-job")

        # Simulate BEFORE_JOB
        before_hooks = registry._global_hooks[HookEvent.BEFORE_JOB]
        for hook in before_hooks:
            hook(rc, kwargs={"x": 1})

        # Verify execution was recorded
        assert plugin.tracker is not None
        assert plugin.tracker.session_id is not None

        # Get the execution_uid that was stored
        execution_uid = plugin._rc_execution_map.get(id(rc))
        assert execution_uid is not None

        # Verify the execution is in the database
        assert plugin.backend is not None
        execution = plugin.backend.get_execution(execution_uid)
        assert execution is not None
        assert execution["job_name"] == "my-job"
        assert execution["status"] == "running"
        assert execution["kwargs_json"] == '{"x": 1}'

        # Simulate AFTER_SUCCESS
        after_hooks = registry._global_hooks[HookEvent.AFTER_SUCCESS]
        for hook in after_hooks:
            hook(rc, result="success_result")

        # Verify execution is now completed
        execution = plugin.backend.get_execution(execution_uid)
        assert execution is not None
        assert execution["status"] == "success"
        assert execution["result_json"] == '"success_result"'
        assert execution["ended_at"] is not None

    def test_failed_execution_recorded(
        self, initialized_plugin: ExecutionStatePlugin, mock_app: MagicMock
    ):
        """AFTER_FAILURE records the error details."""
        plugin = initialized_plugin
        registry = mock_app.hook_registry
        rc = _make_rc("failing-job")

        # BEFORE_JOB to create the execution record
        before_hooks = registry._global_hooks[HookEvent.BEFORE_JOB]
        for hook in before_hooks:
            hook(rc)

        execution_uid = plugin._rc_execution_map.get(id(rc))
        assert execution_uid is not None

        # AFTER_FAILURE
        error = ValueError("something went wrong")
        failure_hooks = registry._global_hooks[HookEvent.AFTER_FAILURE]
        for hook in failure_hooks:
            hook(rc, error)

        # Verify error was recorded
        assert plugin.backend is not None
        execution = plugin.backend.get_execution(execution_uid)
        assert execution is not None
        assert execution["status"] == "failure"
        assert execution["error_message"] == "something went wrong"
        assert execution["error_type"] == "ValueError"

    def test_teardown_cleans_up_rc_mapping(
        self, initialized_plugin: ExecutionStatePlugin, mock_app: MagicMock
    ):
        """ON_TEARDOWN removes the rc-to-execution_uid mapping."""
        plugin = initialized_plugin
        registry = mock_app.hook_registry
        rc = _make_rc("cleanup-job")

        # BEFORE_JOB
        before_hooks = registry._global_hooks[HookEvent.BEFORE_JOB]
        for hook in before_hooks:
            hook(rc)

        assert id(rc) in plugin._rc_execution_map

        # ON_TEARDOWN
        teardown_hooks = registry._global_hooks[HookEvent.ON_TEARDOWN]
        for hook in teardown_hooks:
            hook(rc)

        assert id(rc) not in plugin._rc_execution_map

    def test_execution_uid_attached_to_result_metadata(
        self, initialized_plugin: ExecutionStatePlugin, mock_app: MagicMock
    ):
        """BEFORE_JOB attaches execution_uid via rc.set_result_metadata."""
        registry = mock_app.hook_registry
        rc = _make_rc("metadata-job")

        before_hooks = registry._global_hooks[HookEvent.BEFORE_JOB]
        for hook in before_hooks:
            hook(rc)

        # set_result_metadata should have been called with execution_uid
        rc.set_result_metadata.assert_called_once()
        call_args = rc.set_result_metadata.call_args
        assert call_args[0][0] == "execution_uid"
        assert isinstance(call_args[0][1], str)
        assert len(call_args[0][1]) > 0  # UUID string


# ─── Session Resume Tests ─────────────────────────────────────────────


class TestSessionResume:
    """Test session resume within TTL (30 min default)."""

    def test_session_resumed_within_ttl(
        self, initialized_plugin: ExecutionStatePlugin, mock_app: MagicMock
    ):
        """A second execution within TTL reuses the same session."""
        plugin = initialized_plugin
        registry = mock_app.hook_registry

        # First execution
        rc1 = _make_rc("job-1")
        before_hooks = registry._global_hooks[HookEvent.BEFORE_JOB]
        for hook in before_hooks:
            hook(rc1)

        session_id_1 = plugin.tracker.session_id
        assert session_id_1 is not None

        # Second execution (within TTL)
        rc2 = _make_rc("job-2")
        for hook in before_hooks:
            hook(rc2)

        session_id_2 = plugin.tracker.session_id
        assert session_id_2 == session_id_1

    def test_new_session_after_ttl_expires(self, tmp_db_path: Path):
        """A new session is created when TTL has expired."""
        # Use a very short TTL for testing
        short_ttl = 0.1  # 100ms

        backend = SQLiteBackend(base_dir=tmp_db_path)
        backend.initialize()

        tracker = ExecutionTracker(backend, session_ttl=short_ttl)

        # First execution creates a session
        tracker.record_start("job-1")
        session_id_1 = tracker.session_id
        assert session_id_1 is not None

        # Wait for TTL to expire
        time.sleep(0.15)

        # Create a new tracker (simulating process restart)
        tracker2 = ExecutionTracker(backend, session_ttl=short_ttl)
        tracker2.record_start("job-2")
        session_id_2 = tracker2.session_id

        # Should be a different session
        assert session_id_2 != session_id_1

        backend.close()

    def test_session_resume_preserves_execution_history(
        self, initialized_plugin: ExecutionStatePlugin, mock_app: MagicMock
    ):
        """Resumed session contains execution history from the earlier part."""
        plugin = initialized_plugin
        registry = mock_app.hook_registry

        # Multiple executions in the same session
        for i in range(3):
            rc = _make_rc(f"job-{i}")
            before_hooks = registry._global_hooks[HookEvent.BEFORE_JOB]
            for hook in before_hooks:
                hook(rc)
            # Complete each
            after_hooks = registry._global_hooks[HookEvent.AFTER_SUCCESS]
            for hook in after_hooks:
                hook(rc, result=f"result-{i}")

        # Query execution history
        history = plugin.tracker.get_execution_history(limit=10)
        assert len(history) == 3
        job_names = {h["job_name"] for h in history}
        assert job_names == {"job-0", "job-1", "job-2"}


# ─── Nested Execution Tests ──────────────────────────────────────────


class TestNestedExecutionParentUid:
    """Test nested execution parent_uid linkage via INVOKE_START/INVOKE_END."""

    def test_invoke_start_pushes_parent_uid(
        self, initialized_plugin: ExecutionStatePlugin, mock_app: MagicMock
    ):
        """INVOKE_START pushes the parent's execution_uid onto the stack."""
        plugin = initialized_plugin
        registry = mock_app.hook_registry

        # Parent job starts
        parent_rc = _make_rc("parent-job")
        before_hooks = registry._global_hooks[HookEvent.BEFORE_JOB]
        for hook in before_hooks:
            hook(parent_rc)

        parent_uid = plugin._rc_execution_map[id(parent_rc)]

        # INVOKE_START fires (parent invokes child)
        invoke_start_hooks = registry._global_hooks[HookEvent.INVOKE_START]
        for hook in invoke_start_hooks:
            hook(parent_rc, "child-job", {"arg": "val"}, 1)

        # Parent uid should be on the stack
        assert plugin._invoke_parent_stack == [parent_uid]

    def test_child_execution_linked_to_parent(
        self, initialized_plugin: ExecutionStatePlugin, mock_app: MagicMock
    ):
        """Child execution's parent_uid is set to the parent's execution_uid."""
        plugin = initialized_plugin
        registry = mock_app.hook_registry

        # Parent starts
        parent_rc = _make_rc("parent-job")
        before_hooks = registry._global_hooks[HookEvent.BEFORE_JOB]
        for hook in before_hooks:
            hook(parent_rc)

        parent_uid = plugin._rc_execution_map[id(parent_rc)]

        # INVOKE_START (parent invokes child)
        invoke_start_hooks = registry._global_hooks[HookEvent.INVOKE_START]
        for hook in invoke_start_hooks:
            hook(parent_rc, "child-job", {}, 1)

        # Child's BEFORE_JOB fires
        child_rc = _make_rc("child-job")
        for hook in before_hooks:
            hook(child_rc)

        child_uid = plugin._rc_execution_map[id(child_rc)]

        # Verify parent_uid linkage in DB
        assert plugin.backend is not None
        child_execution = plugin.backend.get_execution(child_uid)
        assert child_execution is not None
        assert child_execution["parent_uid"] == parent_uid
        assert child_execution["depth"] == 1

    def test_invoke_end_pops_from_stack(
        self, initialized_plugin: ExecutionStatePlugin, mock_app: MagicMock
    ):
        """INVOKE_END pops from the parent stack."""
        plugin = initialized_plugin
        registry = mock_app.hook_registry

        # Parent starts
        parent_rc = _make_rc("parent-job")
        before_hooks = registry._global_hooks[HookEvent.BEFORE_JOB]
        for hook in before_hooks:
            hook(parent_rc)

        # INVOKE_START
        invoke_start_hooks = registry._global_hooks[HookEvent.INVOKE_START]
        for hook in invoke_start_hooks:
            hook(parent_rc, "child-job", {}, 1)

        assert len(plugin._invoke_parent_stack) == 1

        # INVOKE_END
        invoke_end_hooks = registry._global_hooks[HookEvent.INVOKE_END]
        child_result = MagicMock()
        for hook in invoke_end_hooks:
            hook(parent_rc, "child-job", 1, child_result)

        assert len(plugin._invoke_parent_stack) == 0

    def test_deeply_nested_invocations(
        self, initialized_plugin: ExecutionStatePlugin, mock_app: MagicMock
    ):
        """Multiple levels of nesting correctly link parent_uid at each level."""
        plugin = initialized_plugin
        registry = mock_app.hook_registry
        before_hooks = registry._global_hooks[HookEvent.BEFORE_JOB]
        invoke_start_hooks = registry._global_hooks[HookEvent.INVOKE_START]
        invoke_end_hooks = registry._global_hooks[HookEvent.INVOKE_END]

        # Level 0: grandparent
        gp_rc = _make_rc("grandparent-job")
        for hook in before_hooks:
            hook(gp_rc)
        gp_uid = plugin._rc_execution_map[id(gp_rc)]

        # grandparent invokes parent
        for hook in invoke_start_hooks:
            hook(gp_rc, "parent-job", {}, 1)

        # Level 1: parent
        parent_rc = _make_rc("parent-job")
        for hook in before_hooks:
            hook(parent_rc)
        parent_uid = plugin._rc_execution_map[id(parent_rc)]

        # Verify parent links to grandparent
        assert plugin.backend is not None
        parent_exec = plugin.backend.get_execution(parent_uid)
        assert parent_exec is not None
        assert parent_exec["parent_uid"] == gp_uid
        assert parent_exec["depth"] == 1

        # parent invokes child
        for hook in invoke_start_hooks:
            hook(parent_rc, "child-job", {}, 2)

        # Level 2: child
        child_rc = _make_rc("child-job")
        for hook in before_hooks:
            hook(child_rc)
        child_uid = plugin._rc_execution_map[id(child_rc)]

        # Verify child links to parent
        child_exec = plugin.backend.get_execution(child_uid)
        assert child_exec is not None
        assert child_exec["parent_uid"] == parent_uid
        assert child_exec["depth"] == 2

        # Unwind: child done
        for hook in invoke_end_hooks:
            hook(parent_rc, "child-job", 2, MagicMock())

        # parent done
        for hook in invoke_end_hooks:
            hook(gp_rc, "parent-job", 1, MagicMock())

        assert len(plugin._invoke_parent_stack) == 0


# ─── Error Resilience Tests ──────────────────────────────────────────


class TestErrorResilience:
    """Test that DB write failures don't crash job execution (Req 23.11)."""

    def test_before_job_survives_db_failure(
        self, initialized_plugin: ExecutionStatePlugin, mock_app: MagicMock
    ):
        """BEFORE_JOB handler doesn't crash when DB write fails."""
        plugin = initialized_plugin
        registry = mock_app.hook_registry
        rc = _make_rc("resilient-job")

        # Patch the tracker's record_start to raise
        assert plugin.tracker is not None
        with patch.object(
            plugin.tracker, "record_start", side_effect=Exception("DB write failed")
        ):
            before_hooks = registry._global_hooks[HookEvent.BEFORE_JOB]
            # Should NOT raise
            for hook in before_hooks:
                hook(rc)

    def test_after_success_survives_db_failure(
        self, initialized_plugin: ExecutionStatePlugin, mock_app: MagicMock
    ):
        """AFTER_SUCCESS handler doesn't crash when DB write fails."""
        plugin = initialized_plugin
        registry = mock_app.hook_registry
        rc = _make_rc("resilient-job")

        # First, create a valid execution
        before_hooks = registry._global_hooks[HookEvent.BEFORE_JOB]
        for hook in before_hooks:
            hook(rc)

        # Now patch record_end to fail
        assert plugin.tracker is not None
        with patch.object(
            plugin.tracker, "record_end", side_effect=Exception("DB write failed")
        ):
            after_hooks = registry._global_hooks[HookEvent.AFTER_SUCCESS]
            # Should NOT raise
            for hook in after_hooks:
                hook(rc, result="some_result")

    def test_after_failure_survives_db_failure(
        self, initialized_plugin: ExecutionStatePlugin, mock_app: MagicMock
    ):
        """AFTER_FAILURE handler doesn't crash when DB write fails."""
        plugin = initialized_plugin
        registry = mock_app.hook_registry
        rc = _make_rc("resilient-job")

        # Create a valid execution
        before_hooks = registry._global_hooks[HookEvent.BEFORE_JOB]
        for hook in before_hooks:
            hook(rc)

        # Patch record_end to fail
        assert plugin.tracker is not None
        with patch.object(
            plugin.tracker, "record_end", side_effect=Exception("DB write failed")
        ):
            failure_hooks = registry._global_hooks[HookEvent.AFTER_FAILURE]
            # Should NOT raise
            for hook in failure_hooks:
                hook(rc, ValueError("job error"))

    def test_invoke_start_survives_error(
        self, initialized_plugin: ExecutionStatePlugin, mock_app: MagicMock
    ):
        """INVOKE_START handler doesn't crash on internal errors."""
        registry = mock_app.hook_registry

        # Use an rc that was never registered (no execution_uid)
        unregistered_rc = _make_rc("unregistered")

        invoke_start_hooks = registry._global_hooks[HookEvent.INVOKE_START]
        # Should NOT raise (no execution_uid means early return)
        for hook in invoke_start_hooks:
            hook(unregistered_rc, "child", {}, 1)

    def test_scope_created_survives_backend_not_initialized(
        self, plugin: ExecutionStatePlugin, mock_app: MagicMock
    ):
        """ON_SCOPE_CREATED doesn't crash when backend is not initialized."""
        # Plugin registered but APP_READY not fired yet (no backend)
        registry = mock_app.hook_registry
        scope = MagicMock()
        scope.scope_id = "test-scope"

        scope_hooks = registry._global_hooks[HookEvent.ON_SCOPE_CREATED]
        # Should NOT raise (backend is None, early return)
        for hook in scope_hooks:
            hook(scope)

    def test_plugin_without_tracker_handles_hooks_gracefully(
        self, plugin: ExecutionStatePlugin, mock_app: MagicMock
    ):
        """All hooks are no-ops when tracker is not initialized."""
        # Plugin is registered but APP_READY not fired → tracker is None
        registry = mock_app.hook_registry
        rc = _make_rc("no-tracker-job")

        # None of these should raise
        before_hooks = registry._global_hooks[HookEvent.BEFORE_JOB]
        for hook in before_hooks:
            hook(rc)

        after_hooks = registry._global_hooks[HookEvent.AFTER_SUCCESS]
        for hook in after_hooks:
            hook(rc, result="val")

        failure_hooks = registry._global_hooks[HookEvent.AFTER_FAILURE]
        for hook in failure_hooks:
            hook(rc, ValueError("err"))


# ─── Shutdown Tests ───────────────────────────────────────────────────


class TestShutdown:
    """Test plugin shutdown closes backend properly."""

    def test_shutdown_closes_backend(
        self, initialized_plugin: ExecutionStatePlugin, mock_app: MagicMock
    ):
        """on_shutdown closes the SQLiteBackend."""
        plugin = initialized_plugin
        assert plugin.backend is not None
        assert plugin.backend.is_initialized

        plugin.on_shutdown(mock_app)

        assert plugin.backend is None
        assert plugin.tracker is None

    def test_shutdown_safe_when_not_initialized(
        self, plugin: ExecutionStatePlugin, mock_app: MagicMock
    ):
        """on_shutdown is safe to call when backend was never initialized."""
        # APP_READY not fired, backend is None
        plugin.on_shutdown(mock_app)  # Should NOT raise


# ─── ON_SCOPE_CREATED Tests ──────────────────────────────────────────


class TestScopeCreated:
    """Test ON_SCOPE_CREATED replaces state store."""

    def test_scope_state_store_replaced(
        self, initialized_plugin: ExecutionStatePlugin, mock_app: MagicMock
    ):
        """ON_SCOPE_CREATED replaces the scope's state store with SQLiteStateStore."""
        registry = mock_app.hook_registry
        scope = MagicMock()
        scope.scope_id = "workflow-scope-1"

        scope_hooks = registry._global_hooks[HookEvent.ON_SCOPE_CREATED]
        for hook in scope_hooks:
            hook(scope)

        # replace_state_store should have been called
        scope.replace_state_store.assert_called_once()
        store_arg = scope.replace_state_store.call_args[0][0]

        from functualize_state_sqlite.state_store import SQLiteStateStore

        assert isinstance(store_arg, SQLiteStateStore)
