"""Unit tests for detect_mode() with group_names parameter.

Validates Requirements: 4, 7, 8
"""

from __future__ import annotations

from functualize._cli.dispatch import Mode, detect_mode


class TestDetectModeGroups:
    """Tests for detect_mode() group-aware dispatch."""

    def test_group_detected(self) -> None:
        """First positional in group_names → Mode.GROUP.

        Validates: Requirement 4
        """
        mode, args = detect_mode(
            ["func", "infra", "provision"],
            job_names={"deploy"},
            group_names={"infra"},
        )
        assert mode is Mode.GROUP
        assert args == ["infra", "provision"]

    def test_nested_greedy(self) -> None:
        """Greedy prefix matching consumes longest group prefix.

        Validates: Requirement 4
        """
        mode, args = detect_mode(
            ["func", "infra", "aws", "provision"],
            job_names=set(),
            group_names={"infra", "infra.aws"},
        )
        assert mode is Mode.GROUP
        assert args == ["infra", "aws", "provision"]

    def test_group_shadows_flat_job(self) -> None:
        """GROUP takes priority over JOB when name matches both.

        Validates: Requirements 4, 8
        """
        mode, args = detect_mode(
            ["func", "infra"],
            job_names={"infra"},
            group_names={"infra"},
        )
        assert mode is Mode.GROUP
        assert args == ["infra"]

    def test_stale_cache_unknown(self) -> None:
        """Unknown first positional with group_names provided → Mode.UNKNOWN.

        Validates: Requirement 7
        """
        mode, args = detect_mode(
            ["func", "newgroup", "cmd"],
            job_names={"deploy"},
            group_names={"infra"},
        )
        assert mode is Mode.UNKNOWN
        assert args == ["newgroup", "cmd"]

    def test_no_groups_backward_compat(self) -> None:
        """group_names=None skips GROUP check → falls through to JOB.

        Validates: Requirement 8
        """
        mode, args = detect_mode(
            ["func", "deploy"],
            job_names={"deploy"},
            group_names=None,
        )
        assert mode is Mode.JOB
        assert args == ["deploy"]

    def test_empty_group_names(self) -> None:
        """Empty group_names set skips GROUP check → UNKNOWN (not in job_names).

        Validates: Requirements 7, 8
        """
        mode, args = detect_mode(
            ["func", "infra"],
            job_names={"deploy"},
            group_names=set(),
        )
        assert mode is Mode.UNKNOWN
        assert args == ["infra"]
