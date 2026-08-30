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

import glob as _glob
import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping, Sequence

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

    #: The job declared sources and **none of them resolved to a file**.
    #:
    #: Distinct from "not up to date" and from "up to date". A checksum run
    #: over an empty source map compares nothing and finds nothing changed, so
    #: it used to answer ``up_to_date=True, "0 sources unchanged"`` — a stage
    #: certifying success having verified nothing at all. The distinction
    #: cannot be recovered downstream, because an empty ``source_map`` looks
    #: identical whether the job declared no sources or declared sources that
    #: matched nothing. So it is carried here, from the one place that can
    #: still tell them apart.
    #:
    #: Defaulting to False keeps every existing construction valid.
    refused: bool = field(default=False)


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


def config_payload(config: Any) -> Any:
    """A resolved config as plain data, ready for :func:`compute_args_hash`.

    That function's contract is "pass a plain mapping — pydantic models should
    be dumped by the caller, which owns the model's serialization rules", and
    every caller passed the live model instead, relying on pydantic's ``repr``
    being stable. It was, undocumented, and one non-``repr``-stable nested
    field away from the same defect that made a job with a capability
    parameter hash a new key every run.

    Honouring the contract at each call site would re-create that drift at
    each call site, so the dumping lives here: one function, every caller.

    A field JSON mode cannot render must not break a run, so an un-dumpable
    model falls back to itself, which :func:`canonical_json` reprs — the old
    behavior, now the exception rather than the rule.
    """
    dump = getattr(config, "model_dump", None)
    if dump is None:
        return config
    try:
        return dump(mode="json")
    except Exception:
        return config


def compute_args_hash(resolved_config: Any = None, call_args: Any = None) -> str:
    """Hash the resolved config + call args (§D.3 Fix 1).

    Pass the *resolved* config (post-precedence, post-env, post-prompt) as a
    plain mapping — pydantic models should be dumped by the caller, which owns
    the model's serialization rules. :func:`config_payload` is that dump.
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


#: Characters that make a declared entry a pattern rather than a literal path.
_GLOB_METACHARACTERS = ("*", "?", "[")


def _is_pattern(entry: str) -> bool:
    """True when ``entry`` is a glob rather than a literal path."""
    return any(char in entry for char in _GLOB_METACHARACTERS)


def _iter_matches(base: Path, pattern: str) -> Iterator[tuple[Path, str]]:
    """Yield ``(absolute path, record key)`` for every match of one pattern.

    The record key is the path **as the declaration named it** (ADR-013):
    relative if the pattern was relative, absolute if it was absolute. There is
    no containment check. A declared input may live anywhere on the machine —
    a job body can already read any file it likes, and ``Fingerprint`` only
    stats and hashes.

    Three routes, because the three declared forms need three different
    walkers, not because the rule differs:

    - **absolute** — ``glob`` from the filesystem root; the key is the match.
    - **relative with ``..``** — ``Path.glob`` does not match ``..`` segments at
      all, so ``glob`` walks it and ``os.path.relpath`` renders the key. That
      keeps the key machine-independent, which ``resolve()`` would not.
    - **plain relative** — ``Path.glob``, and the key is ``relative_to(base)``
      computed on the **unresolved** match. Resolving here is what used to
      discard a file reached through a symlinked directory: the glob found it,
      and then ``resolve().relative_to(base)`` raised ``ValueError`` because the
      real location is outside the project.
    """
    as_path = Path(pattern)
    if as_path.is_absolute():
        for match in _glob.iglob(pattern, recursive=True):
            found = Path(match)
            yield found, found.as_posix()
        return
    if ".." in as_path.parts:
        for match in _glob.iglob(str(base / pattern), recursive=True):
            found = Path(match)
            yield found, Path(os.path.relpath(found, base)).as_posix()
        return
    for match in base.glob(pattern):
        yield match, match.relative_to(base).as_posix()


def expand_sources(root: Path | str, patterns: Iterable[str]) -> list[str]:
    """Expand source globs to sorted record keys, addressed as declared.

    Only files are returned (a directory match is not a source).

    Paths are **not** required to live under ``root``. Each is recorded the way
    the declaration wrote it — relative if declared relative, absolute if
    declared absolute (see :func:`_iter_matches`). The accepted consequence is
    that a record keyed by an absolute path does not match on another machine,
    so that machine re-runs the job once and writes its own; nothing breaks,
    the work is simply not shared. ADR-013 records why that is the honest
    behaviour and what it rules out.
    """
    base = Path(root).resolve()
    found: set[str] = set()
    for pattern in patterns:
        for match, key in _iter_matches(base, pattern):
            if not match.is_file():
                continue
            found.add(key)
    return sorted(found)


def expand_generates(
    root: Path | str, patterns: Iterable[str]
) -> tuple[list[str], list[str]]:
    """Resolve declared outputs. Returns ``(resolved, missing)``.

    ``generates`` entries are glob patterns, exactly as ``sources`` entries are.
    They were tested as literal paths — ``(root / entry).exists()`` — which is
    always False for ``dist/*.whl``, the form the ``@job`` docstring itself
    advertises. The job then reported ``output missing`` on every run and
    rebuilt forever, with no error to say why.

    **A pattern that matches nothing is a missing output, and forces a run.**
    Zero matches and an absent literal path land on the same verdict, on
    purpose: a job whose promised artifact is not there is not fresh, whatever
    its inputs say. Any other answer would reintroduce the false clean that
    making the default method consult ``generates`` exists to close.

    ``resolved`` holds absolute paths, for stat-ing. ``missing`` holds the
    declared entries **verbatim**, because that is the string the reader wrote
    and an expansion of nothing has nothing to show them.

    A non-pattern entry keeps the old existence semantics exactly, including
    that a **directory** counts — ``generates=["dist"]`` is a legal declaration
    and has nothing to do with globbing.
    """
    base = Path(root).resolve()
    resolved: set[str] = set()
    missing: list[str] = []
    for entry in patterns:
        if _is_pattern(entry):
            matched = [found.as_posix() for found, _ in _iter_matches(base, entry)]
            if matched:
                resolved.update(matched)
            else:
                missing.append(entry)
            continue
        target = base / entry
        if target.exists():
            resolved.add(target.as_posix())
        else:
            missing.append(entry)
    return sorted(resolved), missing


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
    declared_sources: Sequence[str] = (),
) -> FingerprintVerdict:
    """Decide whether a job is up to date against its stored ``record``.

    - ``none``: file checking disabled — never fresh on this axis (guards still
      decide; §D.3).
    - ``checksum``: every source's SHA-256 must match the record.
    - ``timestamp``: every declared output must exist and be no older than the
      newest source (a missing output always forces a run).

    A record written under a different ``job_version`` is stale regardless of
    files: the declaration itself changed.

    ``declared_sources`` is the *patterns* the job declared, alongside
    ``source_map``, which is what those patterns resolved to. Only the caller
    holds both, and only both together distinguish "declared nothing" from
    "declared something that matched nothing" — the second of which is a
    refusal (see :attr:`FingerprintVerdict.refused`). Passing the resolved map
    alone, as this function used to receive, makes the two indistinguishable.
    """
    if method == "none":
        return FingerprintVerdict(False, "method=none — file checking disabled")

    # Before any record check, and deliberately: the refusal is a statement
    # about the world, not about a previous run. On the *first* run there is no
    # record, so a record-first ordering would let a stage that verifies
    # nothing run to completion and report success once before the false-clean
    # even became reachable.
    if declared_sources and not source_map:
        patterns = ", ".join(declared_sources)
        return FingerprintVerdict(
            False,
            f"declared sources resolved to no files ({patterns})",
            refused=True,
        )

    if record is None:
        return FingerprintVerdict(False, "no previous run recorded")
    if job_version and record.get("job_version") not in ("", job_version):
        return FingerprintVerdict(False, "@job declaration changed since last run")

    if method == "timestamp":
        return _evaluate_timestamp(root, source_map, generates)

    # A declared output that is not on disk means the job is not up to date,
    # whatever its inputs say. `timestamp` has always enforced this ("a
    # missing output always forces a run"); `checksum` ignored `generates`
    # entirely, so a job whose sources were unchanged reported fresh with its
    # promised artifact deleted — and every downstream consumer then read a
    # record describing a file that no longer exists.
    #
    # `generates` entries are patterns (see `expand_generates`), so a pattern
    # matching nothing counts as missing — the same verdict as an absent
    # literal path, which is the only answer that keeps the rule above true.
    missing = expand_generates(root, generates)[1]
    if missing:
        return FingerprintVerdict(
            False,
            f"output missing: {', '.join(sorted(missing))}",
            tuple(sorted(missing)),
        )

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
    resolved, missing = expand_generates(root, generates)
    if missing:
        return FingerprintVerdict(
            False,
            f"output missing: {', '.join(sorted(missing))}",
            tuple(sorted(missing)),
        )
    newest_source = max(
        (entry.get("mtime", 0.0) for entry in source_map.values()), default=0.0
    )
    # Over the *resolved* set, not the declared patterns: `dist/*.whl` is not a
    # path to stat, and the oldest thing a pattern matched is what decides
    # whether the outputs are current.
    oldest_output = min(Path(out).stat().st_mtime for out in resolved)
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
