"""Tests for ConfigSnapshotStore recording during job execution.

Verifies that:
1. record() is called with outcome "success" on successful execution
2. record() is called with outcome "failure" when execution raises
3. flush() is called after recording to persist to disk
4. effective_values are extracted from PendingExecution when available
5. effective_values fall back to kwargs when no PendingExecution exists

Requirements: R4-AC1, R4-AC2, R4-AC3, R4-AC4, R4-AC5
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from functualize._cli.data.config_snapshot_store import ConfigSnapshotStore
from functualize._cli.data.pending_execution import PendingExecution
from functualize._cli.data.resolved_value_compat import ResolvedValueCompat
from functualize._cli.tui.app import FunctualizeInlineTUI
from functualize._engine.result import JobResult
from functualize.app.utils import RunStatus

# =============================================================================
# Helpers
# =============================================================================


def _success_result() -> Any:
    """A JobResult the engine would produce for a run that succeeded."""
    return JobResult(
        status=RunStatus.SUCCESS,
        return_value=None,
        duration_ms=0.0,
        job_name="deploy",
    )


def _make_tui_with_mocks(
    *,
    pending: PendingExecution | None = None,
    execute_side_effect: Any = None,
    execute_return: Any = None,
) -> tuple[FunctualizeInlineTUI, MagicMock, MagicMock]:
    """Create a TUI instance with mocked internals for testing execution.

    Returns:
        Tuple of (tui, mock_snapshot_store, mock_func_app).
    """
    with patch.object(FunctualizeInlineTUI, "__init__", lambda self, *a, **kw: None):
        tui = FunctualizeInlineTUI.__new__(FunctualizeInlineTUI)

    # Set up mock snapshot store
    mock_store = MagicMock(spec=ConfigSnapshotStore)
    tui._snapshot_store = mock_store

    # Set up pending execution
    tui._pending = pending

    # Set up mock func_app
    mock_app = MagicMock()
    if execute_side_effect:
        mock_app.execute.side_effect = execute_side_effect
    elif execute_return is not None:
        mock_app.execute.return_value = execute_return
    else:
        # `FunctualizeApp.execute()` returns a `JobResult`, never None, and the
        # panel branches on that result's *status* — a raised body and a
        # FAILURE result are different things (see execute_job_sync). A double
        # returning None therefore reads as "not a success status", which is
        # correct behaviour against an unrealistic stand-in. Default to the
        # success result a real call would produce.
        mock_app.execute.return_value = _success_result()
    tui._func_app = mock_app

    return tui, mock_store, mock_app


# =============================================================================
# Test: _extract_effective_values
# =============================================================================


class TestExtractEffectiveValues:
    """_extract_effective_values returns correct values from pending or kwargs."""

    def test_extracts_from_pending_when_job_matches(self) -> None:
        """Uses PendingExecution.all_effective() when pending exists for the job."""
        pending = PendingExecution(
            job_name="deploy",
            resolved_values={
                "env": ResolvedValueCompat(value="prod", source_type="cli"),
                "region": ResolvedValueCompat(value="us-east-1", source_type="default"),
            },
        )
        tui, _, _ = _make_tui_with_mocks(pending=pending)

        result = tui._extract_effective_values("deploy", {"env": "prod"})

        assert result == {"env": "prod", "region": "us-east-1"}

    def test_extracts_overrides_from_pending(self) -> None:
        """Overrides in PendingExecution are reflected in extracted values."""
        pending = PendingExecution(
            job_name="deploy",
            resolved_values={
                "env": ResolvedValueCompat(value="staging", source_type="default"),
                "region": ResolvedValueCompat(value="us-east-1", source_type="default"),
            },
        )
        pending.overrides["env"] = "prod"
        tui, _, _ = _make_tui_with_mocks(pending=pending)

        result = tui._extract_effective_values("deploy", {"env": "staging"})

        assert result["env"] == "prod"  # override wins
        assert result["region"] == "us-east-1"

    def test_falls_back_to_kwargs_when_no_pending(self) -> None:
        """Returns kwargs when _pending is None."""
        tui, _, _ = _make_tui_with_mocks(pending=None)

        result = tui._extract_effective_values(
            "deploy", {"env": "prod", "region": "us-west-2"}
        )

        assert result == {"env": "prod", "region": "us-west-2"}

    def test_falls_back_to_kwargs_when_job_name_differs(self) -> None:
        """Returns kwargs when pending is for a different job."""
        pending = PendingExecution(
            job_name="build",
            resolved_values={
                "target": ResolvedValueCompat(value="release", source_type="default"),
            },
        )
        tui, _, _ = _make_tui_with_mocks(pending=pending)

        result = tui._extract_effective_values("deploy", {"env": "prod"})

        assert result == {"env": "prod"}


# =============================================================================
# Test: Snapshot recording on success
# =============================================================================


class TestRecordOnSuccess:
    """ConfigSnapshotStore.record() is called with outcome='success' on success."""

    @pytest.mark.asyncio
    async def test_records_success_after_execution(self) -> None:
        """record() is called with 'success' when execution completes normally."""
        pending = PendingExecution(
            job_name="deploy",
            resolved_values={
                "env": ResolvedValueCompat(value="prod", source_type="cli"),
            },
        )
        tui, mock_store, _ = _make_tui_with_mocks(pending=pending)

        # Mock the RichLog widget that _execute_job_async queries
        mock_log = MagicMock()
        tui.query_one = MagicMock(return_value=mock_log)

        return_code = await tui._execute_job_async("deploy", {"env": "prod"})

        assert return_code == 0
        mock_store.record.assert_called_once_with("deploy", {"env": "prod"}, "success")

    @pytest.mark.asyncio
    async def test_flush_called_after_success_record(self) -> None:
        """flush() is called after record() on success."""
        pending = PendingExecution(
            job_name="deploy",
            resolved_values={
                "env": ResolvedValueCompat(value="prod", source_type="cli"),
            },
        )
        tui, mock_store, _ = _make_tui_with_mocks(pending=pending)
        mock_log = MagicMock()
        tui.query_one = MagicMock(return_value=mock_log)

        await tui._execute_job_async("deploy", {"env": "prod"})

        mock_store.flush.assert_called_once()
        # Verify flush is called AFTER record
        record_call_order = mock_store.record.call_args_list
        flush_call_order = mock_store.flush.call_args_list
        assert len(record_call_order) == 1
        assert len(flush_call_order) == 1


# =============================================================================
# Test: Snapshot recording on failure
# =============================================================================


class TestRecordOnFailedResult:
    """A FAILURE *result* is a failure, even though nothing raised.

    `FunctualizeApp.execute()` reports a failed run by returning a FAILURE
    `JobResult`, not by raising — a missing-config error and a raised job body
    both come back that way. The panel must branch on the result's status, or
    it prints "✓ Done" for a run `func builtin history` records as failed.

    Every other failure test here drives an *exception*, which is caught
    before the status branch is ever reached — so without these, that branch
    can be replaced with `if True:` and the whole file still passes.
    """

    @pytest.mark.asyncio
    async def test_failure_result_records_failure_and_nonzero_exit(self) -> None:
        """A FAILURE JobResult records 'failure' and returns a non-zero code."""
        pending = PendingExecution(
            job_name="deploy",
            resolved_values={
                "env": ResolvedValueCompat(value="prod", source_type="cli"),
            },
        )
        tui, mock_store, _ = _make_tui_with_mocks(
            pending=pending,
            execute_return=JobResult(
                status=RunStatus.FAILURE,
                return_value=None,
                duration_ms=0.0,
                job_name="deploy",
            ),
        )
        mock_log = MagicMock()
        tui.query_one = MagicMock(return_value=mock_log)

        return_code = await tui._execute_job_async("deploy", {"env": "prod"})

        assert return_code != 0
        mock_store.record.assert_called_once_with("deploy", {"env": "prod"}, "failure")

    @pytest.mark.asyncio
    async def test_skipped_result_is_not_a_failure(self) -> None:
        """SKIPPED did what was asked — it records success and exits 0."""
        tui, mock_store, _ = _make_tui_with_mocks(
            execute_return=JobResult(
                status=RunStatus.SKIPPED,
                return_value=None,
                duration_ms=0.0,
                job_name="deploy",
            ),
        )
        mock_log = MagicMock()
        tui.query_one = MagicMock(return_value=mock_log)

        return_code = await tui._execute_job_async("deploy", {"env": "prod"})

        assert return_code == 0
        mock_store.record.assert_called_once_with("deploy", {"env": "prod"}, "success")


class TestRecordOnFailure:
    """ConfigSnapshotStore.record() is called with outcome='failure' on exception."""

    @pytest.mark.asyncio
    async def test_records_failure_on_exception(self) -> None:
        """record() is called with 'failure' when execution raises."""
        pending = PendingExecution(
            job_name="deploy",
            resolved_values={
                "env": ResolvedValueCompat(value="prod", source_type="cli"),
            },
        )
        tui, mock_store, _ = _make_tui_with_mocks(
            pending=pending,
            execute_side_effect=RuntimeError("connection failed"),
        )
        mock_log = MagicMock()
        tui.query_one = MagicMock(return_value=mock_log)

        return_code = await tui._execute_job_async("deploy", {"env": "prod"})

        assert return_code == 1
        mock_store.record.assert_called_once_with("deploy", {"env": "prod"}, "failure")

    @pytest.mark.asyncio
    async def test_flush_called_after_failure_record(self) -> None:
        """flush() is called after record() on failure."""
        pending = PendingExecution(
            job_name="deploy",
            resolved_values={
                "env": ResolvedValueCompat(value="prod", source_type="cli"),
            },
        )
        tui, mock_store, _ = _make_tui_with_mocks(
            pending=pending,
            execute_side_effect=ValueError("bad config"),
        )
        mock_log = MagicMock()
        tui.query_one = MagicMock(return_value=mock_log)

        await tui._execute_job_async("deploy", {"env": "prod"})

        mock_store.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_failure_uses_kwargs_when_no_pending(self) -> None:
        """On failure without pending, kwargs are recorded as values."""
        tui, mock_store, _ = _make_tui_with_mocks(
            pending=None,
            execute_side_effect=RuntimeError("oops"),
        )
        mock_log = MagicMock()
        tui.query_one = MagicMock(return_value=mock_log)

        await tui._execute_job_async(
            "deploy", {"env": "staging", "region": "eu-west-1"}
        )

        mock_store.record.assert_called_once_with(
            "deploy", {"env": "staging", "region": "eu-west-1"}, "failure"
        )


# =============================================================================
# Test: Flush persists to disk
# =============================================================================


class TestFlushPersists:
    """ConfigSnapshotStore.flush() actually persists data."""

    def test_flush_writes_to_file(self, tmp_path: Any) -> None:
        """flush() persists recorded snapshots to disk."""
        store_path = tmp_path / "snapshots.json"
        store = ConfigSnapshotStore(path=store_path)

        store.record("deploy", {"env": "prod"}, "success")
        store.flush()

        assert store_path.exists()

        # Reload and verify
        loaded = ConfigSnapshotStore.load(path=store_path)
        snapshot = loaded.get_last_snapshot("deploy")
        assert snapshot is not None
        assert snapshot.job_name == "deploy"
        assert snapshot.values == {"env": "prod"}
        assert snapshot.outcome == "success"

    def test_flush_persists_multiple_records(self, tmp_path: Any) -> None:
        """Multiple records are persisted and retrievable."""
        store_path = tmp_path / "snapshots.json"
        store = ConfigSnapshotStore(path=store_path)

        store.record("deploy", {"env": "prod"}, "success")
        store.record("deploy", {"env": "staging"}, "failure")
        store.flush()

        loaded = ConfigSnapshotStore.load(path=store_path)
        snapshots = loaded.get_snapshots("deploy", limit=10)
        assert len(snapshots) == 2
        # Most recent first (reverse chronological)
        assert snapshots[0].values == {"env": "staging"}
        assert snapshots[0].outcome == "failure"
        assert snapshots[1].values == {"env": "prod"}
        assert snapshots[1].outcome == "success"
