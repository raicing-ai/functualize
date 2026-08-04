"""Providers that adapt a domain to ``SourceChainProvider``.

``JobConfigChainProvider`` covers job config; ``FuncSettingsChainProvider``
covers `func`'s own settings. Together they are what lets one Detail view
serve the Config Files, Settings, and Settings Files panels.

**Why these re-read files from disk.** The kernel parses config files once at
boot and reuses the result for every lookup (a deliberate invariant — zero
per-invocation file I/O). That makes the kernel's view stale the instant the
Detail screen saves, which would make a saved edit appear not to have taken.
So the kernel supplies the authoritative *discovery* (which files exist, in
what precedence order, via ``config_file_paths``/``config_file_values``) while
the provider reads *content* fresh on each ``resolve()``. Parsing TOML in
``_cli/`` is the established precedent here — ``config_files.py`` already does
it in ``_extract_fields_from_file``.

This module is in the ``_cli/`` layer — public API + stdlib only.
"""

from __future__ import annotations

import os
import tomllib
from typing import TYPE_CHECKING, Any

from functualize._cli.data.config_target import ConfigTarget
from functualize._cli.data.toml_writer import write_toml_section
from functualize._cli.tui.models.source_chain import (
    NOT_SET,
    ResolvedKey,
    SourceEntry,
)

if TYPE_CHECKING:
    from pathlib import Path

    from functualize._cli.data.func_settings import FuncSettingsStore
    from functualize._cli.tui.panels.config_table import FieldDef

__all__ = [
    "FileScope",
    "FuncSettingsChainProvider",
    "JobConfigChainProvider",
    "file_source_id",
]

# Precedence, ascending. Mirrors the order the TUI's own chain already uses
# (see chain_resolution.build_command_panels, which picks the first non-empty
# of CLI, Env, File, Remote, Default) — Remote sits *below* File there, so it
# does here too rather than inventing a second, disagreeing order.
PRECEDENCE_DEFAULT = 0
PRECEDENCE_REMOTE = 10
PRECEDENCE_FILE_BASE = 20
PRECEDENCE_ENV = 90
PRECEDENCE_CLI = 100


def file_source_id(path: Path | str) -> str:
    """The concrete source id for a config file."""
    return f"file:{path}"


class FileScope:
    """One config file participating in a job's chain."""

    def __init__(self, path: Path, section: str, display_name: str) -> None:
        self.path = path
        self.section = section
        self.display_name = display_name

    @property
    def source_id(self) -> str:
        """This file's concrete source id."""
        return file_source_id(self.path)

    @property
    def writable(self) -> bool:
        """Whether the Detail view may stage edits against this file.

        A file that doesn't exist yet counts as writable when its directory
        is — that is how a user creates config from the TUI.
        """
        if self.path.exists():
            return os.access(self.path, os.W_OK)
        parent = self.path.parent
        while not parent.exists() and parent.parent != parent:
            parent = parent.parent
        return os.access(parent, os.W_OK)


def _read_section(path: Path, section: str) -> dict[str, Any]:
    """Parse ``path`` and return ``section``'s table, or {} on any failure."""
    try:
        with path.open("rb") as fh:
            data: Any = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}

    for part in section.split("."):
        if not isinstance(data, dict):
            return {}
        data = data.get(part)
    return data if isinstance(data, dict) else {}


def _scalar_to_str(value: Any) -> str:
    """Render a parsed TOML scalar the way the tables display it."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ",".join(str(v) for v in value)
    return str(value)


class JobConfigChainProvider:
    """Job config, with the file layer decomposed per file.

    The kernel deep-merges every config file into one view and reports a
    single generic ``"File"`` chain entry, so the old detail view had to guess
    which file a value came from by comparing merged values. This expands that
    one entry into one ``SourceEntry`` per file, using real per-file content.
    """

    def __init__(
        self,
        fields: list[FieldDef],
        files: list[FileScope],
    ) -> None:
        """
        Args:
            fields: The job's resolved FieldDefs — the source of the non-file
                chain layers (CLI/Env/Remote/Default), plus type and choice
                metadata. PLAIN params are dropped: they resolve straight from
                CLI/default and never participate in file resolution, so
                showing them on a file's Detail screen would invite an edit
                that could not take effect (R5-AC5).
            files: Config files in kernel discovery order (highest priority
                first), which is the order ``config_file_paths()`` returns.
        """
        from functualize._cli.tui.panels.config_table import ParamKind

        self._fields = [f for f in fields if f.param_kind is ParamKind.CONFIG]
        self._files = list(files)

    @property
    def files(self) -> list[FileScope]:
        """The files participating in this chain."""
        return list(self._files)

    def _chain_value(self, field: FieldDef, source: str) -> str:
        """Pull one of the kernel-derived chain layers off a FieldDef."""
        for entry in field.chain:
            if entry.source.lower() == source:
                return entry.value or ""
        return ""

    def resolve(self) -> list[ResolvedKey]:
        """Re-read every file and rebuild each field's full chain."""
        # Read each file once, not once per field.
        per_file: list[tuple[FileScope, dict[str, Any]]] = [
            (scope, _read_section(scope.path, scope.section)) for scope in self._files
        ]

        keys: list[ResolvedKey] = []
        for field in self._fields:
            chain: list[SourceEntry] = [
                SourceEntry(
                    source_id="default",
                    label="Default",
                    value=self._chain_value(field, "default") or NOT_SET,
                    writable=False,
                    precedence=PRECEDENCE_DEFAULT,
                ),
                SourceEntry(
                    source_id="remote",
                    label="Remote",
                    value=self._chain_value(field, "remote") or NOT_SET,
                    writable=False,
                    precedence=PRECEDENCE_REMOTE,
                ),
            ]

            # Files: earlier-discovered wins, so give the first file the
            # highest precedence within the file band.
            count = len(per_file)
            for index, (scope, data) in enumerate(per_file):
                raw = data.get(field.name)
                chain.append(
                    SourceEntry(
                        source_id=scope.source_id,
                        label=scope.display_name,
                        value=(_scalar_to_str(raw) if field.name in data else NOT_SET),
                        writable=scope.writable,
                        precedence=PRECEDENCE_FILE_BASE + (count - 1 - index),
                    )
                )

            chain.append(
                SourceEntry(
                    source_id="env",
                    label="Env",
                    value=self._chain_value(field, "env") or NOT_SET,
                    writable=False,
                    precedence=PRECEDENCE_ENV,
                )
            )
            chain.append(
                SourceEntry(
                    source_id="cli",
                    label="CLI",
                    value=self._chain_value(field, "cli") or NOT_SET,
                    writable=False,
                    precedence=PRECEDENCE_CLI,
                )
            )

            keys.append(
                ResolvedKey(
                    name=field.name,
                    chain=chain,
                    description=field.description,
                    type_hint=field.type_annotation or "str",
                    choices=field.choices,
                )
            )
        return keys

    def _scope_for(self, source_id: str) -> FileScope | None:
        return next((s for s in self._files if s.source_id == source_id), None)

    def target_for(self, source_id: str) -> ConfigTarget | None:
        """Describe the file behind ``source_id``, if it is writable."""
        scope = self._scope_for(source_id)
        if scope is None or not scope.writable:
            return None
        return ConfigTarget(
            type="file",
            label=scope.display_name,
            detail=str(scope.path),
            path=scope.path,
        )

    def write(
        self,
        source_id: str,
        edits: dict[str, str],
        removals: set[str],
    ) -> None:
        """Write staged changes into one config file, atomically.

        Raises:
            ValueError: If ``source_id`` is not a writable file in this chain.
        """
        scope = self._scope_for(source_id)
        if scope is None:
            raise ValueError(f"Unknown config file source: {source_id}")
        if not scope.writable:
            raise ValueError(f"Config file is not writable: {scope.path}")

        hints = {
            f.name: f.type_annotation
            for f in self._fields
            if f.type_annotation and f.name in edits
        }
        write_toml_section(scope.path, scope.section, edits, removals, hints)

    def apply_live(self, edits: dict[str, str]) -> None:
        """No-op: job config takes effect when the job runs, not before."""


class FuncSettingsChainProvider:
    """`func`'s own settings, backed by ``FuncSettingsStore``.

    The chain spans the real config files (global ``config.toml``, project
    ``.functualize.toml`` / ``pyproject.toml [tool.functualize]``) plus
    ``FUNCTUALIZE_*`` env — the same layers ``resolve_cli_config`` merges.

    ``apply_live`` is the part that matters here and has no job-config
    equivalent: a saved theme has to take effect immediately, or saving it
    looks like it did nothing.
    """

    def __init__(
        self,
        store: FuncSettingsStore,
        *,
        apply_hook: Any = None,
    ) -> None:
        """
        Args:
            store: The settings chain to read and write.
            apply_hook: Optional ``callable(edits: dict[str, str])`` invoked
                after a successful save, to push values into the running app.
                Edits are keyed by dotted setting name (``tui.theme``).
        """
        self._store = store
        self._apply_hook = apply_hook

    @property
    def store(self) -> FuncSettingsStore:
        """The underlying settings store."""
        return self._store

    def resolve(self) -> list[ResolvedKey]:
        """Re-read every settings source."""
        self._store.refresh()
        return self._store.resolve()

    def _path_for(self, source_id: str) -> Path | None:
        """Map a file source id back to its path, if it is one of ours."""
        for info in self._store.layers:
            if source_id == file_source_id(info.path):
                return info.path
        return None

    def target_for(self, source_id: str) -> ConfigTarget | None:
        """Describe the settings file behind ``source_id``."""
        path = self._path_for(source_id)
        if path is None:
            return None
        label = "global config" if path == self._store.global_path else "project file"
        return ConfigTarget(type="file", label=label, detail=str(path), path=path)

    def write(
        self,
        source_id: str,
        edits: dict[str, str],
        removals: set[str],
    ) -> None:
        """Persist settings to the file behind ``source_id``.

        Edits are keyed by dotted setting name; the store maps each to the
        right section inside the file (``tui.theme`` → ``[tui] theme``, or
        ``[tool.functualize.tui]`` in a ``pyproject.toml``).

        Raises:
            ValueError: If ``source_id`` is not a writable settings file
                (env and default sources cannot be written).
        """
        path = self._path_for(source_id)
        if path is None:
            raise ValueError(f"Not a writable settings source: {source_id}")
        self._store.write(path, edits, removals)

    def apply_live(self, edits: dict[str, str]) -> None:
        """Push saved settings into the running app."""
        if self._apply_hook is not None:
            self._apply_hook(edits)
