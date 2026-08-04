"""AST-based first-level dependency extraction for cache invalidation.

Parses Python source files using ast.parse() to identify in-project imports
without executing the module. Returns a mapping of resolved dependency file
paths to their sha256 hex digests.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path


def extract_first_level_dependencies(
    source_file: Path, project_root: Path
) -> dict[str, str]:
    """Extract in-project imports from a module's AST without executing it.

    Parses the source file's top-level import statements and resolves them
    to file paths within the project root. Only first-level (direct) imports
    are tracked — transitive dependencies are not followed.

    Args:
        source_file: Path to the Python source file to analyze.
        project_root: Root directory of the project; only imports resolving
            to files within this directory are included.

    Returns:
        A dict mapping absolute dependency file paths (as strings) to their
        sha256 hex digests. Returns an empty dict if the source file is
        unreadable or contains syntax errors.
    """
    try:
        source = source_file.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return {}

    dependencies: dict[str, str] = {}

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _try_resolve(alias.name, source_file, project_root, dependencies)
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            level = node.level  # relative import depth
            _try_resolve_from(
                module_name, level, source_file, project_root, dependencies
            )

    return dependencies


def _try_resolve(
    dotted_name: str,
    source_file: Path,
    project_root: Path,
    dependencies: dict[str, str],
) -> None:
    """Try to resolve an absolute import (import X.Y.Z) to a local file.

    Checks if the dotted module path corresponds to a file within project_root.
    If found, adds it to the dependencies dict with its sha256 hash.
    """
    resolved = _resolve_module_path(dotted_name, project_root)
    if resolved is not None:
        _add_dependency(resolved, dependencies)


def _try_resolve_from(
    module_name: str,
    level: int,
    source_file: Path,
    project_root: Path,
    dependencies: dict[str, str],
) -> None:
    """Try to resolve a from-import statement to a local file.

    Handles both absolute imports (level=0) and relative imports (level>0).
    For relative imports, the base path is computed from the source file's
    package location.
    """
    if level == 0:
        # Absolute import: from X.Y import Z
        if module_name:
            resolved = _resolve_module_path(module_name, project_root)
            if resolved is not None:
                _add_dependency(resolved, dependencies)
    else:
        # Relative import: from . import X, from ..sub import Y
        base = _get_relative_base(source_file, project_root, level)
        if base is None:
            return

        if module_name:
            # from .sub.module import Y → resolve relative to base
            parts = module_name.split(".")
            target = base
            for part in parts:
                target = target / part
            resolved = _resolve_file_path(target)
            if resolved is not None and _is_within(resolved, project_root):
                _add_dependency(resolved, dependencies)
        else:
            # from . import X → the base package __init__.py itself
            init_file = base / "__init__.py"
            if init_file.is_file() and _is_within(init_file, project_root):
                _add_dependency(init_file, dependencies)


def _resolve_module_path(dotted_name: str, project_root: Path) -> Path | None:
    """Resolve a dotted module name to a file path within project_root.

    Checks two forms:
    1. project_root / a/b/c.py  (module file)
    2. project_root / a/b/c/__init__.py  (package)

    Returns the resolved Path if found, or None if the module cannot be
    resolved to a local file.
    """
    parts = dotted_name.split(".")
    relative = Path(*parts)

    # Check as a .py file
    candidate = project_root / relative.with_suffix(".py")
    if candidate.is_file():
        return candidate

    # Check as a package (__init__.py)
    candidate = project_root / relative / "__init__.py"
    if candidate.is_file():
        return candidate

    return None


def _resolve_file_path(target: Path) -> Path | None:
    """Resolve a path (without extension) to either target.py or target/__init__.py."""
    candidate = target.with_suffix(".py")
    if candidate.is_file():
        return candidate

    candidate = target / "__init__.py"
    if candidate.is_file():
        return candidate

    return None


def _get_relative_base(
    source_file: Path, project_root: Path, level: int
) -> Path | None:
    """Compute the base directory for a relative import.

    For level=1 (from . import X): the package directory containing source_file.
    For level=2 (from .. import X): one level above that, etc.

    Returns None if the resulting path would escape the project root.
    """
    # Start from the directory containing the source file (its package)
    base = source_file.parent

    # Go up (level - 1) more directories for deeper relative imports
    for _ in range(level - 1):
        base = base.parent

    # Ensure we haven't escaped the project root
    if not _is_within(base, project_root):
        return None

    return base


def _is_within(path: Path, root: Path) -> bool:
    """Check if path is within root directory (inclusive)."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _add_dependency(file_path: Path, dependencies: dict[str, str]) -> None:
    """Add a resolved file to the dependencies dict with its sha256 hash.

    Silently skips files that cannot be read.
    """
    abs_path = str(file_path.resolve())
    if abs_path in dependencies:
        return

    try:
        content = file_path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        dependencies[abs_path] = digest
    except OSError:
        # File disappeared or is unreadable — skip silently
        pass
