"""Module pre-filter protocol and composable combinators.

Provides a fast pre-import check mechanism to determine whether a source
file should be imported for job extraction, without actually importing it.

Only imports from _types/ and stdlib — zero third-party runtime dependencies.
"""

from __future__ import annotations

import ast
import fnmatch
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class ModulePreFilter(Protocol):
    """Fast pre-import check: should this module be imported for job extraction?"""

    def should_import(self, source_file: Path) -> bool: ...


# ---------------------------------------------------------------------------
# Composable combinators
# ---------------------------------------------------------------------------


class AllOf:
    """Composite pre-filter: passes only if ALL inner filters pass.

    Satisfies the ``ModulePreFilter`` Protocol via structural typing.

    Args:
        filters: One or more ``ModulePreFilter``-compatible objects.
    """

    def __init__(self, *filters: ModulePreFilter) -> None:
        self._filters = filters

    def should_import(self, source_file: Path) -> bool:
        """Return True only if all inner filters return True."""
        return all(f.should_import(source_file) for f in self._filters)


class AnyOf:
    """Composite pre-filter: passes if ANY inner filter passes.

    Satisfies the ``ModulePreFilter`` Protocol via structural typing.

    Args:
        filters: One or more ``ModulePreFilter``-compatible objects.
    """

    def __init__(self, *filters: ModulePreFilter) -> None:
        self._filters = filters

    def should_import(self, source_file: Path) -> bool:
        """Return True if at least one inner filter returns True."""
        return any(f.should_import(source_file) for f in self._filters)


class NoneOf:
    """Composite pre-filter: passes only if NO inner filter passes.

    Satisfies the ``ModulePreFilter`` Protocol via structural typing.

    Args:
        filters: One or more ``ModulePreFilter``-compatible objects.
    """

    def __init__(self, *filters: ModulePreFilter) -> None:
        self._filters = filters

    def should_import(self, source_file: Path) -> bool:
        """Return True only if no inner filter returns True."""
        return not any(f.should_import(source_file) for f in self._filters)


# ---------------------------------------------------------------------------
# Built-in implementations
# ---------------------------------------------------------------------------


class DefaultModulePreFilter:
    """Skip files whose names start with an underscore.

    This is the simplest built-in filter — it excludes private/internal
    modules (e.g. ``_helpers.py``, ``__main__.py``) from job extraction.

    Satisfies the ``ModulePreFilter`` Protocol via structural typing.
    """

    def should_import(self, source_file: Path) -> bool:
        """Return False for underscore-prefixed filenames."""
        return not source_file.name.startswith("_")


class ASTModulePreFilter:
    """Check for public function definitions via AST parsing.

    Parses the source file's AST and returns True only if the module
    contains at least one public (non-underscore-prefixed) function
    definition at the top level.

    Satisfies the ``ModulePreFilter`` Protocol via structural typing.
    """

    def should_import(self, source_file: Path) -> bool:
        """Return True if the file contains at least one public function def."""
        try:
            source = source_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(source_file))
        except (OSError, SyntaxError):
            return False

        for node in ast.iter_child_nodes(tree):
            if isinstance(
                node, ast.FunctionDef | ast.AsyncFunctionDef
            ) and not node.name.startswith("_"):
                return True
        return False


class DisplayClassPreFilter:
    """Check for display-provider class definitions via AST parsing.

    Parses the source file's AST and returns True if any top-level class
    body assigns ``display_id`` — the cheap textual signal that the module
    defines a DisplayProvider. Without this, a module containing only
    displays (no public functions) would be pre-filtered out and never
    reach the scan's display-detection pass.

    Satisfies the ``ModulePreFilter`` Protocol via structural typing.
    """

    def should_import(self, source_file: Path) -> bool:
        """Return True if any top-level class assigns ``display_id``."""
        try:
            source = source_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(source_file))
        except (OSError, SyntaxError):
            return False

        for node in ast.iter_child_nodes(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name) and target.id == "display_id":
                            return True
                elif (
                    isinstance(stmt, ast.AnnAssign)
                    and isinstance(stmt.target, ast.Name)
                    and stmt.target.id == "display_id"
                ):
                    return True
        return False


class GroupOptionsPreFilter:
    """Check for a bound ``GroupOptions`` declaration via AST parsing.

    Returns True if any top-level class lists a ``GroupOptions`` base — the
    cheap textual signal that the module declares a group's flags.

    Used in **two** places in the stack, for two distinct reasons:

    1. To exempt the module from ``DefaultModulePreFilter``. The conventional
       home for a declaration is ``jobs/deploy/_group.py``, and the leading
       underscore otherwise means "private helper, never scan me". A class
       explicitly bound with ``group=`` is a public declaration, so it earns
       the exemption the same way a display-only module earns one below.
    2. To satisfy the "module must contain something worth importing" rule,
       since a declaration module deliberately defines no jobs — exactly the
       case ``DisplayClassPreFilter`` exists for.

    Satisfies the ``ModulePreFilter`` Protocol via structural typing.
    """

    def should_import(self, source_file: Path) -> bool:
        """Return True if any top-level class derives from ``GroupOptions``."""
        try:
            source = source_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(source_file))
        except (OSError, SyntaxError):
            return False

        for node in ast.iter_child_nodes(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for base in node.bases:
                # Matches both `GroupOptions` and a dotted `job.GroupOptions`.
                if isinstance(base, ast.Name) and base.id == "GroupOptions":
                    return True
                if isinstance(base, ast.Attribute) and base.attr == "GroupOptions":
                    return True
        return False


class FilePrefixPreFilter:
    """Only pass files whose stem starts with the specified prefix.

    Operates on the file stem only (filename without extension), not the
    directory path or `.py` extension.

    Args:
        prefix: The string that the file stem must start with.

    Satisfies the ``ModulePreFilter`` Protocol via structural typing.
    """

    def __init__(self, prefix: str) -> None:
        self._prefix = prefix

    def should_import(self, source_file: Path) -> bool:
        """Return True if the file stem starts with the configured prefix."""
        return source_file.stem.startswith(self._prefix)


class FilePostfixPreFilter:
    """Only pass files whose stem ends with the specified postfix.

    Operates on the file stem only (filename without extension), not the
    directory path or `.py` extension.

    Args:
        postfix: The string that the file stem must end with.

    Satisfies the ``ModulePreFilter`` Protocol via structural typing.
    """

    def __init__(self, postfix: str) -> None:
        self._postfix = postfix

    def should_import(self, source_file: Path) -> bool:
        """Return True if the file stem ends with the configured postfix."""
        return source_file.stem.endswith(self._postfix)


class ImportModulePreFilter:
    """Require the file to import from a specified package (via AST).

    Parses the source file's AST and returns True if any ``import`` or
    ``from ... import`` statement references a module whose path starts
    with the configured package name. Detects imports at the module top
    level as well as those nested inside ``try``/``except`` and ``if``
    blocks at module level.

    Args:
        package: The package name to look for (e.g. ``"functualize"``).

    Satisfies the ``ModulePreFilter`` Protocol via structural typing.
    """

    def __init__(self, package: str) -> None:
        self._package = package

    def should_import(self, source_file: Path) -> bool:
        """Return True if the file imports from the configured package."""
        try:
            source = source_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(source_file))
        except (OSError, SyntaxError):
            return False

        return self._has_matching_import(tree.body)

    def _has_matching_import(self, stmts: list[ast.stmt]) -> bool:
        """Recursively check statements for matching imports.

        Walks into try/except and if blocks at module level to find
        conditional imports (e.g. ``try: import pkg`` patterns).
        """
        for node in stmts:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if self._matches(alias.name):
                        return True
            elif isinstance(node, ast.ImportFrom):
                if node.module and self._matches(node.module):
                    return True
            elif isinstance(node, ast.Try):
                if self._has_matching_import(node.body):
                    return True
                for handler in node.handlers:
                    if self._has_matching_import(handler.body):
                        return True
                if self._has_matching_import(node.orelse):
                    return True
                if self._has_matching_import(node.finalbody):
                    return True
            elif isinstance(node, ast.If):
                if self._has_matching_import(node.body):
                    return True
                if self._has_matching_import(node.orelse):
                    return True
        return False

    def _matches(self, module_path: str) -> bool:
        """Check if a module path starts with the configured package name."""
        return module_path == self._package or module_path.startswith(
            self._package + "."
        )


class MarkerModulePreFilter:
    """Require a named module-level variable to be present.

    Parses the source file's AST and returns True only if there is a
    top-level assignment to the specified marker variable name.

    Args:
        marker: The variable name to look for (default: ``"__functualize__"``).

    Satisfies the ``ModulePreFilter`` Protocol via structural typing.
    """

    def __init__(self, marker: str = "__functualize__") -> None:
        self._marker = marker

    def should_import(self, source_file: Path) -> bool:
        """Return True if the file contains a top-level assignment to the marker."""
        try:
            source = source_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(source_file))
        except (OSError, SyntaxError):
            return False

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == self._marker:
                        return True
            elif (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == self._marker
            ):
                return True
        return False


def extract_decorator_root_name(node: ast.expr) -> str | None:
    """Extract the root (leftmost) name from a decorator AST node.

    Handles:
    - Name: ``@job`` → "job"
    - Call: ``@job(...)`` → unwrap to func, then recurse
    - Attribute: ``@foo.bar`` → walk left to the Name node
    - Call wrapping Attribute: ``@foo.bar(...)`` → "foo"
    """
    # Unwrap Call nodes: @job(...) → get the function being called
    if isinstance(node, ast.Call):
        node = node.func

    # Walk Attribute chain to the leftmost Name: @foo.bar.baz → "foo"
    while isinstance(node, ast.Attribute):
        node = node.value

    if isinstance(node, ast.Name):
        return node.id

    return None


def extract_function_decorators(source_file: Path) -> dict[str, tuple[str, ...]]:
    """Map each top-level function name to its decorator root names (via AST).

    The per-function counterpart to :class:`DecoratorModulePreFilter`, which can
    only answer "does this *file* contain a decorated function". Job-level
    filters (``require_job_decorators``) need to know which *functions* carry
    the decorator, and decorators are not reliably introspectable after import
    (a transparent wrapper leaves no trace on the resulting object), so the
    names are read from the source AST at extraction time and carried on the
    descriptor.

    Returns an empty mapping when the file cannot be read or parsed; callers
    treat that as "no decorators known", so a job-level decorator filter
    rejects the module rather than silently admitting it.
    """
    try:
        source = source_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(source_file))
    except (OSError, SyntaxError):
        return {}

    result: dict[str, tuple[str, ...]] = {}
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            names = tuple(
                name
                for name in (
                    extract_decorator_root_name(d) for d in node.decorator_list
                )
                if name is not None
            )
            result[node.name] = names
    return result


class DecoratorModulePreFilter:
    """Require at least one function with a qualifying decorator (via AST).

    Parses the source file's AST and returns True if any top-level function
    or async function definition has a decorator whose root name matches one
    of the configured decorator names.

    Root name extraction:
    - ``@job`` → root name is "job"
    - ``@job(...)`` → root name is "job" (Call node, unwrap func)
    - ``@foo.bar`` → root name is "foo" (Attribute node, walk to leftmost Name)
    - ``@foo.bar(...)`` → root name is "foo" (Call wrapping Attribute)

    Args:
        decorator_names: Tuple of decorator root names to match against.

    Satisfies the ``ModulePreFilter`` Protocol via structural typing.
    """

    def __init__(self, decorator_names: tuple[str, ...]) -> None:
        self._names = set(decorator_names)

    def should_import(self, source_file: Path) -> bool:
        """Return True if any top-level function has a matching decorator."""
        try:
            source = source_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(source_file))
        except (OSError, SyntaxError):
            return False

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                for decorator in node.decorator_list:
                    root = self._extract_root_name(decorator)
                    if root in self._names:
                        return True
        return False

    _extract_root_name = staticmethod(extract_decorator_root_name)


class GlobExcludePreFilter:
    """Exclude files matching any glob pattern (evaluated against relative path).

    Matches the file's path relative to ``base_dir`` against each configured
    pattern using :mod:`fnmatch` semantics (``*``, ``**``, ``?`` wildcards).

    Args:
        patterns: One or more glob pattern strings. All must be non-empty.
        base_dir: The base directory against which file paths are relativized.

    Raises:
        ValueError: If ``patterns`` is empty or contains any empty string.

    Satisfies the ``ModulePreFilter`` Protocol via structural typing.
    """

    def __init__(self, patterns: tuple[str, ...], base_dir: Path) -> None:
        if not patterns:
            raise ValueError("All glob patterns must be non-empty strings")
        for i, p in enumerate(patterns):
            if not isinstance(p, str) or not p:
                raise ValueError(
                    f"All glob patterns must be non-empty strings "
                    f"(pattern at index {i} is invalid)"
                )
        self._patterns = patterns
        self._base_dir = base_dir

    def should_import(self, source_file: Path) -> bool:
        """Return False if the file matches any exclusion pattern."""
        try:
            rel_path = source_file.relative_to(self._base_dir)
        except ValueError:
            # File is not under base_dir — cannot match, allow through
            return True

        rel_str = str(rel_path)

        return all(not fnmatch.fnmatch(rel_str, pattern) for pattern in self._patterns)
