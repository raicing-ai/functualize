"""Per-job, per-field argument history with JSON persistence.

Records argument values used in previous invocations, indexed by job name
and field name. Supports configurable max entries with oldest-first eviction,
consecutive duplicate avoidance, and JSON serialization for disk persistence.

This module is in the ``_cli/`` layer — it uses only stdlib.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ArgumentHistory:
    """Per-job, per-field argument history with JSON persistence.

    Thread-safe for single-writer (TUI) usage. History is loaded
    at boot and flushed on shutdown.

    Internal storage keeps values in chronological order (oldest first).
    The public ``get_history`` method returns them in reverse chronological
    order (most recent first).
    """

    _store: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    _max_entries: int = 50
    _path: Path | None = None
    _dirty: bool = False

    def record(self, job_name: str, field_name: str, value: str) -> None:
        """Append value, skip consecutive duplicates, enforce max.

        Args:
            job_name: The job that was invoked.
            field_name: The field/parameter name.
            value: The string value that was used.
        """
        job_fields = self._store.setdefault(job_name, {})
        history = job_fields.setdefault(field_name, [])

        # Consecutive duplicate avoidance: skip if last entry is identical
        if history and history[-1] == value:
            return

        history.append(value)

        # Enforce max_entries by evicting oldest (front of list)
        if len(history) > self._max_entries:
            del history[: len(history) - self._max_entries]

        self._dirty = True

    def get_history(self, job_name: str, field_name: str) -> list[str]:
        """Return history values in reverse chronological order.

        Args:
            job_name: The job name to look up.
            field_name: The field name to look up.

        Returns:
            List of values, most recent first. Empty if no history exists.
        """
        job_fields = self._store.get(job_name)
        if job_fields is None:
            return []
        history = job_fields.get(field_name)
        if history is None:
            return []
        return list(reversed(history))

    def has_history(self, job_name: str) -> bool:
        """Check if any history exists for a job.

        Args:
            job_name: The job name to check.

        Returns:
            ``True`` if at least one field has recorded values for this job.
        """
        job_fields = self._store.get(job_name)
        if job_fields is None:
            return False
        return any(bool(values) for values in job_fields.values())

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict.

        Returns:
            A dict with ``version`` and ``history`` keys suitable for
            ``json.dumps()``.
        """
        return {
            "version": 1,
            "history": {
                job_name: {
                    field_name: list(values) for field_name, values in fields.items()
                }
                for job_name, fields in self._store.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], max_entries: int = 50) -> ArgumentHistory:
        """Reconstruct from deserialized JSON dict.

        Args:
            data: A dict previously produced by ``to_dict()``.
            max_entries: Maximum entries per job-field pair.

        Returns:
            A new ``ArgumentHistory`` instance with the restored state.
        """
        history_data: dict[str, dict[str, list[str]]] = data.get("history", {})
        store: dict[str, dict[str, list[str]]] = {}

        for job_name, fields in history_data.items():
            store[job_name] = {}
            for field_name, values in fields.items():
                # Enforce max_entries on load (keep most recent)
                if len(values) > max_entries:
                    values = values[-max_entries:]
                store[job_name][field_name] = list(values)

        instance = cls(
            _store=store,
            _max_entries=max_entries,
            _path=None,
            _dirty=False,
        )
        return instance

    @staticmethod
    def _default_path() -> Path:
        """XDG data dir: ~/.local/share/functualize/argument_history.json.

        Uses ``XDG_DATA_HOME`` environment variable if set, otherwise
        falls back to ``~/.local/share/functualize/``.
        """
        xdg_data_home = os.environ.get("XDG_DATA_HOME")
        if xdg_data_home:
            base = Path(xdg_data_home)
        else:
            base = Path.home() / ".local" / "share"
        return base / "functualize" / "argument_history.json"

    @classmethod
    def load(cls, path: Path | None = None, max_entries: int = 50) -> ArgumentHistory:
        """Load from XDG data dir or given path. Returns empty on failure.

        Args:
            path: Explicit path to the history JSON file. If ``None``,
                uses :meth:`_default_path`.
            max_entries: Maximum entries per job-field pair.

        Returns:
            A populated ``ArgumentHistory`` if the file exists and is valid,
            otherwise an empty instance.
        """
        resolved_path = path if path is not None else cls._default_path()

        if not resolved_path.exists():
            logger.debug("History file does not exist: %s", resolved_path)
            return cls(
                _store={},
                _max_entries=max_entries,
                _path=resolved_path,
                _dirty=False,
            )

        try:
            raw = resolved_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            # Corrupted or unreadable file — rename to .bak and start fresh
            logger.warning(
                "Corrupted history file %s: %s. Renaming to .bak and "
                "initializing empty.",
                resolved_path,
                exc,
            )
            bak_path = resolved_path.with_suffix(".json.bak")
            try:
                os.replace(str(resolved_path), str(bak_path))
            except OSError as rename_exc:
                logger.warning(
                    "Failed to rename corrupted file to %s: %s",
                    bak_path,
                    rename_exc,
                )
            return cls(
                _store={},
                _max_entries=max_entries,
                _path=resolved_path,
                _dirty=False,
            )

        instance = cls.from_dict(data, max_entries=max_entries)
        instance._path = resolved_path
        return instance

    def flush(self) -> None:
        """Write to disk atomically (temp file + rename).

        Uses :func:`tempfile.NamedTemporaryFile` to write to a temporary
        file in the same directory, then :func:`os.replace` for an atomic
        rename. Creates parent directories if they do not exist.

        Only writes if the instance is dirty (has unsaved changes).
        """
        if not self._dirty:
            return

        path = self._path if self._path is not None else self._default_path()

        # Ensure parent directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        data = self.to_dict()
        payload = json.dumps(data, indent=2, ensure_ascii=False)

        # Atomic write: write to temp file in same directory, then rename
        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(path.parent),
                suffix=".tmp",
                delete=False,
            ) as fd:
                tmp_path = fd.name
                fd.write(payload)
                fd.flush()
                os.fsync(fd.fileno())
            os.replace(tmp_path, str(path))
        except OSError as exc:
            logger.error("Failed to flush history to %s: %s", path, exc)
            # Clean up temp file if it still exists
            if tmp_path:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)
            return

        self._dirty = False
