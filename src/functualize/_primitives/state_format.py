"""Shared runtime-state format: single source of truth for the state file.

The runtime state store answers "what ran last, against which inputs" —
fingerprints, run history, session-scoped precondition results, and per-scope
workflow records. It is deliberately **separate from the discovery cache**
(proposal §D.3 Fix 2): the discovery cache answers "what jobs exist" and is
rebuilt whenever a source file or version changes, which would drop every
fingerprint because one file moved. Different lifecycle, different invalidation
rules, different file. `func cache clear` and `func state clear` never
invalidate each other.

Location mirrors the discovery cache (proposal Part F):
- Declared-project mode: `.functualize/state.json`
- Standalone mode: `$XDG_CACHE_HOME/functualize/<project_id>/state.json`

This module holds the format version, filename, location resolution, and the
tolerant load / locked atomic save so readers and writers never drift — the
same discipline as `cache_format.py`.

Record keys contain **no absolute paths** and record paths are project-relative,
so the format stays content-addressable-friendly (Part G: a future shared
fingerprint cache must not require a format break).

Lives in `_primitives/` (stdlib-only): no `_types`, no pydantic, no `_discovery`.
"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize._primitives.locator import _xdg_cache_dir, compute_project_id

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

# Current state file format version. Bump on any incompatible format change.
# A version mismatch discards the file (runtime state is derived, never a
# source of truth — the worst case is one extra run).
# v1 (2026-07-20): initial envelope — fingerprints (with the R4
# (mtime, size, sha256) stat short-circuit), scopes (per-scope step records,
# recorded branch choices, gate payloads, blocked position, epilogue record),
# history ring buffer, session precondition cache.
STATE_VERSION = 1

# State file name within the resolved directory (beside cache.json).
STATE_FILENAME = "state.json"

# Ring-buffer bound for the run-history section (`func history`).
HISTORY_LIMIT = 200

_SECTIONS: tuple[str, ...] = ("fingerprints", "scopes", "history", "session")


def empty_state() -> dict[str, Any]:
    """Return a fresh, fully-populated envelope (schema.md §1)."""
    return {
        "format_version": STATE_VERSION,
        "fingerprints": {},
        "scopes": {},
        "history": [],
        "session": {"preconditions": {}},
    }


def find_functualize_dir(start: Path) -> Path | None:
    """Search upward from ``start`` for a ``.functualize/`` directory."""
    current = Path(start).resolve()
    while True:
        candidate = current / ".functualize"
        if candidate.is_dir():
            return candidate
        parent = current.parent
        if parent == current:
            return None
        current = parent


#: The two places a freshness ledger can live. Pinned as exactly two strings so
#: a script can match on them.
STATE_MODES = ("project", "standalone")


def resolve_state_location(start: Path) -> tuple[Path, str, Path | None]:
    """Where the runtime state lives, and **which of the two modes** that is.

    Mirrors ``cache_format.resolve_cache_path`` so state lands beside the
    discovery cache in both modes:

    - ``project`` — a ``.functualize/`` directory was found walking upward, and
      the ledger lives inside it, versioned with the code it describes.
    - ``standalone`` — no such directory, so the ledger goes to the XDG cache
      keyed by ``project_id`` of ``start``.

    Standalone is the fallback rather than the failure: ``func`` is meant to run
    over loose scripts anywhere on the filesystem, and littering a
    ``.functualize/`` beside every one of them would be worse than a keyed cache
    directory. ``mkdir .functualize`` is the switch between the two.

    The mode is returned rather than re-derived by each caller because deriving
    it means repeating the upward walk, and two walks can disagree. Nothing
    reported which mode you were in, so a project could spend its whole life in
    standalone without noticing and then go looking for a ``state.json`` that
    was under a hashed directory in the home cache.

    Args:
        start: Project root (or cwd) to resolve from.

    Returns:
        ``(state_path, mode, functualize_dir)`` — the path (which may not exist
        yet), one of :data:`STATE_MODES`, and the directory that decided it, or
        None in standalone mode.
    """
    start = Path(start).resolve()
    functualize_dir = find_functualize_dir(start)
    if functualize_dir is not None:
        return functualize_dir / STATE_FILENAME, "project", functualize_dir
    project_id = compute_project_id(str(start))
    path = _xdg_cache_dir() / "functualize" / project_id / STATE_FILENAME
    return path, "standalone", None


def resolve_state_path(start: Path) -> Path:
    """Resolve the runtime state file path for a project.

    The path half of :func:`resolve_state_location`, which is where the rule
    lives — one upward walk, one answer.

    Args:
        start: Project root (or cwd) to resolve from.

    Returns:
        Absolute path where the state file lives (may not exist yet).
    """
    return resolve_state_location(start)[0]


def normalize_state(data: Any) -> dict[str, Any]:
    """Coerce loaded data into a valid envelope, filling missing sections.

    Anything unrecognizable (not a dict, wrong version) yields a fresh envelope
    rather than raising — runtime state is derived and always safe to discard.
    """
    if not isinstance(data, dict):
        return empty_state()
    if data.get("format_version") != STATE_VERSION:
        return empty_state()
    state = empty_state()
    for section in _SECTIONS:
        value = data.get(section)
        if isinstance(value, type(state[section])):
            state[section] = value
    if not isinstance(state["session"].get("preconditions"), dict):
        state["session"]["preconditions"] = {}
    return state


def load_state(path: Path | str) -> dict[str, Any]:
    """Load the state envelope, tolerating a missing, corrupt, or stale file.

    Never raises for bad content: a truncated write, hand-editing, or a format
    bump all degrade to an empty envelope.
    """
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return empty_state()
    try:
        return normalize_state(json.loads(raw))
    except (json.JSONDecodeError, ValueError):
        return empty_state()


def save_state(path: Path | str, state: dict[str, Any]) -> None:
    """Write the envelope atomically (tmp file + ``os.replace``).

    Atomic so a crash mid-write cannot leave a half-written file that the next
    run would discard. Callers that read-modify-write must hold
    :func:`state_lock` — or better, use :func:`update_state`.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(state)
    payload["format_version"] = STATE_VERSION
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        with suppress(OSError):
            os.unlink(tmp_name)
        raise


@contextmanager
def state_lock(path: Path | str, timeout: float = 10.0) -> Iterator[None]:
    """Hold an advisory lock on the state file for the block (Part F).

    Uses a ``.lock`` sidecar so the lock survives the atomic replace of the
    state file itself. Degrades to a no-op where OS locking is unavailable —
    the store is advisory-locked, not transactional.
    """
    lock_path = Path(path).with_name(Path(path).name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = None
    try:
        handle = open(lock_path, "a+")  # noqa: SIM115 — released in finally
        _acquire_lock(handle, timeout)
        yield
    finally:
        if handle is not None:
            _release_lock(handle)
            handle.close()


def _acquire_lock(handle: Any, timeout: float) -> None:
    """Best-effort exclusive lock; returns (unlocked) if unsupported."""
    try:
        import fcntl
    except ImportError:
        _acquire_lock_windows(handle, timeout)
        return
    import time as _time

    deadline = _time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError:
            if _time.monotonic() >= deadline:
                return  # advisory: proceed rather than deadlock a build
            _time.sleep(0.01)


def _msvcrt_locking() -> tuple[Any, Any, Any] | None:
    """Return ``(locking, LK_NBLCK, LK_UNLCK)`` on Windows, else None.

    Looked up dynamically: these attributes do not exist in the POSIX stubs, so
    a static reference fails type-checking on Linux (and a ``type: ignore``
    would read as unused on Windows).
    """
    try:
        import msvcrt
    except ImportError:
        return None
    locking = getattr(msvcrt, "locking", None)
    nblck = getattr(msvcrt, "LK_NBLCK", None)
    unlck = getattr(msvcrt, "LK_UNLCK", None)
    if locking is None or nblck is None or unlck is None:
        return None
    return locking, nblck, unlck


def _acquire_lock_windows(handle: Any, timeout: float) -> None:
    import time as _time

    api = _msvcrt_locking()
    if api is None:
        return
    locking, nblck, _ = api
    deadline = _time.monotonic() + timeout
    while True:
        try:
            locking(handle.fileno(), nblck, 1)
            return
        except OSError:
            if _time.monotonic() >= deadline:
                return
            _time.sleep(0.01)


def _release_lock(handle: Any) -> None:
    try:
        import fcntl
    except ImportError:
        api = _msvcrt_locking()
        if api is not None:
            locking, _, unlck = api
            with suppress(OSError, ValueError):
                locking(handle.fileno(), unlck, 1)
        return
    with suppress(OSError, ValueError):
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def update_state(
    path: Path | str, mutate: Callable[[dict[str, Any]], None]
) -> dict[str, Any]:
    """Read-modify-write the envelope under one lock, returning the new state.

    This is the safe entry point for every writer: it re-reads inside the lock,
    so two concurrent runs touching *different* job keys merge instead of
    clobbering each other (Part F: last-writer-wins per key, not per file).
    """
    target = Path(path)
    with state_lock(target):
        state = load_state(target)
        mutate(state)
        save_state(target, state)
        return state
