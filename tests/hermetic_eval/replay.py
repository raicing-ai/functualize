"""The replay command: measure one comparator over the frozen corpus.

``main`` resolves the corpus version, refuses before writing anything when the
frozen lock and the comparator about to run disagree, then drives one cell at a
time through the real router:

    main → replay_cell → FunctualizeApp.execute →
    DecisionGateResolver(provider).resolve → decision_record → cells.jsonl

Nothing here reads a scenario's label into the request: ``build_router``
receives the scenario's ``state`` and the gate sees only that text, so a
comparator can never see the answer it is being scored against. Different
process runs of the same cell set differ the same way a re-run does — the
comparator is a fresh object per invocation, the ledger is append-only, and a
cell is never asked twice.

Runs inside whatever the corpus's lock pinned: seed, repeats and the time box
come from the lock, never from flags. Exit codes are C-6's: 0 for a complete
run, a budget stop or a rate-limit pause; 2 for a refusal before any write; 3
for a frontier cell that answered with a model other than the one requested.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from functualize.app import FunctualizeApp
from functualize.app.utils import ScopeStore, decision_record
from functualize.plugin import DecisionGateResolver, DecisionProvider
from functualize.types import RunRequest
from tests.hermetic_eval import corpus
from tests.hermetic_eval._router import load_router
from tests.hermetic_eval.comparators import (
    DeterministicBaseline,
    FrontierRouter,
    hermetic,
    hermetic_identity,
    identity_sha256,
)

__all__ = ["freeze", "ledger_rows", "main", "replay_cell"]

#: The three comparators, in the order reports read them.
COMPARATORS: tuple[str, ...] = ("hermetic", "frontier", "deterministic")

#: A factory receives the run directory and returns a provider and its identity.
Factory = Callable[[Path], tuple[DecisionProvider, dict[str, object]]]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_STATE = Path(".local") / "state"
_STATE_DIR = "functualize-hermetic-eval"
_SCENARIOS = "scenarios.jsonl"
_RUN_JSON = "run.json"
_CELLS = "cells.jsonl"
_PROJECT = "project"
_FUNCTUALIZE = ".functualize"
_FRONTIER_CWD = "frontier-cwd"
_APP_NAME = "hermetic-router"
_JOB = "router"
_SURFACE = "app.execute"
_GATE = "route"
_DECISION = "decision"
_FRONTIER = "frontier"
_RATE_LIMITED = "rate_limited"
_INVALID_MODEL = "invalid_model"
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


def _scope(comparator: str, repeat: int, scenario_id: str) -> str:
    """The workflow scope one cell runs under: unique per comparator and cell."""
    return f"{comparator}-r{repeat}-{scenario_id}"


def _default_factories() -> dict[str, Factory]:
    """The three real comparators, each built against the run directory."""

    def deterministic(_run_dir: Path) -> tuple[DecisionProvider, dict[str, object]]:
        baseline = DeterministicBaseline()
        return (baseline, baseline.identity())

    def plugin(_run_dir: Path) -> tuple[DecisionProvider, dict[str, object]]:
        return (hermetic(), hermetic_identity())

    def frontier(run_dir: Path) -> tuple[DecisionProvider, dict[str, object]]:
        router = FrontierRouter(cwd=str(run_dir / _FRONTIER_CWD))
        return (router, router.identity())

    return {"deterministic": deterministic, "hermetic": plugin, "frontier": frontier}


def _factories(injected: Mapping[str, Factory] | None) -> dict[str, Factory]:
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


def _repo_commit() -> str:
    """The checked-out commit, for the header.

    The one process this command spawns, and only when it writes a header; the
    offline tests replace it, because no test may spawn one (spec B-28). The
    import sits here so the module stays free of a top-level ``subprocess``:
    only ``comparators.py`` imports it that way.
    """
    import subprocess

    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=_REPO_ROOT,
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
    started_at: str,
) -> dict[str, Any]:
    """The C-7 header: what ran, over which corpus, from which commit."""
    return {
        "run_id": run_id,
        "comparator": comparator,
        "identity": dict(identity),
        "identity_sha256": digest,
        "corpus": lock.version,
        "scenarios_sha256": lock.scenarios_sha256,
        "seed": lock.seed,
        "repeats": lock.repeats,
        "repo_commit": _repo_commit(),
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
    if header.get("seed") != lock.seed or header.get("repeats") != lock.repeats:
        return "run directory holds a different seed or repeat count"
    return None


def ledger_rows(path: Path) -> list[dict[str, Any]]:
    """Parse the ledger's lines; a missing ledger is an empty one."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{number} is not a JSON object")
        rows.append(payload)
    return rows


def _append(ledger: Path, row: Mapping[str, Any]) -> None:
    """Append one ledger line, flushed and fsynced before the next cell."""
    line = json.dumps(row, sort_keys=True) + "\n"
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def _frontier_block(call: Any) -> dict[str, Any]:
    """The S-2 block: what answered, and what it cost."""
    return {
        "cli_version": call.cli_version,
        "model": call.model,
        "model_mismatch": bool(call.model_mismatch),
        "usage": call.usage,
    }


def _ledger_row(
    *,
    cell: int,
    repeat: int,
    scenario: corpus.Scenario,
    comparator: str,
    status: str,
    started_at: str,
    record: Mapping[str, Any] | None = None,
    frontier: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One S-1 row: gate values copied from the record, never recomputed."""
    evidence = dict((record or {}).get("evidence") or {})
    state = dict(evidence.get("state") or {})
    rule = dict(evidence.get("rule") or {})
    return {
        "cell": cell,
        "repeat": repeat,
        "scenario": scenario.id,
        "expected": scenario.expected,
        "stratum": scenario.stratum,
        "scope": _scope(comparator, repeat, scenario.id),
        "status": status,
        "route": (record or {}).get("route"),
        "decided_by": (record or {}).get("decided_by"),
        "verdict": evidence.get("verdict"),
        "proposal": evidence.get("proposal"),
        "distribution": evidence.get("distribution"),
        "probability": evidence.get("probability"),
        "margin": evidence.get("margin"),
        "confidence": evidence.get("confidence"),
        "failure": evidence.get("failure"),
        "latency_seconds": evidence.get("latency_seconds"),
        "input_tokens": evidence.get("input_tokens"),
        "output_tokens": evidence.get("output_tokens"),
        "state_sha256": state.get("sha256"),
        "rule_digest": rule.get("digest"),
        "frontier": dict(frontier) if frontier is not None else None,
        "started_at": started_at,
    }


def _last_call(provider: DecisionProvider) -> Any | None:
    """The provider's last recorded call, when the comparator keeps them."""
    calls = getattr(provider, "calls", None)
    if not calls:
        return None
    return calls[-1]


def replay_cell(
    *,
    cell: int,
    repeat: int,
    scenario: corpus.Scenario,
    comparator: str,
    provider: DecisionProvider,
    run_dir: Path,
    now: Callable[[], datetime],
) -> dict[str, Any]:
    """Drive one cell through the real router and append its ledger line.

    The project directory is entered for the duration of the cell only: the
    run's scratch state lives under ``run_dir/project`` and the process's own
    working directory is restored whatever the app does.
    """
    project = run_dir / _PROJECT
    (project / _FUNCTUALIZE).mkdir(parents=True, exist_ok=True)
    scope = _scope(comparator, repeat, scenario.id)
    started_at = _iso(now())
    previous = Path.cwd()
    os.chdir(project)
    try:
        app = FunctualizeApp(name=_APP_NAME)
        load_router().build_router(app, scenario.state)
        app.gates.register_gate_strategy(_DECISION, DecisionGateResolver(provider))
        app.execute(
            RunRequest(job_name=_JOB, surface=_SURFACE, workflow_scope_id=scope)
        )
        record = dict(decision_record(ScopeStore(app.substrate), scope, _GATE) or {})
    finally:
        os.chdir(previous)

    call = _last_call(provider) if comparator == _FRONTIER else None
    verdict = (record.get("evidence") or {}).get("verdict")
    if call is not None and call.model_mismatch:
        status = _INVALID_MODEL
    elif verdict == "provider_failed":
        status = _FAILED
    else:
        status = _ROUTED
    row = _ledger_row(
        cell=cell,
        repeat=repeat,
        scenario=scenario,
        comparator=comparator,
        status=status,
        started_at=started_at,
        record=record,
        frontier=_frontier_block(call) if call is not None else None,
    )
    _append(run_dir / _CELLS, row)
    return row


def freeze(
    version_dir: Path,
    factories: Mapping[str, Factory],
    now: Callable[[], datetime],
) -> int:
    """Write the version's lock file from the three comparators' identities."""
    identities = {
        name: identity_sha256(factory(version_dir)[1])
        for name, factory in factories.items()
    }
    try:
        lock = corpus.write_lock(version_dir, identities, frozen_at=_iso(now()))
    except (corpus.CorpusError, OSError, ValueError) as error:
        print(error)
        return 2
    print(f"frozen {lock.version} at {lock.frozen_at}")
    return 0


def _parser() -> argparse.ArgumentParser:
    """The C-6 command line."""
    parser = argparse.ArgumentParser(prog="tests.hermetic_eval.replay")
    parser.add_argument("--corpus", default="v1")
    parser.add_argument("--comparator", choices=COMPARATORS, default=None)
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--budget-seconds", type=float, default=_DEFAULT_BUDGET)
    parser.add_argument("--corpus-root", default=str(Path(__file__).parent / "corpus"))
    parser.add_argument("--freeze", action="store_true")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    factories: Mapping[str, Factory] | None = None,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] = _utc_now,
) -> int:
    """Run, resume or freeze one comparator's measurement."""
    args = _parser().parse_args(argv)
    version_dir = Path(args.corpus_root) / args.corpus
    resolved = _factories(factories)
    if args.freeze:
        return freeze(version_dir, resolved, now)
    comparator: str | None = args.comparator
    if comparator is None:
        print("--comparator is required unless --freeze is given")
        return 2

    moment = now()
    run_id = f"{comparator}-{_utc(moment).strftime('%Y%m%dT%H%M%SZ')}"
    run_dir = Path(args.run_dir) if args.run_dir else _default_run_dir(run_id)
    print(run_dir)
    provider, identity = resolved[comparator](run_dir)
    digest = identity_sha256(identity)
    try:
        lock = corpus.check_lock(version_dir, {comparator: digest})
        scenarios = corpus.load_corpus(version_dir / _SCENARIOS)
        header = _read_header(run_dir)
        rows = ledger_rows(run_dir / _CELLS)
    except (corpus.CorpusError, OSError, ValueError) as error:
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
                    _ledger_row(
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
            run_dir=run_dir,
            now=now,
        )
        failure = dict(row["failure"] or {})
        if row["status"] == _INVALID_MODEL:
            print(_INVALID_MODEL)
            return 3
        if failure.get("kind") == _RATE_LIMITED:
            # B-12: every rate-limit failure pauses the invocation — a provider
            # that names no reset time pauses too, on "resume after unknown",
            # rather than spending the next cells on a spent window.
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
