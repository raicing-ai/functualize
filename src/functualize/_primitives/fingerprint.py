"""Up-to-date checking: fingerprint keys, source maps, and verdicts (§D.3).

Two correctness fixes from the proposal are baked into this module's shape:

**Fix 1 — the key includes the resolved config/args hash.** Keying on source
files alone means ``func build --env prod`` right after a successful
``func build --env dev`` is skipped as "up to date" — the wrong answer,
silently. The key is ``<job_name>::<args_hash>::<method>`` where ``args_hash``
covers the *typed, resolved* config (post-precedence, post-env, post-prompt)
plus call args, so any input that could change behavior changes the key. Matrix
instances get independent staleness for free.

**Fix 2 — fingerprints do NOT live in the discovery cache.** They live in the
runtime state store (Part F), because the discovery cache is rebuilt whenever
any source file or version changes, which would drop every job's fingerprint
because one file moved — the exact spurious-rebuild failure up-to-date checking
exists to prevent.

**Companion R4 (normative) — stat short-circuit.** Source entries record
``(mtime, size, sha256)``; a file whose mtime and size both match the previous
entry is not re-hashed. Hashing every source on every run is the dominant cost
of checksum mode on a large tree.

Pure and stdlib-only (``_primitives``): no I/O beyond reading the files it is
asked to hash, no state-store coupling — callers persist the records.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

# Supported up-to-date methods (§D.3). "none" disables file checking entirely;
# guards still apply.
FINGERPRINT_METHODS: tuple[str, ...] = ("checksum", "timestamp", "none")

_CHUNK = 65536


@dataclass(frozen=True)
class FingerprintVerdict:
    """Why a job is (or is not) up to date — the data behind `func why` (§D.6).

    Attributes:
        up_to_date: True when the job may be skipped as fresh.
        reason: Human-readable explanation, shown by `func why`/`--explain`.
        changed: Project-relative source paths that differ from the record.
    """

    up_to_date: bool
    reason: str
    changed: tuple[str, ...] = field(default=())


def canonical_json(payload: Any) -> str:
    """Serialize ``payload`` deterministically for hashing.

    Sorted keys and tight separators so equal inputs always produce an equal
    string. Values that are not JSON-serializable fall back to ``repr`` rather
    than raising — an un-serializable config field must not break a build; the
    worst case is a hash that changes more often than strictly necessary.
    """
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=repr, ensure_ascii=True
    )


def compute_args_hash(resolved_config: Any = None, call_args: Any = None) -> str:
    """Hash the resolved config + call args (§D.3 Fix 1).

    Pass the *resolved* config (post-precedence, post-env, post-prompt) as a
    plain mapping — pydantic models should be dumped by the caller, which owns
    the model's serialization rules.
    """
    payload = {"config": resolved_config, "args": call_args}
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def compute_declaration_hash(declaration: Any) -> str:
    """Hash a ``@job`` declaration so a changed declaration invalidates records.

    Stored as ``job_version``: changing ``sources``, ``method``, or guards must
    not silently reuse a fingerprint recorded under the old declaration.
    """
    return hashlib.sha256(canonical_json(declaration).encode()).hexdigest()


def fingerprint_key(job_name: str, args_hash: str, method: str) -> str:
    """Build the state-store key ``<job_name>::<args_hash>::<method>``.

    Contains no absolute paths, keeping the store content-addressable-friendly
    (Part G).
    """
    return f"{job_name}::{args_hash}::{method}"


def hash_file(path: Path) -> str:
    """SHA-256 of a file's contents, streamed."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def expand_sources(root: Path | str, patterns: Iterable[str]) -> list[str]:
    """Expand source globs to sorted, project-relative POSIX paths.

    Only files are returned (a directory match is not a source). Paths that
    escape ``root`` are skipped — records must stay project-relative.
    """
    base = Path(root).resolve()
    found: set[str] = set()
    for pattern in patterns:
        for match in base.glob(pattern):
            if not match.is_file():
                continue
            try:
                relative = match.resolve().relative_to(base)
            except ValueError:
                continue  # outside the project root
            found.add(relative.as_posix())
    return sorted(found)


def build_source_map(
    root: Path | str,
    relpaths: Sequence[str],
    previous: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build ``{relpath: {mtime, size, sha256}}`` for the given sources.

    Applies the R4 stat short-circuit: when a file's ``mtime`` and ``size`` both
    match the previous entry, its recorded ``sha256`` is reused instead of
    re-reading the file.
    """
    base = Path(root).resolve()
    prior = previous or {}
    result: dict[str, dict[str, Any]] = {}
    for relpath in relpaths:
        target = base / relpath
        try:
            stat = target.stat()
        except OSError:
            continue  # vanished between expansion and stat — treat as absent
        entry_prev = prior.get(relpath)
        digest: str | None = None
        if isinstance(entry_prev, dict) and (
            entry_prev.get("mtime") == stat.st_mtime
            and entry_prev.get("size") == stat.st_size
        ):
            recorded = entry_prev.get("sha256")
            if isinstance(recorded, str):
                digest = recorded  # R4: unchanged stat → skip the re-hash
        if digest is None:
            try:
                digest = hash_file(target)
            except OSError:
                continue
        result[relpath] = {
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "sha256": digest,
        }
    return result


def make_record(
    source_map: Mapping[str, Any],
    generates: Sequence[str] = (),
    job_version: str = "",
    recorded_at: str = "",
    return_value: Any = None,
) -> dict[str, Any]:
    """Build a fingerprint record in the schema.md §1 shape.

    ``return_value`` is stored only when it round-trips through JSON; see
    :func:`classify_return_value` for what happens otherwise and why the record
    is still written.
    """
    reusable, kind, type_name, stored = classify_return_value(return_value)
    return {
        "sources": dict(source_map),
        "generates": list(generates),
        "return_value": stored if reusable else None,
        "return_value_reusable": reusable,
        "return_value_kind": kind,
        "return_value_type": type_name,
        "recorded_at": recorded_at,
        "job_version": job_version,
    }


def classify_return_value(value: Any) -> tuple[bool, str, str, Any]:
    """Decide whether ``value`` can be reused, and render it (resolved Q19).

    Returns ``(reusable, kind, type_name, stored)``.

    **Serialization is pydantic's, not `json`'s.** `json.dumps` fails on a
    `@dataclass` — the most idiomatic way to return structured data in modern
    Python — not because the data is hard but because stdlib json has no
    encoder for the *type*; `dataclasses.asdict` renders it in one call.
    Classifying with `json.dumps` therefore condemned ordinary code, and made
    `Path` look like a special case rather than one instance of a general one.

    pydantic is already a hard dependency, already imported at boot, and
    already used in this module, so this costs nothing and covers dataclasses,
    `BaseModel`, `Path`, `datetime`, `set`, `tuple`, and nested generics.
    Only values with no derivable schema — a live connection, a socket, an
    open file — remain unreusable, which is the rare tail this was meant to
    describe all along.

    ``stored`` is JSON-compatible Python, so the state file stays a plain
    readable document. Rebuilding the original *type* needs a type, which the
    writer does not reliably have; the consumer supplies it on read (see
    :func:`reusable_return_value`).
    """
    if value is None:
        return True, "none", "", None

    type_name = type(value).__name__

    try:
        from pydantic import TypeAdapter

        stored = TypeAdapter(type(value)).dump_python(value, mode="json")
    except Exception:
        return False, "unserializable", type_name, None

    kind = "path" if isinstance(value, Path) else "json"
    return True, kind, type_name, stored


def evaluate(
    record: Mapping[str, Any] | None,
    *,
    root: Path | str,
    source_map: Mapping[str, Any],
    generates: Sequence[str] = (),
    method: str = "checksum",
    job_version: str = "",
) -> FingerprintVerdict:
    """Decide whether a job is up to date against its stored ``record``.

    - ``none``: file checking disabled — never fresh on this axis (guards still
      decide; §D.3).
    - ``checksum``: every source's SHA-256 must match the record.
    - ``timestamp``: every declared output must exist and be no older than the
      newest source (a missing output always forces a run).

    A record written under a different ``job_version`` is stale regardless of
    files: the declaration itself changed.
    """
    if method == "none":
        return FingerprintVerdict(False, "method=none — file checking disabled")
    if record is None:
        return FingerprintVerdict(False, "no previous run recorded")
    if job_version and record.get("job_version") not in ("", job_version):
        return FingerprintVerdict(False, "@job declaration changed since last run")

    if method == "timestamp":
        return _evaluate_timestamp(root, source_map, generates)
    return _evaluate_checksum(record, source_map)


def _evaluate_checksum(
    record: Mapping[str, Any], source_map: Mapping[str, Any]
) -> FingerprintVerdict:
    recorded = record.get("sources")
    if not isinstance(recorded, dict):
        return FingerprintVerdict(False, "no previous run recorded")

    changed = [
        path
        for path, entry in source_map.items()
        if not isinstance(recorded.get(path), dict)
        or recorded[path].get("sha256") != entry.get("sha256")
    ]
    removed = [path for path in recorded if path not in source_map]
    if changed or removed:
        detail = _describe_changes(changed, removed)
        return FingerprintVerdict(False, detail, tuple(sorted(changed + removed)))
    return FingerprintVerdict(True, f"{len(source_map)} sources unchanged")


def _evaluate_timestamp(
    root: Path | str, source_map: Mapping[str, Any], generates: Sequence[str]
) -> FingerprintVerdict:
    if not generates:
        return FingerprintVerdict(
            False, "method=timestamp requires generates to compare against"
        )
    base = Path(root).resolve()
    missing = [out for out in generates if not (base / out).exists()]
    if missing:
        return FingerprintVerdict(
            False,
            f"output missing: {', '.join(sorted(missing))}",
            tuple(sorted(missing)),
        )
    newest_source = max(
        (entry.get("mtime", 0.0) for entry in source_map.values()), default=0.0
    )
    oldest_output = min((base / out).stat().st_mtime for out in generates)
    if newest_source > oldest_output:
        return FingerprintVerdict(False, "sources newer than outputs")
    return FingerprintVerdict(True, "outputs newer than all sources")


def _describe_changes(changed: Sequence[str], removed: Sequence[str]) -> str:
    """Render a `func why`-style change summary (§D.6)."""
    parts: list[str] = []
    if changed:
        shown = ", ".join(sorted(changed)[:3])
        suffix = ", …" if len(changed) > 3 else ""
        parts.append(f"{len(changed)} changed ({shown}{suffix})")
    if removed:
        parts.append(f"{len(removed)} removed")
    return " · ".join(parts) + " since last run"


# Jobs already warned about in this process, so the notice is once per job
# rather than once per dependent that missed the value.
_WARNED_UNREUSABLE: set[str] = set()


def reusable_return_value(
    record: Mapping[str, Any] | None,
    *,
    job_name: str,
    expected_type: Any = None,
) -> Any:
    """The recorded value a dependent may be handed, or None (resolved Q19).

    ``expected_type`` is the *consumer's* declared type — the ``T`` in
    ``Annotated[T, FromJob(...)]``. The writer stored JSON-compatible data and
    could not reliably know the full type (``type([Report(1)])`` is ``list``,
    losing the item schema), but the reader's annotation says exactly what is
    wanted, so reconstruction belongs here. This is the same direction config
    injection already resolves in: the consumer declares, the framework
    supplies.

    Refusals, each for a different reason:

    - **Nothing recorded** -> None. Ordinary cache miss.
    - **Recorded but not reusable** -> None, *warned once per job per
      process*. The warning fires here because here is where the cost is paid:
      a dependent asked, could not be served, and the upstream must re-run.
      Warning at record time would fire for jobs nobody reads from.
    - **A path that no longer exists** -> None. A cached path to a deleted
      file is a wrong answer the system can catch, so it declines to hand back
      a lie. pydantic cannot see this; existence is a freshness question, not
      a serialization one.
    - **Stored shape no longer matches the annotation** -> None. The
      declaration drifted since the value was written; re-running is correct
      and silently coercing would not be.
    """
    if not record:
        return None

    if record.get("return_value_reusable") is False:
        if job_name and job_name not in _WARNED_UNREUSABLE:
            _WARNED_UNREUSABLE.add(job_name)
            logger.warning(
                "Job %r returned %s, which has no serializable form, so its "
                "value cannot be reused: dependents reading it with FromJob "
                "will re-run it. Caching is unaffected — the job still "
                "fingerprints and still skips when fresh.",
                job_name,
                record.get("return_value_type") or "a value",
            )
        return None

    stored = record.get("return_value")
    if stored is None:
        return None

    if record.get("return_value_kind") == "path" and not Path(str(stored)).exists():
        return None

    if expected_type is None:
        return stored

    try:
        from pydantic import TypeAdapter

        return TypeAdapter(expected_type).validate_python(stored)
    except Exception:
        logger.debug(
            "Recorded value for %r no longer matches the declared type %r; "
            "treating it as absent so the upstream re-runs.",
            job_name,
            expected_type,
        )
        return None


def why_return_value_unreusable(record: Mapping[str, Any] | None) -> str:
    """One line for `func why` / `--explain`, or "" when nothing is wrong."""
    if not record:
        return ""
    if record.get("return_value_reusable") is False:
        return (
            f"return value not reusable: "
            f"{record.get('return_value_type') or 'non-serializable'} "
            f"cannot be stored in the state file"
        )
    if record.get("return_value_kind") == "path":
        value = record.get("return_value")
        if value is not None and not Path(value).exists():
            return f"recorded path no longer exists: {value}"
    return ""
