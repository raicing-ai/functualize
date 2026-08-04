"""Hierarchy validation for parent-child project relationships.

Provides cycle detection, depth limiting, and version compatibility checking
for hierarchical functualize project structures. All path comparisons use
canonical absolute paths (via os.path.realpath) to handle symlinks and
relative paths correctly.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ValidationFailure:
    """Records a single validation failure.

    Attributes:
        child_namespace: The namespace the child would be mounted under.
        child_path: Absolute path to the child project.
        reason: Human-readable failure reason.
        failure_type: One of "version_incompatible", "cycle_detected",
            "depth_exceeded".
    """

    child_namespace: str
    child_path: str
    reason: str
    failure_type: str


class HierarchyValidationError(Exception):
    """Raised when hierarchy validation fails in strict mode.

    Attributes:
        failures: List of ValidationFailure instances describing each failure.
    """

    def __init__(
        self,
        message: str,
        failures: list[ValidationFailure] | None = None,
    ) -> None:
        super().__init__(message)
        self.failures: list[ValidationFailure] = failures or []


@dataclass
class ValidationContext:
    """Carries state through recursive hierarchy validation.

    Attributes:
        ancestry_chain: Set of canonical absolute paths from root to current
            node, used for O(1) cycle detection.
        ancestry_list: Ordered list of paths for cycle reporting.
        parent_version: The parent's running functualize version as
            (major, minor, patch), or None if unknown.
        strict: Whether strict validation mode is enabled.
        depth: Current nesting depth (root = 0).
        max_depth: Maximum allowed nesting depth.
    """

    ancestry_chain: set[str] = field(default_factory=set)
    ancestry_list: list[str] = field(default_factory=list)
    parent_version: tuple[int, int, int] | None = None
    strict: bool = False
    depth: int = 0
    max_depth: int = 10


class HierarchyValidator:
    """Validates child projects for version compatibility and cycle-free DAG structure."""

    @classmethod
    def create_root_context(
        cls,
        root_path: Path,
        parent_version: tuple[int, int, int] | None = None,
        strict: bool = False,
    ) -> ValidationContext:
        """Create the initial validation context for the root project.

        Initializes the ancestry chain with the root's canonical path.

        Args:
            root_path: Path to the root project.
            parent_version: The running functualize version.
            strict: Whether strict validation is enabled.

        Returns:
            A ValidationContext initialized for the root.
        """
        canonical_root = os.path.realpath(str(root_path))
        return ValidationContext(
            ancestry_chain={canonical_root},
            ancestry_list=[canonical_root],
            parent_version=parent_version,
            strict=strict,
            depth=0,
            max_depth=10,
        )

    @classmethod
    def validate_child(
        cls,
        child_namespace: str,
        child_path: Path,
        context: ValidationContext,
        child_version: tuple[int, int, int] | None = None,
    ) -> ValidationFailure | None:
        """Validate a single child project before mounting.

        Performs in order:
        1. Depth limit check
        2. Cycle detection (canonical path in ancestry chain)
        3. Version compatibility check

        Args:
            child_namespace: The namespace this child will be mounted under.
            child_path: Path to the child project root.
            context: The current validation context.
            child_version: The child's minimum functualize version, or None
                if unknown. When None, version compatibility is skipped.

        Returns:
            A ValidationFailure if validation fails, None if the child is valid.
        """
        canonical_child = os.path.realpath(str(child_path))

        # 1. Depth limit check
        if context.depth >= context.max_depth:
            reason = (
                f"Maximum hierarchy depth of {context.max_depth} exceeded "
                f"at project: {canonical_child}"
            )
            return ValidationFailure(
                child_namespace=child_namespace,
                child_path=canonical_child,
                reason=reason,
                failure_type="depth_exceeded",
            )

        # 2. Cycle detection
        if canonical_child in context.ancestry_chain:
            cycle_path = cls.format_cycle_path(context.ancestry_list, canonical_child)
            reason = f"Cycle detected: {cycle_path}"
            return ValidationFailure(
                child_namespace=child_namespace,
                child_path=canonical_child,
                reason=reason,
                failure_type="cycle_detected",
            )

        # 3. Version compatibility check
        if not cls.check_version_compatibility(child_version, context.parent_version):
            child_ver_str = (
                f"{child_version[0]}.{child_version[1]}.{child_version[2]}"
                if child_version
                else "unknown"
            )
            parent_ver_str = (
                f"{context.parent_version[0]}.{context.parent_version[1]}"
                f".{context.parent_version[2]}"
                if context.parent_version
                else "unknown"
            )
            reason = (
                f"Version incompatibility for child '{child_namespace}' "
                f"at {canonical_child}: child requires functualize "
                f"{child_ver_str} but parent runs {parent_ver_str}"
            )
            return ValidationFailure(
                child_namespace=child_namespace,
                child_path=canonical_child,
                reason=reason,
                failure_type="version_incompatible",
            )

        return None

    @classmethod
    def child_context(
        cls,
        child_path: Path,
        parent_context: ValidationContext,
    ) -> ValidationContext:
        """Create a new validation context for a child's own children.

        Extends the ancestry chain with the child's canonical path and
        increments the depth counter.

        Args:
            child_path: The child project's path.
            parent_context: The parent's validation context.

        Returns:
            A new ValidationContext for the child's subtree.
        """
        canonical_child = os.path.realpath(str(child_path))
        return ValidationContext(
            ancestry_chain=parent_context.ancestry_chain | {canonical_child},
            ancestry_list=[*parent_context.ancestry_list, canonical_child],
            parent_version=parent_context.parent_version,
            strict=parent_context.strict,
            depth=parent_context.depth + 1,
            max_depth=parent_context.max_depth,
        )

    @classmethod
    def check_version_compatibility(
        cls,
        child_version: tuple[int, int, int] | None,
        parent_version: tuple[int, int, int] | None,
    ) -> bool:
        """Check if a child's version is compatible with the parent.

        Compatible means: child's (major, minor) >= parent's (major, minor).
        If either version is None (unknown), the check passes.

        Args:
            child_version: The child's minimum functualize version.
            parent_version: The parent's running functualize version.

        Returns:
            True if compatible (or if either version is unknown), False otherwise.
        """
        if child_version is None or parent_version is None:
            return True

        child_major, child_minor, _ = child_version
        parent_major, parent_minor, _ = parent_version

        if child_major != parent_major:
            return child_major > parent_major

        return child_minor >= parent_minor

    @classmethod
    def format_cycle_path(cls, ancestry_list: list[str], repeated_path: str) -> str:
        """Format a cycle as a human-readable path chain.

        Example: "/path/A → /path/B → /path/C → /path/A"

        Args:
            ancestry_list: The ordered ancestry from root to current.
            repeated_path: The path that closes the cycle.

        Returns:
            Formatted cycle string with " → " separators.
        """
        return " → ".join([*ancestry_list, repeated_path])


class ErrorFormatter:
    """Formats validation error messages with optional Rich markup.

    Detects Rich availability at runtime and produces either Rich-formatted
    or plain-text messages accordingly.
    """

    @classmethod
    def format_version_warning(
        cls,
        child_namespace: str,
        child_path: str,
        child_version: tuple[int, int, int],
        parent_version: tuple[int, int, int],
        strict: bool = False,
    ) -> str:
        """Format a version incompatibility message.

        Includes child namespace, child path, child version, and parent
        version. In strict mode, the message indicates strict mode enforcement.

        Args:
            child_namespace: The namespace the child is mounted under.
            child_path: Absolute path to the child project.
            child_version: The child's minimum functualize version tuple.
            parent_version: The parent's running functualize version tuple.
            strict: Whether strict validation mode is enabled.

        Returns:
            Formatted warning/error message string.
        """
        child_ver_str = f"{child_version[0]}.{child_version[1]}.{child_version[2]}"
        parent_ver_str = f"{parent_version[0]}.{parent_version[1]}.{parent_version[2]}"

        if cls._has_rich():
            strict_text = " [bold red](strict mode)[/bold red]" if strict else ""
            return (
                f"[yellow]Version incompatibility{strict_text}:[/yellow] "
                f"child [bold]'{child_namespace}'[/bold] at "
                f"[bold]{child_path}[/bold] requires functualize "
                f"[bold red]{child_ver_str}[/bold red] but parent runs "
                f"[bold red]{parent_ver_str}[/bold red]"
            )

        strict_text = " (strict mode)" if strict else ""
        return (
            f"Version incompatibility{strict_text}: "
            f"child '{child_namespace}' at {child_path} requires functualize "
            f"{child_ver_str} but parent runs {parent_ver_str}"
        )

    @classmethod
    def format_cycle_error(
        cls,
        cycle_path: str,
    ) -> str:
        """Format a cycle detection error message.

        Includes the full cycle path with " → " separators.

        Args:
            cycle_path: The formatted cycle path string (e.g.,
                "/path/A → /path/B → /path/A").

        Returns:
            Formatted cycle error message string.
        """
        if cls._has_rich():
            return f"[bold red]Cycle detected:[/bold red] {cycle_path}"

        return f"Cycle detected: {cycle_path}"

    @classmethod
    def format_unknown_version_warning(
        cls,
        child_namespace: str,
        child_path: str,
    ) -> str:
        """Format a warning for unknown child version.

        Indicates that the child's functualize version could not be determined.

        Args:
            child_namespace: The namespace the child is mounted under.
            child_path: Absolute path to the child project.

        Returns:
            Formatted unknown version warning message string.
        """
        if cls._has_rich():
            return (
                f"[yellow]Unknown functualize version[/yellow] for child "
                f"[bold]'{child_namespace}'[/bold] at "
                f"[bold]{child_path}[/bold]"
            )

        return (
            f"Unknown functualize version for child '{child_namespace}' at {child_path}"
        )

    @classmethod
    def _has_rich(cls) -> bool:
        """Check if Rich is available in the runtime environment.

        Internal packages must not import rich at runtime (CLI isolation).
        Always returns False — rich formatting is handled by the CLI layer.

        Returns:
            Always False — internal packages use plain text only.
        """
        return False
