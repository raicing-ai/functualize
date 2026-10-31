"""The replay command: measure one comparator over the frozen corpus.

Every row this command writes came through the same code a production request
would: :func:`selection.select` walks the real ``select`` workflow through a
fresh app, the decision gate calls the comparator, and the row is the gate's
own record copied field by field. Nothing here decides what a cell's answer
*means* — that is the corpus's ``expected`` and the metrics' job.

Four comparators, two shapes. ``hermetic``, ``frontier`` and ``deterministic``
are ``DecisionProvider``\\ s, so they go through the gate and every row is
gated. ``native`` is the shipped behaviour — the agent reaches for a skill with
the ``Skill`` tool — so it has no distribution to threshold, no gate to decide,
and its row is built from :class:`comparators.NativeCell` instead.

What a run may not do is change its mind halfway. Each start and resume derives
the catalog, the rule digest and the instrument digest from the working tree
and asks :func:`corpus.check_lock` whether the corpus is still the one that was
frozen; a cell whose own recorded rule digest disagrees is not appended at all.
The result is that a measurement is either the frozen question or no
measurement.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tests.hermetic_eval.replay import ledger_rows
from tests.skill_router_eval import corpus, selection
from tests.skill_router_eval.catalog import Entry, derive_catalog
from tests.skill_router_eval.comparators import (
    FrontierRouter,
    KeywordTable,
    NativeCell,
    NativeOverrideError,
    NativeRouter,
    hermetic,
    hermetic_identity,
    identity_sha256,
)

__all__ = [
    "COMPARATORS",
    "GATED",
    "PROBE_STATE",
    "REPO_ROOT",
    "run_key",
    "Factory",
    "resolve_factories",
    "freeze",
    "instrument_sha256",
    "ledger_rows",
    "main",
    "probe_rule_digest",
    "replay_cell",
]

#: The four comparators, in the order the reports read them.
COMPARATORS: tuple[str, ...] = ("hermetic", "frontier", "deterministic", "native")

#: The gated ones: the three whose answer is a distribution a rule accepts.
GATED: tuple[str, ...] = tuple(name for name in COMPARATORS if name != "native")

#: The request the rule digest is probed with. It matches no keyword rule, so
#: the probe measures the declaration, not an answer.
PROBE_STATE = "func: command not found"

#: A factory receives the run directory and returns a comparator and its identity.
Factory = Callable[[Path], tuple[Any, dict[str, object]]]

REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_STATE = Path(".local") / "state"
_STATE_DIR = "functualize-skill-router-eval"
_SCENARIOS = "scenarios.jsonl"
_RUN_JSON = "run.json"
_CELLS = "cells.jsonl"
_PROJECT = "project"
_FUNCTUALIZE = ".functualize"
_FRONTIER_CWD = "frontier-cwd"
_PROBE_SCOPE = "probe"
_NATIVE = "native"
_RATE_LIMITED = "rate_limited"
_INVALID_MODEL = "invalid_model"
_PROVIDER_FAILED = "provider_failed"
_FAILED = "failed"
_ROUTED = "routed"
_NOT_ATTEMPTED = "not_attempted"
_DEFAULT_BUDGET = 360.0


def _utc_now() -> datetime:
    """The current UTC time: the one clock the run's timestamps come from."""
    return datetime.now(UTC)


def _utc(moment: datetime) -> datetime:
    """The moment in UTC; a naive one is read as already UTC."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _iso(moment: datetime) -> str:
    """Render a moment as UTC ISO-8601 with a ``Z`` suffix."""
    return _utc(moment).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_iso(text: str) -> datetime:
    """Read back a timestamp written by :func:`_iso`."""
    return datetime.fromisoformat(text)


def run_key(path: Path) -> str:
    """A short digest of an absolute directory, for a scope id that cannot collide.

    A scope id is the key a walk's state is stored under, and the engine keeps
    a per-process view of it too, so two walks that share an id share a walk.
    The cell's own name is not enough — the same comparator and scenario recur
    in every run directory — so the directory the walk runs in is part of the
    id, and a resumed run re-enters exactly the scopes it already owns.
    """
    digest = hashlib.sha256(str(Path(path).resolve()).encode("utf-8"))
    return digest.hexdigest()[:12]


def _scope(comparator: str, repeat: int, scenario_id: str, run_dir: Path) -> str:
    """The workflow scope one cell runs under: unique per run directory and cell."""
    return f"{comparator}-r{repeat}-{scenario_id}-{run_key(run_dir)}"


def _probe_scope(project: Path) -> str:
    """The probe's scope id, unique to the scratch project it runs in."""
    return f"{_PROBE_SCOPE}-{run_key(project)}"


def _selection_block(entries: Sequence[Entry]) -> dict[str, Any]:
    """The C-3 ``selection`` block: the declaration the gate is configured from."""
    decide = selection.select_decision(entries)
    return {
        "field": decide.field,
        "instructions": decide.instructions,
        "options": dict(decide.options),
        "accept_at": decide.accept_at,
        "min_margin": decide.min_margin,
        "fallback": decide.fallback,
    }


def instrument_sha256(repo_root: Path) -> str:
    """The digest of everything that decides what a cell asks or how it is read.

    Computed like a skill digest: each file's repository-relative path, a NUL,
    its bytes and a NUL, in sorted path order — so a renamed file and an edited
    one are both a different instrument.

    Raises:
        corpus.CorpusError: a pinned file is missing.
    """
    root = Path(repo_root)
    digest = hashlib.sha256()
    for name in sorted(corpus.INSTRUMENT_FILES):
        path = root / name
        if not path.is_file():
            raise corpus.CorpusError(f"instrument file {name} is missing from {root}")
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


@contextlib.contextmanager
def _scratch() -> Iterator[Path]:
    """A throwaway directory to walk the probe in."""
    with tempfile.TemporaryDirectory(prefix="skill-router-probe-") as name:
        yield Path(name)


def probe_rule_digest(entries: Sequence[Entry], project: Path) -> str | None:
    """The rule digest of one probe selection, for the lock.

    The probe is a real walk — the same workflow, gate and record a measured
    cell uses — so the digest in the lock is the digest a cell will carry. It
    runs in ``project``, a scratch directory the caller owns and throws away.
    """
    project = Path(project)
    (project / _FUNCTUALIZE).mkdir(parents=True, exist_ok=True)
    chosen = selection.select(
        PROBE_STATE,
        KeywordTable(),
        entries=entries,
        project=project,
        scope=_probe_scope(project),
    )
    return chosen.rule_digest


def _default_factories() -> dict[str, Factory]:
    """The four real comparators, each built against the run directory."""

    def deterministic(_run_dir: Path) -> tuple[Any, dict[str, object]]:
        table = KeywordTable()
        return (table, table.identity())

    def plugin(_run_dir: Path) -> tuple[Any, dict[str, object]]:
        return (hermetic(), hermetic_identity())

    def frontier(run_dir: Path) -> tuple[Any, dict[str, object]]:
        router = FrontierRouter(cwd=str(run_dir / _FRONTIER_CWD))
        return (router, router.identity())

    def native(_run_dir: Path) -> tuple[Any, dict[str, object]]:
        router = NativeRouter()
        return (router, router.identity())

    return {
        "deterministic": deterministic,
        "hermetic": plugin,
        "frontier": frontier,
        "native": native,
    }


def resolve_factories(injected: Mapping[str, Factory] | None) -> dict[str, Factory]:
    """The comparator factories, with any injected one overriding its default."""
    resolved = _default_factories()
    if injected is not None:
        resolved.update(injected)
    return resolved


def _default_run_dir(run_id: str) -> Path:
    """The run id under ``$XDG_STATE_HOME`` (else ``~/.local/state``)."""
    root = os.environ.get("XDG_STATE_HOME")
    base = Path(root) if root else Path.home() / _LOCAL_STATE
    return base / _STATE_DIR / run_id


def _repo_commit(repo_root: Path) -> str:
    """The checked-out commit, for the header.

    The one process this command spawns, and only when it writes a header; the
    offline tests replace it, because no test may spawn one. The import sits
    here so the module stays free of a top-level ``subprocess``.
    """
    import subprocess

    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return "unknown"
    return completed.stdout.strip() or "unknown"


def _header(
    *,
    run_id: str,
    comparator: str,
    identity: Mapping[str, object],
    digest: str,
    lock: corpus.Lock,
    repo_commit: str,
    started_at: str,
) -> dict[str, Any]:
    """The C-8 header: what ran, over which corpus, under which identities."""
    return {
        "run_id": run_id,
        "comparator": comparator,
        "identity": dict(identity),
        "identity_sha256": digest,
        "corpus": lock.version,
        "scenarios_sha256": lock.scenarios_sha256,
        "catalog_sha256": lock.catalog_sha256,
        "rule_digest": lock.selection.get("rule_digest"),
        "instrument_sha256": lock.instrument.get("sha256"),
        "seed": lock.seed,
        "repeats": lock.repeats,
        "repo_commit": repo_commit,
        "started_at": started_at,
    }


def _read_header(run_dir: Path) -> dict[str, Any] | None:
    """The run directory's header, or ``None`` when it has none yet."""
    path = run_dir / _RUN_JSON
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} is not a JSON object")
    return payload


def _write_header(run_dir: Path, header: Mapping[str, Any]) -> None:
    """Write the run directory's header once, when the first cell starts."""
    (run_dir / _RUN_JSON).write_text(
        json.dumps(header, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _header_matches(
    header: Mapping[str, Any], comparator: str, digest: str, lock: corpus.Lock
) -> str | None:
    """Say why a resumed run may not continue, or ``None`` when it may."""
    if header.get("comparator") != comparator:
        return f"run directory holds {header.get('comparator')}, not {comparator}"
    if header.get("identity_sha256") != digest:
        return "run directory holds a different comparator identity"
    if header.get("scenarios_sha256") != lock.scenarios_sha256:
        return "run directory holds a different corpus digest"
    if header.get("catalog_sha256") != lock.catalog_sha256:
        return "run directory holds a different catalog digest"
    if header.get("rule_digest") != lock.selection.get("rule_digest"):
        return "run directory holds a different selection rule"
    if header.get("instrument_sha256") != lock.instrument.get("sha256"):
        return "run directory holds a different instrument digest"
    if header.get("seed") != lock.seed or header.get("repeats") != lock.repeats:
        return "run directory holds a different seed or repeat count"
    return None


def _append(ledger: Path, row: Mapping[str, Any]) -> None:
    """Append one ledger line, flushed and fsynced before the next cell."""
    line = json.dumps(row) + "\n"
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def _evidence(record: Mapping[str, Any] | None) -> dict[str, Any]:
    """The decision rung's evidence, or an empty mapping when there is none."""
    return dict((record or {}).get("evidence") or {})


def _row(
    *,
    cell: int,
    repeat: int,
    scenario: corpus.Scenario,
    comparator: str,
    status: str,
    started_at: str,
    route: str | None = None,
    decided_by: str | None = None,
    evidence: Mapping[str, Any] | None = None,
    failure: Mapping[str, Any] | None = None,
    frontier: Mapping[str, Any] | None = None,
    native: Mapping[str, Any] | None = None,
    rule_digest: str | None = None,
    latency_seconds: float | None = None,
) -> dict[str, Any]:
    """One C-8 row, with its keys in the contract's order.

    Every value is copied from the gate's record or from the native cell; none
    is recomputed here, so a reader can always check a row against the evidence
    it came from.
    """
    found = dict(evidence or {})
    return {
        "cell": cell,
        "repeat": repeat,
        "scenario": scenario.id,
        "expected": scenario.expected,
        "stratum": scenario.stratum,
        "comparator": comparator,
        "status": status,
        "route": route,
        "decided_by": decided_by,
        "proposal": found.get("proposal"),
        "distribution": found.get("distribution"),
        "probability": found.get("probability"),
        "margin": found.get("margin"),
        "confidence": found.get("confidence"),
        "verdict": found.get("verdict"),
        "failure": dict(failure) if failure is not None else found.get("failure"),
        "rule_digest": rule_digest,
        "latency_seconds": (
            found.get("latency_seconds") if latency_seconds is None else latency_seconds
        ),
        "input_tokens": found.get("input_tokens"),
        "output_tokens": found.get("output_tokens"),
        "frontier": dict(frontier) if frontier is not None else None,
        "native": dict(native) if native is not None else None,
        "started_at": started_at,
    }


def _frontier_block(provider: Any) -> dict[str, Any] | None:
    """The frontier block of the provider's last call, when it keeps calls."""
    calls = getattr(provider, "calls", None)
    if not calls:
        return None
    call = calls[-1]
    return {"model": call.model, "model_mismatch": bool(call.model_mismatch)}


def _native_block(cell: NativeCell) -> dict[str, Any]:
    """C-8's ``native`` block: the cell's fields, verbatim."""
    return {
        "selected": cell.selected,
        "error": cell.error,
        "model": cell.model,
        "cost_usd": cell.cost_usd,
    }


def replay_cell(
    *,
    cell: int,
    repeat: int,
    scenario: corpus.Scenario,
    comparator: str,
    provider: Any,
    entries: Sequence[Entry],
    run_dir: Path,
    rule_digest: str | None,
    now: Callable[[], datetime],
) -> dict[str, Any] | None:
    """Drive one cell and return its row, or ``None`` when the rule moved.

    ``None`` means the cell's own recorded rule digest is not the lock's: the
    cell is not appended and the invocation refuses. Nothing about a cell is
    written by this function; the caller appends.
    """
    started_at = _iso(now())
    if comparator == _NATIVE:
        native = provider.select(scenario.state)
        return _row(
            cell=cell,
            repeat=repeat,
            scenario=scenario,
            comparator=comparator,
            status=_FAILED if native.failed is not None else _ROUTED,
            started_at=started_at,
            route=native.route,
            decided_by=_NATIVE,
            failure=native.failed,
            native=_native_block(native),
            latency_seconds=native.latency_seconds,
        )

    project = run_dir / _PROJECT
    (project / _FUNCTUALIZE).mkdir(parents=True, exist_ok=True)
    chosen = selection.select(
        scenario.state,
        provider,
        entries=entries,
        project=project,
        scope=_scope(comparator, repeat, scenario.id, run_dir),
    )
    recorded = chosen.rule_digest
    if rule_digest is not None and recorded != rule_digest:
        return None

    evidence = _evidence(chosen.record)
    frontier = _frontier_block(provider) if comparator == "frontier" else None
    if frontier is not None and frontier["model_mismatch"]:
        status = _INVALID_MODEL
    elif evidence.get("verdict") == _PROVIDER_FAILED:
        status = _FAILED
    else:
        status = _ROUTED
    return _row(
        cell=cell,
        repeat=repeat,
        scenario=scenario,
        comparator=comparator,
        status=status,
        started_at=started_at,
        route=chosen.outcome,
        decided_by=chosen.decided_by,
        evidence=evidence,
        frontier=frontier,
        rule_digest=recorded,
    )


def freeze(
    version_dir: Path,
    entries: Sequence[Entry],
    factories: Mapping[str, Factory],
    *,
    repo_root: Path,
    now: Callable[[], datetime],
) -> int:
    """Write the version's lock from the catalog, the probe and the identities."""
    try:
        with _scratch() as scratch:
            rule_digest = probe_rule_digest(entries, scratch / "project")
        instrument = instrument_sha256(repo_root)
        identities = {
            name: identity_sha256(factory(version_dir)[1])
            for name, factory in factories.items()
            if name in COMPARATORS
        }
        lock = corpus.write_lock(
            version_dir,
            entries,
            identities,
            selection=_selection_block(entries),
            rule_digest=str(rule_digest),
            instrument_sha256=instrument,
            frozen_at=_iso(now()),
        )
    except (corpus.CorpusError, NativeOverrideError, OSError, ValueError) as error:
        print(error)
        return 2
    print(f"frozen {lock.version} at {lock.frozen_at}")
    return 0


def _parser() -> argparse.ArgumentParser:
    """The C-6 command line."""
    parser = argparse.ArgumentParser(prog="tests.skill_router_eval.replay")
    parser.add_argument("--corpus", default="v1")
    parser.add_argument("--comparator", choices=COMPARATORS, default=None)
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--budget-seconds", type=float, default=_DEFAULT_BUDGET)
    parser.add_argument("--corpus-root", default=str(Path(__file__).parent / "corpus"))
    parser.add_argument("--skills-root", default=None)
    parser.add_argument("--freeze", action="store_true")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    factories: Mapping[str, Factory] | None = None,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] = _utc_now,
    repo_root: Path | None = None,
) -> int:
    """Run, resume or freeze one comparator's measurement."""
    args = _parser().parse_args(argv)
    version_dir = Path(args.corpus_root) / args.corpus
    resolved = resolve_factories(factories)
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    skills_root = Path(args.skills_root) if args.skills_root else None
    try:
        entries = (
            derive_catalog(skills_root) if skills_root is not None else derive_catalog()
        )
    except (OSError, ValueError) as error:
        print(error)
        return 2
    if args.freeze:
        return freeze(version_dir, entries, resolved, repo_root=root, now=now)
    comparator: str | None = args.comparator
    if comparator is None:
        print("--comparator is required unless --freeze is given")
        return 2

    moment = now()
    run_id = f"{comparator}-{_utc(moment).strftime('%Y%m%dT%H%M%SZ')}"
    run_dir = Path(args.run_dir) if args.run_dir else _default_run_dir(run_id)
    print(run_dir)
    try:
        provider, identity = resolved[comparator](run_dir)
        digest = identity_sha256(identity)
        with _scratch() as scratch:
            rule_digest = probe_rule_digest(entries, scratch / "project")
        lock = corpus.check_lock(
            version_dir,
            entries,
            {comparator: digest},
            rule_digest=str(rule_digest),
            instrument_sha256=instrument_sha256(root),
        )
        scenarios = corpus.load_corpus(version_dir / _SCENARIOS)
        header = _read_header(run_dir)
        rows = ledger_rows(run_dir / _CELLS)
    except (
        corpus.CorpusError,
        NativeOverrideError,
        OSError,
        ValueError,
    ) as error:
        print(error)
        return 2
    if header is not None:
        why = _header_matches(header, comparator, digest, lock)
        if why is not None:
            print(why)
            return 2

    cells = corpus.ordered_cells(
        [scenario.id for scenario in scenarios], seed=lock.seed, repeats=lock.repeats
    )
    by_id = {scenario.id: scenario for scenario in scenarios}
    ledger = run_dir / _CELLS
    done = len(rows)
    remaining = cells[done:]
    expected = lock.selection.get("rule_digest") if comparator != _NATIVE else None
    run_dir.mkdir(parents=True, exist_ok=True)
    if header is None:
        _write_header(
            run_dir,
            _header(
                run_id=run_id,
                comparator=comparator,
                identity=identity,
                digest=digest,
                lock=lock,
                repo_commit=_repo_commit(root),
                started_at=_iso(moment),
            ),
        )
    (run_dir / _PROJECT / _FUNCTUALIZE).mkdir(parents=True, exist_ok=True)
    (run_dir / _FRONTIER_CWD).mkdir(parents=True, exist_ok=True)

    started_at = header.get("started_at") if header is not None else None
    if remaining and started_at:
        closed = _parse_iso(str(started_at)) + timedelta(hours=lock.time_box_hours)
        if _utc(moment) > closed:
            for offset, (repeat, scenario_id) in enumerate(remaining):
                _append(
                    ledger,
                    _row(
                        cell=done + offset + 1,
                        repeat=repeat,
                        scenario=by_id[scenario_id],
                        comparator=comparator,
                        status=_NOT_ATTEMPTED,
                        started_at=_iso(now()),
                    ),
                )
            print("run complete")
            return 0

    start = clock()
    for offset, (repeat, scenario_id) in enumerate(remaining):
        if clock() - start >= float(args.budget_seconds):
            print(f"budget reached; next cell {done + offset + 1}")
            return 0
        row = replay_cell(
            cell=done + offset + 1,
            repeat=repeat,
            scenario=by_id[scenario_id],
            comparator=comparator,
            provider=provider,
            entries=entries,
            run_dir=run_dir,
            rule_digest=expected,
            now=now,
        )
        if row is None:
            print(
                f"selection rule changed at cell {done + offset + 1}; "
                f"expected {expected}"
            )
            return 2
        failure = dict(row["failure"] or {})
        if row["status"] == _INVALID_MODEL:
            print(_INVALID_MODEL)
            return 3
        _append(ledger, row)
        if failure.get("kind") == _RATE_LIMITED:
            # Every rate-limit failure pauses the invocation — a provider that
            # names no reset time pauses too, on "resume after unknown", rather
            # than spending the next cells on a spent window.
            retry_after = failure.get("retry_after")
            if retry_after is None:
                print("resume after unknown")
            else:
                print(
                    f"resume after "
                    f"{_iso(now() + timedelta(seconds=float(retry_after)))}"
                )
            return 0
    print("run complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
