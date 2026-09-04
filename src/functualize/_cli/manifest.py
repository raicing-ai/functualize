"""The registry of every ``func`` that has run on this machine.

One user-global file, voluntarily updated by any installation that runs. That
is the entire protocol — **nothing here discovers anything.** No ``PATH`` scan,
no directory walk, no subprocess, no interrogating another binary. An
installation appears once it has run, and an installation that has never run is
genuinely unknown, which is the right answer rather than a gap: it has produced
no state, no config and no jobs, so it is not yet a fact about the system.

Discovery was measured and rejected. Executing five installations to read their
versions costs ~2.1s serial, and a filesystem walk looking for repos has no
honest root. Reading this file costs ~39us.

**Registration is voluntary, and failing at it is never an error.** A read-only
config directory, a container without a writable ``XDG_CONFIG_HOME``, a sandbox
— each makes it impossible, and each must degrade silently. A registry that
interferes with the command the user typed is worse than no registry.

This module is in the ``_cli/`` layer — public API only.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = [
    "SCHEMA_VERSION",
    "InstallRecord",
    "Manifest",
    "manifest_path",
    "marker_path",
    "forget_addition",
    "record_addition",
    "recorded_additions",
    "register",
]

#: Bumped when the on-disk shape changes incompatibly. A reader seeing a
#: *higher* number treats the file as unreadable rather than guessing.
SCHEMA_VERSION = 1

_MANIFEST_NAME = "install.json"
_MARKER_DIR = "installs"

#: How long a writer waits for the lock before giving up. Registration is
#: best-effort, so timing out is a silent no-op rather than an error.
_LOCK_TIMEOUT_S = 2.0
#: A lock older than this is assumed to belong to a process that died holding
#: it. Short, because the critical section is one small read and one rename.
_STALE_LOCK_S = 30.0


@dataclass(frozen=True)
class InstallRecord:
    """One installation that has run at least once."""

    binary_path: str
    runtime_mode: str
    owning_distribution: str | None
    python_version: str
    functualize_version: str
    #: Added by ``plugin install`` — not an inventory of what is installed.
    plugins: tuple[str, ...] = ()
    #: Added by ``self install``. Disjoint from ``plugins`` by construction:
    #: ``plugin list`` must never show a plain dependency, and ``self update``
    #: restores both in one pass, so the distinction has to survive the file.
    packages: tuple[str, ...] = ()
    first_run_at: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "binary_path": self.binary_path,
            "runtime_mode": self.runtime_mode,
            "owning_distribution": self.owning_distribution,
            "python_version": self.python_version,
            "functualize_version": self.functualize_version,
            "plugins": list(self.plugins),
            "packages": list(self.packages),
            "first_run_at": self.first_run_at,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> InstallRecord | None:
        """Build a record, or ``None`` if the entry is not one.

        Tolerant on purpose: one malformed entry written by a future version
        must not make the whole registry unreadable.
        """
        path = raw.get("binary_path")
        if not isinstance(path, str) or not path:
            return None

        def _strs(key: str) -> tuple[str, ...]:
            value = raw.get(key)
            if not isinstance(value, list):
                return ()
            return tuple(v for v in value if isinstance(v, str))

        owner = raw.get("owning_distribution")
        return cls(
            binary_path=path,
            runtime_mode=str(raw.get("runtime_mode") or "unknown"),
            owning_distribution=owner if isinstance(owner, str) else None,
            python_version=str(raw.get("python_version") or ""),
            functualize_version=str(raw.get("functualize_version") or ""),
            plugins=_strs("plugins"),
            packages=_strs("packages"),
            first_run_at=str(raw.get("first_run_at") or ""),
        )


@dataclass(frozen=True)
class Manifest:
    """Every installation, in the order they first registered.

    **Append-only is a property of this API, not of the type.** There is
    ``add`` and ``replace``, and deliberately no ``remove``: two installations
    coexisting is a real state and ``PATH`` decides which one runs, so a record
    whose binary has gone is *reported* as stale rather than deleted.
    """

    schema_version: int = SCHEMA_VERSION
    installations: tuple[InstallRecord, ...] = ()

    def find(self, binary_path: str) -> InstallRecord | None:
        for record in self.installations:
            if record.binary_path == binary_path:
                return record
        return None

    def add(self, record: InstallRecord) -> Manifest:
        return replace(self, installations=(*self.installations, record))

    def replace(self, record: InstallRecord) -> Manifest:
        """Swap the record for this ``binary_path``, keeping its position.

        What an in-place upgrade takes. Appending instead would accumulate one
        record per version a single binary has ever been, which reads as
        several installations that do not exist.
        """
        updated = tuple(
            record if existing.binary_path == record.binary_path else existing
            for existing in self.installations
        )
        return replace(self, installations=updated)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "installations": [r.to_json() for r in self.installations],
        }


def resolve_binary_path(
    argv0: str, executable: str, standalone_binary: str | None = None
) -> str:
    """A stable identity for "this installation", whatever `argv[0]` looks like.

    `standalone_binary` wins outright when supplied. PyApp launches a standalone
    binary as `python -c "..."`, so `argv[0]` is the literal string `-c` and
    every derivation below produces `<prefix>/bin/-c` -- a path that has never
    existed, which the registry then correctly reports as stale on the very run
    that recorded it. PyApp hands over the real executable path in `PYAPP`
    (built with `PYAPP_PASS_LOCATION=1`), and that is the only honest answer.

    `sys.argv[0]` is not stable across invocation styles: a direct call gives an
    absolute path, while `uv run func` gives the bare name `func`. Recording it
    raw registers one installation twice, and then reports the bare-name copy as
    stale because no such file exists relative to the cwd.

    A bare name is therefore resolved against the running interpreter's own
    directory, which is where a console script for this environment lives. That
    is derived from `sys.executable` — **not discovered**: nothing searches
    `PATH` or the filesystem for candidates.

    Kept in one place because `_cli/main.py`'s warm path recomputes it inline to
    avoid importing this module; `tests/_cli/test_manifest.py` asserts the two
    agree.
    """
    if standalone_binary:
        # Substituted for `argv0` rather than returned directly, so it goes
        # through the same normalization. PyApp's `PYAPP` is always absolute and
        # falls out of the separator branch unchanged; a bare name -- which is
        # what the `FUNCTUALIZE_RUNTIME=standalone` override sees -- must still
        # resolve against the interpreter's directory and not the working one,
        # or this disagrees with `main.py`'s warm path and the registry records
        # the same installation twice.
        argv0 = standalone_binary
    if not argv0:
        return ""
    if "/" in argv0 or "\\" in argv0:
        try:
            return str(Path(argv0).resolve())
        except OSError:  # pragma: no cover - unresolvable path
            return argv0
    return str(Path(executable).parent / argv0)


def manifest_path(config_dir: Path) -> Path:
    return config_dir / _MANIFEST_NAME


def marker_path(config_dir: Path, binary_path: str, version: str) -> Path:
    """Where the "this identity is already recorded" marker lives.

    **The key covers the version, not only the path.** Keyed on
    ``binary_path`` alone, an in-place upgrade is masked forever:
    ``/usr/local/bin/func`` registers at 0.1.2, is upgraded to 0.2.0, the
    marker still exists, the fast path short-circuits, and the registry reports
    0.1.2 for the rest of time. Including the version means an upgrade misses
    the marker, pays one cold registration, and refreshes its record.

    The marker is a negative cache, never the record. Losing it costs one
    redundant re-check; it can be deleted safely.
    """
    digest = hashlib.sha256(f"{binary_path}\0{version}".encode()).hexdigest()[:16]
    return config_dir / _MARKER_DIR / digest


@contextlib.contextmanager
def _locked(path: Path) -> Iterator[bool]:
    """Serialise writers around the registry. Yields whether it was acquired.

    A lock *directory*, because `os.mkdir` is atomic on every platform this
    ships to. `fcntl.flock` would be tidier but is POSIX-only, and the binary
    targets Windows.

    Atomic writes alone are not enough here. `os.replace` prevents a torn file,
    not a lost update: without this, twelve concurrent registrations produced a
    file containing three of them, because each writer loaded before the others
    had written. Verify-and-retry does not close it either — the verification
    is itself racy, so a later writer still clobbers a record that had just
    been confirmed.

    A lock left behind by a process that died is broken after `_STALE_LOCK_S`,
    so a crash cannot wedge registration permanently.
    """
    lock = path.parent / ".install.lock"
    deadline = time.monotonic() + _LOCK_TIMEOUT_S
    acquired = False
    while True:
        try:
            lock.parent.mkdir(parents=True, exist_ok=True)
            os.mkdir(lock)
            acquired = True
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > _STALE_LOCK_S:
                    with contextlib.suppress(OSError):
                        os.rmdir(lock)
                    continue
            except OSError:
                pass
            if time.monotonic() > deadline:
                break
            time.sleep(0.005)
        except OSError:
            break
    try:
        yield acquired
    finally:
        if acquired:
            with contextlib.suppress(OSError):
                os.rmdir(lock)


def load(path: Path) -> Manifest:
    """Read the registry, degrading to empty rather than raising.

    A corrupt or future-versioned file is treated as unreadable. This is a
    convenience record; a damaged one must not make ``func`` unusable.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return Manifest()
    if not isinstance(raw, dict):
        return Manifest()

    version = raw.get("schema_version")
    if not isinstance(version, int) or version > SCHEMA_VERSION:
        # A higher version may mean anything. Refusing to parse is the only
        # honest answer; optimistic parsing would silently drop fields.
        return Manifest()

    entries = raw.get("installations")
    if not isinstance(entries, list):
        return Manifest()
    records = [
        record
        for entry in entries
        if isinstance(entry, dict) and (record := InstallRecord.from_json(entry))
    ]
    return Manifest(schema_version=version, installations=tuple(records))


def save(manifest: Manifest, path: Path) -> bool:
    """Write the registry atomically. ``False`` when it could not be written.

    Serialize to a temporary file in the same directory and ``os.replace`` over
    the target, so a reader never sees a half-written file.

    **Atomicity alone does not make concurrent registration safe.** It prevents
    a *torn* file, not a *lost update*: two writers that each load, modify and
    save will produce one file containing one of the two changes. Losing a
    record is exactly what append-only exists to prevent, so :func:`register`
    wraps this in a verify-and-retry loop rather than relying on the rename.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=".install-", suffix=".json"
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(manifest.to_json(), stream, indent=2)
                stream.write("\n")
            os.replace(tmp_name, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise
    except OSError:
        return False
    return True


def register(
    config_dir: Path,
    *,
    binary_path: str,
    runtime_mode: str,
    owning_distribution: str | None,
    python_version: str,
    functualize_version: str,
) -> bool:
    """Ensure this installation's current identity is recorded.

    Appends a new installation, or **replaces** the record for a
    ``binary_path`` already present whose version has moved. Writes the marker
    only once the registry write succeeded, so a failed write is retried on the
    next run rather than being masked by a marker for a record that was never
    stored.

    Returns whether anything was written. Callers ignore it: registration is
    voluntary and its failure is silent by design.
    """
    path = manifest_path(config_dir)

    with _locked(path) as acquired:
        if not acquired:
            return False

        manifest = load(path)
        existing = manifest.find(binary_path)
        current = (
            existing is not None and existing.functualize_version == functualize_version
        )

        if not current:
            record = InstallRecord(
                binary_path=binary_path,
                runtime_mode=runtime_mode,
                owning_distribution=owning_distribution,
                python_version=python_version,
                functualize_version=functualize_version,
                # An upgrade keeps what the previous version had added, because
                # those are still installed — the binary changed, not its env.
                plugins=existing.plugins if existing else (),
                packages=existing.packages if existing else (),
                first_run_at=(
                    existing.first_run_at
                    if existing and existing.first_run_at
                    else datetime.now(UTC).isoformat(timespec="seconds")
                ),
            )
            updated = (
                manifest.replace(record)
                if existing is not None
                else manifest.add(record)
            )
            if not save(updated, path):
                return False

    marker = marker_path(config_dir, binary_path, functualize_version)
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
    except OSError:
        return False
    return True


def record_addition(
    config_dir: Path,
    *,
    binary_path: str,
    key: Literal["plugins", "packages"],
    name: str,
) -> bool:
    """Note that this installation added ``name``, under ``plugins`` or ``packages``.

    The two lists stay **disjoint**: a name recorded under one is moved rather
    than duplicated if it later arrives through the other command. ``plugin
    list`` must never show a plain dependency, and ``self update`` restores both
    in one pass, so the distinction has to survive the file
    (`contracts.md` §6).

    Called only after the install command has actually succeeded — a record of
    a package that is not installed is worse than no record, because the next
    update reinstalls it.

    Returns whether anything was written; a failure is silent by design, exactly
    as :func:`register`'s is.
    """
    path = manifest_path(config_dir)
    other: Literal["plugins", "packages"] = (
        "packages" if key == "plugins" else "plugins"
    )

    with _locked(path) as acquired:
        if not acquired:
            return False

        manifest = load(path)
        existing = manifest.find(binary_path)
        if existing is None:
            return False

        current: tuple[str, ...] = getattr(existing, key)
        if any(_same(name, held) for held in current):
            return True

        added = (*current, name)
        # Spelled out rather than built with `**{key: ...}`: a dict keyed by a
        # `Literal` widens to `str` at the `replace` boundary, so the checker
        # cannot tell which field is being set and reads every keyword as a
        # possible mistake.
        pruned = tuple(
            held for held in getattr(existing, other) if not _same(name, held)
        )
        updated_record = (
            replace(existing, plugins=added, packages=pruned)
            if key == "plugins"
            else replace(existing, packages=added, plugins=pruned)
        )
        return save(manifest.replace(updated_record), path)


def forget_addition(config_dir: Path, *, binary_path: str, name: str) -> bool:
    """Drop ``name`` from both lists after it has actually been uninstalled.

    **This is not a hole in append-only.** What is append-only is the list of
    *installations*: a record whose binary has gone is reported as stale rather
    than deleted, because two installations coexisting is a real state. The
    ``plugins`` and ``packages`` lists are a different thing — a note of what
    this installation should put back after an upgrade — and a name left there
    after an uninstall is reinstalled by the next ``self update``, undoing the
    uninstall silently and at a distance.

    Returns whether anything changed.
    """
    path = manifest_path(config_dir)

    with _locked(path) as acquired:
        if not acquired:
            return False

        manifest = load(path)
        existing = manifest.find(binary_path)
        if existing is None:
            return False

        plugins = tuple(p for p in existing.plugins if not _same(name, p))
        packages = tuple(p for p in existing.packages if not _same(name, p))
        if plugins == existing.plugins and packages == existing.packages:
            return False
        updated = replace(existing, plugins=plugins, packages=packages)
        return save(manifest.replace(updated), path)


def recorded_additions(config_dir: Path, binary_path: str) -> tuple[str, ...]:
    """Everything this installation added, plugins and packages together.

    One list because reconciliation restores them in one pass and does not care
    which is which — the distinction matters to ``plugin list``, not here.
    """
    record = load(manifest_path(config_dir)).find(binary_path)
    if record is None:
        return ()
    return (*record.plugins, *record.packages)


def _same(left: str, right: str) -> bool:
    """PEP 503 name equality, so ``functualize-http`` and ``functualize_http``
    are not recorded twice."""
    return _canonical(left) == _canonical(right)


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).strip().lower()
