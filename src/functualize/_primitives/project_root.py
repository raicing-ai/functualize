"""Where a project stops — the one answer every walk asks.

A project is found by walking upward from the working directory, and four walks
used to do it, each with its own stop: walk A (project config, job and library
directories, the settings list) stopped at the filesystem root and honoured
``root = true`` only while *merging*; walk B (job configuration) stopped at
``~``; walk C (the ``.functualize/`` folder: mode, state, plugins) stopped at the
first folder it met. So a nested project that declared ``root = true`` still
ran its ancestor's jobs, adopted its ancestor's state, and read its ancestor's
job configuration — while ``builtin config path`` showed the ancestor as no part
of it.

This module owns the rule instead:

- :data:`PROJECT_CONFIG_CANDIDATES` — which files in a directory are project
  config, and in which order, **derived** from the one declaration in
  ``_types/settings.py``;
- :func:`is_root_config` — the one ``root = true`` predicate;
- :func:`find_project_boundary` — the nearest directory that declares it;
- :func:`find_functualize_dir` — walk C, which no longer crosses that boundary;
- :func:`project_identity_dir` — the directory a project's state, cache and
  vault are keyed by.

It lives in ``_primitives`` because walk C does: the ``.functualize/`` lookup is
called by readers that must not boot (the CLI fast path, completions, the MCP
translator), so the boundary has to be answerable from the bottom layer without
threading a parameter through every one of them. Imports ``_types`` and the
sibling ``locator``; nothing else internal.
"""

from __future__ import annotations

import functools
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize._primitives.locator import ResourceLocator
from functualize._types.settings import (
    PROJECT_FILE_NAMES,
    PROJECT_FILE_SECTION_PREFIXES,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from functualize._primitives.locator import Candidate

__all__ = [
    "PROJECT_CONFIG_CANDIDATES",
    "ROOT_KEY",
    "find_functualize_dir",
    "find_project_boundary",
    "is_root_config",
    "project_config_at",
    "project_config_file_table",
    "project_identity_dir",
]

#: The key a project file sets to declare itself the top of its project.
ROOT_KEY = "root"


def _parse_toml(path: Path) -> dict[str, Any] | None:
    """Parse ``path``, or None when it cannot be read or is not TOML."""
    try:
        return tomllib.loads(path.read_bytes().decode("utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return None


def _table(data: Mapping[str, Any], prefix: str) -> dict[str, Any] | None:
    """The table at dotted ``prefix`` inside ``data``, or None if absent."""
    table: Any = data
    for key in prefix.split("."):
        table = table.get(key) if isinstance(table, dict) else None
    return table if isinstance(table, dict) else None


def _extract_table(prefix: str, path: Path) -> dict[str, Any] | None:
    """A candidate extractor: ``path``'s ``prefix`` table, or None.

    None means "this file is not a project file" — a ``pyproject.toml`` without
    a ``[tool.functualize]`` table is somebody else's file, and the walk must
    look at the next candidate in the same directory rather than stop on it.
    """
    data = _parse_toml(path)
    return _table(data, prefix) if data is not None else None


#: Candidate list for the per-directory project config read. Order within the
#: list is priority within one directory (first match wins). Derived, never
#: written out: a shared file named in ``PROJECT_FILE_SECTION_PREFIXES`` becomes
#: ``(name, extractor of its table)``, any other name is read whole.
PROJECT_CONFIG_CANDIDATES: list[Candidate] = [
    (name, functools.partial(_extract_table, PROJECT_FILE_SECTION_PREFIXES[name]))
    if name in PROJECT_FILE_SECTION_PREFIXES
    else name
    for name in PROJECT_FILE_NAMES
]


def project_config_file_table(path: Path) -> tuple[dict[str, Any], str]:
    """``(func's values in path, the table they live under)`` for a settings file.

    A file func shares with other tools (``pyproject.toml``) holds its values
    under a table; any other file holds them at the top level, with prefix
    ``""``. A file that is missing or unreadable contributes ``{}``.
    """
    prefix = PROJECT_FILE_SECTION_PREFIXES.get(path.name, "")
    data = _parse_toml(path) if path.is_file() else None
    if data is None:
        return {}, prefix
    if not prefix:
        return data, prefix
    return _table(data, prefix) or {}, prefix


def is_root_config(config: Mapping[str, Any]) -> bool:
    """Whether a project config layer declares itself the top of its project.

    Only the boolean ``true`` counts. ``root = "true"`` is a string, and a
    string that happens to read like a boolean does not end a walk.
    """
    return config.get(ROOT_KEY) is True


def project_config_at(directory: Path) -> dict[str, Any] | None:
    """The project config ``directory`` itself holds, or None.

    The same per-directory first-match rule the project walk uses, so "does
    this directory declare a root?" is asked of exactly the layer that walk
    would merge.
    """
    found = (
        ResourceLocator()
        .search_explicit(directory)
        .resolve_first_candidate(PROJECT_CONFIG_CANDIDATES)
    )
    return found[1] if found is not None else None


def _declares_root(directory: Path) -> bool:
    config = project_config_at(directory)
    return config is not None and is_root_config(config)


def find_project_boundary(start: Path) -> Path | None:
    """The nearest directory, from ``start`` upward, whose config says ``root = true``.

    None when no project file on the way up declares a root: the walk is then
    unbounded, which is the inheritance a monorepo without a root relies on.
    """
    current = Path(start).resolve()
    while True:
        if _declares_root(current):
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def find_functualize_dir(start: Path) -> Path | None:
    """Search upward from ``start`` for a ``.functualize/`` directory.

    The project-root walk — "walk C" of the declared-plugin-directories
    study (2026-09-19; the decisions survive in `.spec/STATUS.md`). Returns the
    ``.functualize/`` directory itself, or None in standalone mode (no such
    directory between ``start`` and the project boundary). **Bounded by the
    project boundary, inclusive:** a ``.functualize/`` *in* the directory that
    declares ``root = true`` is found; one above it is another project's, and
    the walk ends there with None. With no boundary it runs to the filesystem
    root, as it always did.

    **This used to exist twice**, in ``cache_format.py`` and ``fresh_format.py``,
    and the two were *not* identical however much they looked it: the freshness
    copy did ``Path(start).resolve()`` first and the cache copy did not. Measured
    from ``<root>/sub/deep`` with ``.functualize/`` at ``<root>``::

        cache_format(Path("."))  -> None          # `.`.parent is `.`; walk ends at once
        fresh_format(Path("."))  -> <root>/.functualize

    They agreed only when the caller had already passed an absolute path. Every
    caller does today — ``Path.cwd()``, or a path the caller resolved first — so
    the resolving form is adopted here: it is what the two agreed on in practice,
    and it closes a latent bug where ``resolve_cache_path`` would silently answer
    *standalone* for a relative argument.

    Note for anyone re-collapsing this: both ``cache_format`` and ``fresh_format``
    must **bind this name into their own namespace** and call it unqualified.
    ``tests/conftest.py::_isolate_state_root`` monkeypatches ``fresh_format``'s
    binding *only*, to sandbox runtime state into ``tmp_path`` while leaving the
    discovery cache alone. A qualified ``project_root.find_functualize_dir(...)``
    call would slip that patch — and the suite would stay green while tests wrote
    durable state outside ``tmp_path``, which is exactly the flake that fixture
    exists to stop.
    """
    current = Path(start).resolve()
    while True:
        candidate = current / ".functualize"
        if candidate.is_dir():
            return candidate
        if _declares_root(current):
            return None
        parent = current.parent
        if parent == current:
            return None
        current = parent


def project_identity_dir(start: Path) -> Path:
    """The directory a project's state, cache and vault are keyed by.

    In order: the parent of the project's ``.functualize/``; else the directory
    that declares ``root = true``, so a root and every subfolder of it share one
    identity even without a ``.functualize/``; else ``start`` itself — a loose
    directory with neither is its own project, as before.
    """
    functualize_dir = find_functualize_dir(start)
    if functualize_dir is not None:
        return functualize_dir.parent
    return find_project_boundary(start) or Path(start).resolve()
