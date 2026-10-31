"""The select command: run the suite's five tasks through one selection each.

This is the arm the promptfoo suite reads. ``evals/suites/skill-router.yaml``
names five downstream tasks and the catalog option each expects; this command
replays those tasks through the same selection workflow a measured cell uses
and writes what the gate decided, once per case, to a file the suite mounts
(``FZ_SKILL_ROUTER_SELECTIONS``).

Nothing about a task is answered here. The task text is the gate's state, the
gate calls the comparator, and the case's ``outcome`` is the accepted option or
:data:`selection.ESCALATED` — so the suite measures the router, never a
hand-written mapping. The file also carries the identities it was produced
under, so a later report can refuse a selection set measured against a
different instrument.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from tests.skill_router_eval import corpus, replay, selection
from tests.skill_router_eval.catalog import Entry, derive_catalog
from tests.skill_router_eval.comparators import identity_sha256

__all__ = ["cases_of", "main", "write_selections"]

#: The comparators ``select`` can drive: the gated ones. The native arm needs
#: no selection file — it is the baseline that does not select.
COMPARATORS: tuple[str, ...] = replay.GATED

_DEFAULT_TASKS = "evals/suites/skill-router.yaml"
_FUNCTUALIZE = ".functualize"
_CASE_KEYS: tuple[str, ...] = ("case", "task", "expect")


def cases_of(path: Path) -> list[dict[str, str]]:
    """The suite's cases, as ``case``/``task``/``expect`` per test.

    Raises:
        ValueError: a test does not name all three, or names one twice.
    """
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    tests = payload.get("tests")
    if not isinstance(tests, list) or not tests:
        raise ValueError(f"{path} declares no tests")
    cases: list[dict[str, str]] = []
    seen: set[str] = set()
    for test in tests:
        variables = (test or {}).get("vars") or {}
        missing = [key for key in _CASE_KEYS if not variables.get(key)]
        if missing:
            raise ValueError(f"{path}: a test is missing {', '.join(missing)}")
        name = str(variables["case"])
        if name in seen:
            raise ValueError(f"{path}: case {name!r} is declared twice")
        seen.add(name)
        cases.append(
            {
                "case": name,
                "task": str(variables["task"]),
                "expect": str(variables["expect"]),
            }
        )
    return cases


def write_selections(path: Path, payload: Mapping[str, Any]) -> None:
    """Write the selections file, creating its directory."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def _inside(path: Path, root: Path) -> bool:
    """Whether ``path`` is ``root`` or lies under it."""
    resolved = Path(path).resolve()
    base = Path(root).resolve()
    return resolved == base or base in resolved.parents


def _parser() -> argparse.ArgumentParser:
    """The C-7 command line."""
    parser = argparse.ArgumentParser(prog="tests.skill_router_eval.select")
    parser.add_argument("--tasks", default=_DEFAULT_TASKS)
    parser.add_argument("--out", required=True)
    parser.add_argument("--comparator", choices=COMPARATORS, default="hermetic")
    parser.add_argument("--corpus", default="v1")
    parser.add_argument("--corpus-root", default=str(Path(__file__).parent / "corpus"))
    parser.add_argument("--skills-root", default=None)
    return parser


def _selections(
    *,
    cases: Sequence[Mapping[str, str]],
    comparator: str,
    provider: Any,
    entries: Sequence[Entry],
    project: Path,
) -> dict[str, dict[str, Any]]:
    """One selection per case, in the suite's order."""
    (project / _FUNCTUALIZE).mkdir(parents=True, exist_ok=True)
    chosen: dict[str, dict[str, Any]] = {}
    for case in cases:
        name = case["case"]
        walked = selection.select(
            case["task"],
            provider,
            entries=entries,
            project=project,
            scope=f"{comparator}-{name}-{replay.run_key(project)}",
        )
        evidence = dict((walked.record or {}).get("evidence") or {})
        chosen[name] = {
            "outcome": walked.outcome,
            "expected": case["expect"],
            "decided_by": walked.decided_by,
            "latency_seconds": float(evidence.get("latency_seconds") or 0.0),
            "evidence": evidence,
        }
    return chosen


def main(
    argv: list[str] | None = None,
    *,
    factories: Mapping[str, replay.Factory] | None = None,
    repo_root: Path | None = None,
) -> int:
    """Run the suite's cases through one comparator and write the selections."""
    args = _parser().parse_args(argv)
    version_dir = Path(args.corpus_root) / args.corpus
    root = Path(repo_root) if repo_root is not None else replay.REPO_ROOT
    if _inside(Path(args.out), root):
        print(f"{args.out} lies inside the repository; write it elsewhere")
        return 2
    skills_root = Path(args.skills_root) if args.skills_root else None
    try:
        entries = (
            derive_catalog(skills_root) if skills_root is not None else derive_catalog()
        )
        cases = cases_of(Path(args.tasks))
        resolved = replay.resolve_factories(factories)
        provider, identity = resolved[args.comparator](Path(args.out).resolve().parent)
        digest = identity_sha256(identity)
        with replay._scratch() as probe:
            rule_digest = replay.probe_rule_digest(entries, probe / "project")
        lock = corpus.check_lock(
            version_dir,
            entries,
            {args.comparator: digest},
            rule_digest=str(rule_digest),
            instrument_sha256=replay.instrument_sha256(root),
        )
        with replay._scratch() as scratch:
            chosen = _selections(
                cases=cases,
                comparator=args.comparator,
                provider=provider,
                entries=entries,
                project=scratch / "project",
            )
    except (corpus.CorpusError, OSError, ValueError) as error:
        print(error)
        return 2
    write_selections(
        Path(args.out),
        {
            "catalog_sha256": lock.catalog_sha256,
            "comparator": args.comparator,
            "identity_sha256": digest,
            "repo_commit": replay._repo_commit(root),
            "rule_digest": str(lock.selection.get("rule_digest")),
            "instrument_sha256": str(lock.instrument.get("sha256")),
            "cases": chosen,
        },
    )
    print(f"wrote {len(chosen)} selections to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
