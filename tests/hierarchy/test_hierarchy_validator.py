"""Unit tests for HierarchyValidator and ErrorFormatter.

Tests hierarchy validation including cycle detection, depth limiting,
version compatibility checking, and error formatting.

Requirements: 2.1, 2.2, 2.4, 2.5, 3.1, 3.2, 3.3, 3.7, 5.1, 5.2, 5.3, 5.4, 5.6
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import patch

from functualize._discovery.hierarchy import (
    ErrorFormatter,
    HierarchyValidator,
    ValidationContext,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestCreateRootContext:
    """Test HierarchyValidator.create_root_context initializes correctly."""

    def test_create_root_context_initializes_ancestry_with_root_canonical_path(
        self, tmp_path: Path
    ):
        """create_root_context() sets ancestry_chain and ancestry_list to root's canonical path.

        Validates: Requirement 3.3
        """
        context = HierarchyValidator.create_root_context(
            root_path=tmp_path,
            parent_version=(0, 2, 0),
            strict=False,
        )

        canonical_root = os.path.realpath(str(tmp_path))
        assert canonical_root in context.ancestry_chain
        assert len(context.ancestry_chain) == 1
        assert context.ancestry_list == [canonical_root]

    def test_create_root_context_sets_parent_version(self, tmp_path: Path):
        """create_root_context() stores the parent version in the context.

        Validates: Requirement 3.3
        """
        context = HierarchyValidator.create_root_context(
            root_path=tmp_path,
            parent_version=(1, 5, 3),
            strict=True,
        )

        assert context.parent_version == (1, 5, 3)
        assert context.strict is True
        assert context.depth == 0
        assert context.max_depth == 10

    def test_create_root_context_resolves_symlinks(self, tmp_path: Path):
        """create_root_context() resolves symlinks to canonical path.

        Validates: Requirement 3.3
        """
        real_dir = tmp_path / "real_project"
        real_dir.mkdir()
        symlink_dir = tmp_path / "link_project"
        symlink_dir.symlink_to(real_dir)

        context = HierarchyValidator.create_root_context(
            root_path=symlink_dir,
            parent_version=(0, 1, 0),
        )

        canonical_real = os.path.realpath(str(real_dir))
        assert canonical_real in context.ancestry_chain
        assert context.ancestry_list == [canonical_real]


class TestValidateChild:
    """Test HierarchyValidator.validate_child for various validation scenarios."""

    def test_validate_child_cycle_detected_returns_failure(self, tmp_path: Path):
        """validate_child() returns ValidationFailure with failure_type='cycle_detected'
        when child path is already in ancestry chain.

        Validates: Requirements 3.1, 3.2
        """
        child_dir = tmp_path / "child_project"
        child_dir.mkdir()
        canonical_child = os.path.realpath(str(child_dir))

        # Create context where child is already in ancestry
        context = ValidationContext(
            ancestry_chain={canonical_child, os.path.realpath(str(tmp_path))},
            ancestry_list=[os.path.realpath(str(tmp_path)), canonical_child],
            parent_version=(0, 2, 0),
            strict=False,
            depth=1,
            max_depth=10,
        )

        result = HierarchyValidator.validate_child(
            child_namespace="cyclic_child",
            child_path=child_dir,
            context=context,
        )

        assert result is not None
        assert result.failure_type == "cycle_detected"
        assert result.child_namespace == "cyclic_child"
        assert canonical_child in result.child_path

    def test_validate_child_depth_exceeded_returns_failure(self, tmp_path: Path):
        """validate_child() returns ValidationFailure with failure_type='depth_exceeded'
        when depth >= max_depth.

        Validates: Requirement 3.7
        """
        child_dir = tmp_path / "deep_child"
        child_dir.mkdir()

        context = ValidationContext(
            ancestry_chain={os.path.realpath(str(tmp_path))},
            ancestry_list=[os.path.realpath(str(tmp_path))],
            parent_version=(0, 2, 0),
            strict=False,
            depth=10,
            max_depth=10,
        )

        result = HierarchyValidator.validate_child(
            child_namespace="deep_child",
            child_path=child_dir,
            context=context,
        )

        assert result is not None
        assert result.failure_type == "depth_exceeded"
        assert result.child_namespace == "deep_child"

    def test_validate_child_incompatible_version_returns_failure(self, tmp_path: Path):
        """validate_child() returns ValidationFailure with failure_type='version_incompatible'
        when child version is lower than parent version.

        Validates: Requirements 2.1, 2.2
        """
        child_dir = tmp_path / "old_child"
        child_dir.mkdir()

        context = ValidationContext(
            ancestry_chain={os.path.realpath(str(tmp_path))},
            ancestry_list=[os.path.realpath(str(tmp_path))],
            parent_version=(0, 3, 0),
            strict=False,
            depth=0,
            max_depth=10,
        )

        result = HierarchyValidator.validate_child(
            child_namespace="old_child",
            child_path=child_dir,
            context=context,
            child_version=(0, 1, 0),
        )

        assert result is not None
        assert result.failure_type == "version_incompatible"
        assert result.child_namespace == "old_child"

    def test_validate_child_compatible_version_returns_none(self, tmp_path: Path):
        """validate_child() returns None when child version is compatible with parent.

        Validates: Requirement 2.4
        """
        child_dir = tmp_path / "good_child"
        child_dir.mkdir()

        context = ValidationContext(
            ancestry_chain={os.path.realpath(str(tmp_path))},
            ancestry_list=[os.path.realpath(str(tmp_path))],
            parent_version=(0, 2, 0),
            strict=False,
            depth=0,
            max_depth=10,
        )

        result = HierarchyValidator.validate_child(
            child_namespace="good_child",
            child_path=child_dir,
            context=context,
            child_version=(0, 3, 0),
        )

        assert result is None

    def test_validate_child_unknown_version_returns_none(self, tmp_path: Path):
        """validate_child() returns None when child version is unknown (None).

        Validates: Requirement 2.5
        """
        child_dir = tmp_path / "unknown_child"
        child_dir.mkdir()

        context = ValidationContext(
            ancestry_chain={os.path.realpath(str(tmp_path))},
            ancestry_list=[os.path.realpath(str(tmp_path))],
            parent_version=(0, 2, 0),
            strict=False,
            depth=0,
            max_depth=10,
        )

        result = HierarchyValidator.validate_child(
            child_namespace="unknown_child",
            child_path=child_dir,
            context=context,
            child_version=None,
        )

        assert result is None

    def test_validate_child_depth_check_before_cycle_check(self, tmp_path: Path):
        """validate_child() checks depth before cycle detection.

        When both depth exceeded and cycle present, depth_exceeded is returned.

        Validates: Requirement 3.7
        """
        child_dir = tmp_path / "child"
        child_dir.mkdir()
        canonical_child = os.path.realpath(str(child_dir))

        # Both depth exceeded AND cycle present
        context = ValidationContext(
            ancestry_chain={os.path.realpath(str(tmp_path)), canonical_child},
            ancestry_list=[os.path.realpath(str(tmp_path)), canonical_child],
            parent_version=(0, 2, 0),
            strict=False,
            depth=10,
            max_depth=10,
        )

        result = HierarchyValidator.validate_child(
            child_namespace="child",
            child_path=child_dir,
            context=context,
        )

        assert result is not None
        assert result.failure_type == "depth_exceeded"


class TestFormatCyclePath:
    """Test HierarchyValidator.format_cycle_path produces correct chain."""

    def test_format_cycle_path_produces_arrow_chain(self):
        """format_cycle_path() produces correct " → " separated chain.

        Validates: Requirement 5.2
        """
        ancestry_list = ["/path/to/A", "/path/to/B", "/path/to/C"]
        repeated_path = "/path/to/A"

        result = HierarchyValidator.format_cycle_path(ancestry_list, repeated_path)

        assert result == "/path/to/A → /path/to/B → /path/to/C → /path/to/A"

    def test_format_cycle_path_with_two_nodes(self):
        """format_cycle_path() works with minimal two-node cycle.

        Validates: Requirement 5.2
        """
        ancestry_list = ["/path/to/A"]
        repeated_path = "/path/to/A"

        result = HierarchyValidator.format_cycle_path(ancestry_list, repeated_path)

        assert result == "/path/to/A → /path/to/A"

    def test_format_cycle_path_with_long_chain(self):
        """format_cycle_path() handles longer chains correctly.

        Validates: Requirement 5.2
        """
        ancestry_list = ["/a", "/b", "/c", "/d", "/e"]
        repeated_path = "/b"

        result = HierarchyValidator.format_cycle_path(ancestry_list, repeated_path)

        assert result == "/a → /b → /c → /d → /e → /b"
        assert " → " in result


class TestErrorFormatter:
    """Test ErrorFormatter with Rich available and unavailable."""

    def test_format_version_warning_with_rich_uses_markup(self):
        """ErrorFormatter uses Rich markup when Rich is available.

        Validates: Requirement 5.3
        """
        with patch.object(ErrorFormatter, "_has_rich", return_value=True):
            result = ErrorFormatter.format_version_warning(
                child_namespace="my_child",
                child_path="/path/to/child",
                child_version=(0, 1, 0),
                parent_version=(0, 2, 0),
                strict=False,
            )

        # Rich markup should be present
        assert "[yellow]" in result
        assert "[bold]" in result or "[bold red]" in result
        assert "my_child" in result
        assert "/path/to/child" in result
        assert "0.1.0" in result
        assert "0.2.0" in result

    def test_format_version_warning_without_rich_uses_plain_text(self):
        """ErrorFormatter uses plain text when Rich is not available.

        Validates: Requirement 5.4
        """
        with patch.object(ErrorFormatter, "_has_rich", return_value=False):
            result = ErrorFormatter.format_version_warning(
                child_namespace="my_child",
                child_path="/path/to/child",
                child_version=(0, 1, 0),
                parent_version=(0, 2, 0),
                strict=False,
            )

        # No Rich markup
        assert "[" not in result or ("[" in result and "yellow" not in result)
        assert "my_child" in result
        assert "/path/to/child" in result
        assert "0.1.0" in result
        assert "0.2.0" in result

    def test_format_cycle_error_with_rich_uses_markup(self):
        """ErrorFormatter.format_cycle_error uses Rich markup when available.

        Validates: Requirement 5.3
        """
        with patch.object(ErrorFormatter, "_has_rich", return_value=True):
            result = ErrorFormatter.format_cycle_error("/a → /b → /a")

        assert "[bold red]" in result
        assert "/a → /b → /a" in result

    def test_format_cycle_error_without_rich_uses_plain_text(self):
        """ErrorFormatter.format_cycle_error uses plain text when Rich unavailable.

        Validates: Requirement 5.4
        """
        with patch.object(ErrorFormatter, "_has_rich", return_value=False):
            result = ErrorFormatter.format_cycle_error("/a → /b → /a")

        assert "[bold red]" not in result
        assert "Cycle detected:" in result
        assert "/a → /b → /a" in result

    def test_format_unknown_version_with_rich_uses_markup(self):
        """ErrorFormatter.format_unknown_version_warning uses Rich markup when available.

        Validates: Requirement 5.3
        """
        with patch.object(ErrorFormatter, "_has_rich", return_value=True):
            result = ErrorFormatter.format_unknown_version_warning(
                child_namespace="tools",
                child_path="/path/to/tools",
            )

        assert "[yellow]" in result
        assert "[bold]" in result
        assert "tools" in result
        assert "/path/to/tools" in result

    def test_format_unknown_version_without_rich_uses_plain_text(self):
        """ErrorFormatter.format_unknown_version_warning uses plain text without Rich.

        Validates: Requirement 5.4
        """
        with patch.object(ErrorFormatter, "_has_rich", return_value=False):
            result = ErrorFormatter.format_unknown_version_warning(
                child_namespace="tools",
                child_path="/path/to/tools",
            )

        assert "[yellow]" not in result
        assert "[bold]" not in result
        assert "tools" in result
        assert "/path/to/tools" in result

    def test_strict_mode_message_includes_strict_mode_text(self):
        """ErrorFormatter includes 'strict mode' text when strict=True.

        Validates: Requirement 5.6
        """
        with patch.object(ErrorFormatter, "_has_rich", return_value=False):
            result = ErrorFormatter.format_version_warning(
                child_namespace="my_child",
                child_path="/path/to/child",
                child_version=(0, 1, 0),
                parent_version=(0, 2, 0),
                strict=True,
            )

        assert "strict mode" in result

    def test_strict_mode_message_with_rich_includes_strict_mode_text(self):
        """ErrorFormatter includes 'strict mode' text with Rich markup when strict=True.

        Validates: Requirement 5.6
        """
        with patch.object(ErrorFormatter, "_has_rich", return_value=True):
            result = ErrorFormatter.format_version_warning(
                child_namespace="my_child",
                child_path="/path/to/child",
                child_version=(0, 1, 0),
                parent_version=(0, 2, 0),
                strict=True,
            )

        assert "strict mode" in result
