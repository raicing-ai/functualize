"""ConfigSnapshotStore persistence for execution history.

Pure-logic module with no Textual dependency. Records and retrieves
config snapshots from past executions for diff and session history features.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_VALID_OUTCOMES = frozenset({"success", "failure", "cancelled"})


@dataclass(frozen=True)
class ConfigSnapshot:
    """Immutable record of config values used in a past execution.

    Attributes:
        job_name: The job this snapshot is for.
        timestamp: Unix epoch float when the execution occurred.
        values: Mapping of field names to their values at execution time.
        outcome: Execution result — one of "success", "failure", or "cancelled".
    """

    job_name: str
    timestamp: float
    values: dict[str, Any]
    outcome: str


class ConfigSnapshotStore:
    """Persists config snapshots across sessions.

    Stores execution history keyed by job name, with configurable
    max retention per job.

    Args:
        path: File path for JSON persistence. None means in-memory only.
        max_retention: Maximum snapshots to retain per job (default: 50).
    """

    def __init__(self, path: Path | None = None, max_retention: int = 50) -> None:
        self._path = path
        self._max_retention = max_retention
        self._snapshots: dict[str, list[ConfigSnapshot]] = {}

    def record(self, job_name: str, values: dict[str, Any], outcome: str) -> None:
        """Record a config snapshot after execution.

        Args:
            job_name: The job that was executed.
            values: The field values used during execution.
            outcome: The execution outcome.

        Raises:
            ValueError: If outcome is not a valid value.
        """
        if outcome not in _VALID_OUTCOMES:
            msg = (
                f"Invalid outcome {outcome!r}; must be one of {sorted(_VALID_OUTCOMES)}"
            )
            raise ValueError(msg)

        snapshot = ConfigSnapshot(
            job_name=job_name,
            timestamp=time.time(),
            values=values,
            outcome=outcome,
        )

        if job_name not in self._snapshots:
            self._snapshots[job_name] = []

        self._snapshots[job_name].append(snapshot)

        # Enforce retention limit
        if len(self._snapshots[job_name]) > self._max_retention:
            self._snapshots[job_name] = self._snapshots[job_name][
                -self._max_retention :
            ]

    def get_last_snapshot(self, job_name: str) -> ConfigSnapshot | None:
        """Get the most recently recorded snapshot for a job.

        Args:
            job_name: The job to look up.

        Returns:
            The most recent ConfigSnapshot, or None if no history exists.
        """
        snapshots = self._snapshots.get(job_name, [])
        return snapshots[-1] if snapshots else None

    def get_snapshots(self, job_name: str, limit: int = 10) -> list[ConfigSnapshot]:
        """Get recent snapshots for a job in reverse chronological order.

        Args:
            job_name: The job to look up.
            limit: Maximum number of snapshots to return. Returns empty
                list if limit <= 0.

        Returns:
            List of snapshots in reverse chronological order.
        """
        if limit <= 0:
            return []
        snapshots = self._snapshots.get(job_name, [])
        return list(reversed(snapshots[-limit:]))

    def to_dict(self) -> dict[str, Any]:
        """Serialize the store to a dict for JSON persistence.

        Returns:
            A dict representation of all stored snapshots.
        """
        data: dict[str, Any] = {}
        for job_name, snapshots in self._snapshots.items():
            data[job_name] = [
                {
                    "job_name": s.job_name,
                    "timestamp": s.timestamp,
                    "values": s.values,
                    "outcome": s.outcome,
                }
                for s in snapshots
            ]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConfigSnapshotStore:
        """Deserialize a store from a dict.

        Args:
            data: A dict previously produced by to_dict().

        Returns:
            A new ConfigSnapshotStore with the deserialized snapshots.
        """
        store = cls()
        for job_name, snapshot_list in data.items():
            store._snapshots[job_name] = [
                ConfigSnapshot(
                    job_name=s["job_name"],
                    timestamp=s["timestamp"],
                    values=s["values"],
                    outcome=s["outcome"],
                )
                for s in snapshot_list
            ]
        return store

    @classmethod
    def load(cls, path: Path | None = None) -> ConfigSnapshotStore:
        """Load a store from disk.

        If the file doesn't exist, returns an empty store. If the file
        is corrupted (invalid JSON), renames it to .bak and returns empty.

        Args:
            path: Path to the JSON file. Defaults to XDG data directory.

        Returns:
            A ConfigSnapshotStore loaded from disk or empty on failure.
        """
        if path is None:
            path = cls._default_path()

        if not path.exists():
            store = cls(path=path)
            return store

        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            # Corrupted file — rename to .bak
            bak_path = path.with_suffix(path.suffix + ".bak")
            try:
                path.rename(bak_path)
                logger.warning(
                    "Corrupted snapshot file renamed to %s; starting fresh",
                    bak_path,
                )
            except OSError:
                logger.warning(
                    "Could not rename corrupted snapshot file %s; starting fresh",
                    path,
                )
            store = cls(path=path)
            return store

        store = cls.from_dict(data)
        store._path = path
        return store

    def flush(self) -> None:
        """Atomically write store to disk using tempfile + os.replace.

        No-op if path is None.
        """
        if self._path is None:
            return

        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(self.to_dict(), indent=2)

        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self._path.parent),
                suffix=".tmp",
            )
            try:
                os.write(fd, data.encode("utf-8"))
            finally:
                os.close(fd)
            os.replace(tmp_path, str(self._path))
        except OSError:
            logger.warning(
                "Failed to write snapshot file to %s",
                self._path,
                exc_info=True,
            )

    @staticmethod
    def _default_path() -> Path:
        """Get the default storage path using XDG_DATA_HOME.

        Returns:
            Path to the default snapshot JSON file.
        """
        xdg_data = os.environ.get("XDG_DATA_HOME", "")
        base = Path(xdg_data) if xdg_data else Path.home() / ".local" / "share"
        return base / "functualize" / "config_snapshots.json"
