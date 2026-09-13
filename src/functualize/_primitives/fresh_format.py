"""Shared runtime-state format: single source of truth for the state file.

The runtime state store answers "what ran last, against which inputs" —
fingerprints, run history, and session-scoped precondition results. All three
are **derived**: recomputable from the source tree, and safe to throw away.
Workflow scopes are not, and live in `scope_format.py` next door.

It is deliberately **separate from the discovery cache**
(proposal §D.3 Fix 2): the discovery cache answers "what jobs exist" and is
rebuilt whenever a source file or version changes, which would drop every
fingerprint because one file moved. Different lifecycle, different invalidation
rules, different file. `func cache clear` and `func state clear` never
invalidate each other.

Location mirrors the discovery cache (proposal Part F):
- Declared-project mode: `.functualize/fresh.json`
- Standalone mode: `$XDG_CACHE_HOME/functualize/<project_id>/fresh.json`

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
import logging
import os
import tempfile
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize._primitives.locator import _xdg_cache_dir, compute_project_id

if TYPE_CHECKING:
    from collections.abc import Iterator

# Current state file format version. Bump on any incompatible format change.
# A version mismatch discards the file, and that is safe **because every section
# here is derived** — recomputable from the source tree, at worst costing one
# extra run.
#
# That rule was once false. Workflow scopes lived in this envelope until
# 2026-09-09, and a version bump — an ordinary release action — silently erased
# every in-flight run, recorded gate payloads and all. They now live in
# `scope_format.py`, whose read refuses rather than discards.
#
# So: when adding a section, decide which of the two files it belongs in
# *first*. A record someone would be upset to lose is not derived, and the rule
# above is a promise this file cannot keep for it.
# v1 (2026-07-20): initial envelope — fingerprints (with the R4
# (mtime, size, sha256) stat short-circuit), scopes, history ring buffer,
# session precondition cache.
# v1 (2026-09-09): scopes moved to scopes.json. Version deliberately NOT bumped
# — nothing about the remaining sections changed, and bumping would discard
# every fingerprint to no purpose.
FRESH_VERSION = 1

#: The freshness ledger's file name, beside `cache.json`.
#:
#: **Renamed from `fresh.json` in `durable-run-layer`/T3b**, once the file held
#: only freshness verdicts. The old name was the vaguest word available and it
#: collided three ways: `rc.state.set(...)` wrote to a scope's state file,
#: `fresh.json` held fingerprints, and `func builtin state` cleared both. A user
#: who stored a value and then ran `state clear` wiped the wrong thing.
#:
#: No read-both migration. The Pre-Release Stance permits deleting rather than
#: shimming, and the cost is bounded: an old `fresh.json` is simply not found,
#: so the next run recomputes its freshness verdicts and writes `fresh.json`.
#: The worst case is one extra run of each job — which is exactly the worst case
#: this file's discard rule already accepts.
FRESH_FILENAME = "fresh.json"

#: The document name this envelope is stored under.
#:
#: A key, not a path. `JsonFileSubstrate.for_project` turns it back into
#: `fresh.json` under the directory the upward walk found.
FRESH_KEY = "fresh"

#: The sections this file holds. **Freshness verdicts, and nothing else** —
#: `history` left in `durable-run-layer`/T3b. Job history is now derived from
#: the run log (`app/_run_view.job_history`), which recorded the same runs plus
#: the nested ones plus who invoked them; shell history moved to its own file,
#: because a typed command was never a run and the run log has nowhere to put
#: it. What remains is what the file is actually for.
_SECTIONS: tuple[str, ...] = ("fingerprints", "session")


logger = logging.getLogger(__name__)


def empty_fresh() -> dict[str, Any]:
    """Return a fresh, fully-populated envelope (schema.md §1)."""
    return {
        "format_version": FRESH_VERSION,
        "fingerprints": {},
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
FRESH_MODES = ("project", "standalone")


def resolve_fresh_location(start: Path) -> tuple[Path, str, Path | None]:
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
    standalone without noticing and then go looking for a ``fresh.json`` that
    was under a hashed directory in the home cache.

    Args:
        start: Project root (or cwd) to resolve from.

    Returns:
        ``(state_path, mode, functualize_dir)`` — the path (which may not exist
        yet), one of :data:`FRESH_MODES`, and the directory that decided it, or
        None in standalone mode.
    """
    start = Path(start).resolve()
    functualize_dir = find_functualize_dir(start)
    if functualize_dir is not None:
        return functualize_dir / FRESH_FILENAME, "project", functualize_dir
    project_id = compute_project_id(str(start))
    path = _xdg_cache_dir() / "functualize" / project_id / FRESH_FILENAME
    return path, "standalone", None


def resolve_fresh_path(start: Path) -> Path:
    """Resolve the runtime state file path for a project.

    The path half of :func:`resolve_fresh_location`, which is where the rule
    lives — one upward walk, one answer.

    Args:
        start: Project root (or cwd) to resolve from.

    Returns:
        Absolute path where the state file lives (may not exist yet).
    """
    return resolve_fresh_location(start)[0]


def normalize_fresh(data: Any) -> dict[str, Any]:
    """Coerce loaded data into a valid envelope, filling missing sections.

    Anything unrecognizable (not a dict, wrong version) yields a fresh envelope
    rather than raising — every section here is derived and always safe to
    discard. `scope_format.load_scopes` deliberately does the opposite.
    """
    if not isinstance(data, dict):
        return empty_fresh()
    if data.get("format_version") != FRESH_VERSION:
        return empty_fresh()
    state = empty_fresh()
    for section in _SECTIONS:
        value = data.get(section)
        if isinstance(value, type(state[section])):
            state[section] = value
    if not isinstance(state["session"].get("preconditions"), dict):
        state["session"]["preconditions"] = {}
    return state


def atomic_write_json(path: Path | str, payload: dict[str, Any]) -> None:
    """Write ``payload`` as JSON atomically (tmp file + ``os.replace``).

    Atomic so a crash mid-write cannot leave a half-written file that the next
    run would discard.

    **The only one in ``_primitives/``**, shared by this module and
    :mod:`functualize._primitives.scope_format` — the two runtime-state formats
    write through one implementation so neither can silently lose its ``fsync``.
    The caller supplies the payload including its own ``format_version``; only
    the discipline lives here.

    ``_cli/`` has five other ``mkstemp`` writers (``self_update``, ``manifest``,
    ``package_ops``, ``config_snapshot_store``, ``toml_writer``). They stage a
    binary, a registry, and a TOML file — different payloads, different layer,
    and ``_primitives`` could not import them anyway. This is not the repo's one
    atomic write; it is the runtime state store's one atomic write.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
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


def stamp_fresh(state: dict[str, Any]) -> dict[str, Any]:
    """The payload to store: the envelope with the current version stamped on.

    A copy rather than a mutation, so a caller holding an open batch does not
    find its own envelope rewritten underneath it.
    """
    payload = dict(state)
    payload["format_version"] = FRESH_VERSION
    return payload


@contextmanager
def file_lock(path: Path | str, timeout: float = 10.0) -> Iterator[None]:
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
        _acquire_lock(handle, timeout, lock_path)
        yield
    finally:
        if handle is not None:
            _release_lock(handle)
            handle.close()


def _lock_timeout(path: Any, timeout: float) -> None:
    """Say that the lock was given up on, then let the caller proceed.

    Proceeding is the right default — a stuck lock must not wedge a build — but
    it is also the **one path where a write can be lost**, because two
    processes then read-modify-write the same file with nothing between them.
    It used to happen in complete silence, so the only evidence was the missing
    data.

    A warning rather than an exception: raising here would turn a slow
    neighbour into a failed run, which is the deadlock this branch exists to
    avoid. The caller is told, and decides.
    """
    logger.warning(
        "Gave up waiting %.0fs for the lock on %s and is proceeding without "
        "it. Concurrent writers can now lose each other's updates. This means "
        "something else held the lock for longer than that — a stuck process, "
        "or a filesystem where locking does not work.",
        timeout,
        path,
    )


def _acquire_lock(handle: Any, timeout: float, path: Any = None) -> None:
    """Best-effort exclusive lock; returns (unlocked) if unsupported."""
    try:
        import fcntl
    except ImportError:
        _acquire_lock_windows(handle, timeout, path)
        return
    import time as _time

    deadline = _time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError:
            if _time.monotonic() >= deadline:
                # Advisory: proceed rather than deadlock a build — but say so.
                _lock_timeout(path, timeout)
                return
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


def _acquire_lock_windows(handle: Any, timeout: float, path: Any = None) -> None:
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
                # Same give-up as the POSIX branch, and just as audible.
                _lock_timeout(path, timeout)
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
