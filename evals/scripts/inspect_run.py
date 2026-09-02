#!/usr/bin/env python3
"""Unpack the last eval run so you can read what the agent actually did.

`promptfoo view` shows scores. This shows the work: the files the agent wrote,
the commands it ran, which skills it loaded, and why each assertion landed —
one directory per case, on disk, greppable.

    npm run inspect                  # summary of the latest run
    npm run inspect -- --extract     # ...and write everything to results/runs/
    npm run inspect -- --failures    # only cases that failed
    npm run inspect -- --eval <id>   # a specific run
    npm run inspect -- --list        # what runs are available
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import textwrap
from collections import defaultdict
from pathlib import Path

DB = Path.home() / ".promptfoo" / "promptfoo.db"
OUT = Path(__file__).resolve().parent.parent / "results" / "runs"


def connect() -> sqlite3.Connection:
    if not DB.exists():
        raise SystemExit(f"No promptfoo database at {DB} — has an eval run yet?")
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def evals(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "select id, description, created_at from evals order by created_at desc limit 25"
        )
    )


def as_dict(raw: str | None) -> dict:
    """Provider output survives the DB as JSON, sometimes double-encoded."""
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {"text": value}
    return value if isinstance(value, dict) else {}


def load(conn: sqlite3.Connection, eval_id: str) -> list[dict]:
    cases = []
    for row in conn.execute(
        "select * from eval_results where eval_id=? order by test_idx", (eval_id,)
    ):
        test_case = as_dict(row["test_case"])
        response = as_dict(row["response"])
        output = response.get("output")
        output = output if isinstance(output, dict) else as_dict(json.dumps(output))
        grading = as_dict(row["grading_result"])
        cases.append(
            {
                "idx": row["test_idx"],
                "description": test_case.get("description") or "",
                "vars": test_case.get("vars") or {},
                "provider": (as_dict(row["provider"]) or {}).get("label")
                or row["provider"],
                "success": bool(row["success"]),
                "score": row["score"],
                "cost": row["cost"] or 0.0,
                "error": row["error"],
                # promptfoo's ResultFailureReason: 0 NONE, 1 ASSERT, 2 ERROR.
                # `error` is populated for both, so it cannot tell "the skill
                # was wrong" from "the run never happened" — this can.
                "errored": ("failure_reason" in row and row["failure_reason"] == 2),
                "output": output,
                "reasons": [
                    c.get("reason", "")
                    for c in (grading.get("componentResults") or [])
                    if not c.get("pass", True)
                ]
                or (
                    [grading["reason"]]
                    if grading.get("reason") and not row["success"]
                    else []
                ),
            }
        )
    return cases


def label(case: dict) -> str:
    """Something short and recognisable for a case with no description."""
    if case["description"]:
        return case["description"]
    variables = case["vars"]
    for key in ("task", "query"):
        if variables.get(key):
            return " ".join(str(variables[key]).split())[:70]
    return f"case {case['idx']}"


def summarise(cases: list[dict], failures_only: bool) -> None:
    # Group by the case's identity, not its row index: with `--repeat 3`
    # promptfoo gives each repeat a distinct test_idx, so indexing by it splits
    # one case into three [0/1] rows and hides whether a failure is consistent
    # or noise.
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for case in cases:
        variables = case["vars"]
        identity = (
            variables.get("query") or variables.get("task") or case["description"]
        )
        grouped[(str(identity)[:120], case["provider"])].append(case)

    total_cost = sum(c["cost"] for c in cases)
    passed = sum(c["success"] for c in cases)
    print(f"{len(cases)} runs · {passed} passed · ${total_cost:.2f}\n")

    for (_identity, provider), runs in sorted(grouped.items()):
        ok = sum(r["success"] for r in runs)
        if failures_only and ok == len(runs):
            continue
        mark = "✔" if ok == len(runs) else ("✖" if ok == 0 else "~")
        print(f"{mark} [{ok}/{len(runs)}] {provider}  {label(runs[0])}")

        first = runs[0]
        out = first["output"]
        if out.get("skills_loaded") is not None:
            got = [r["output"].get("selected") for r in runs]
            print(f"      expected={first['vars'].get('expect')!r}  got={got}")
        if out.get("bash_commands"):
            for command in out["bash_commands"][:4]:
                print(f"      $ {' '.join(command.split())[:74]}")
        for check in out.get("checks") or []:
            flag = "ok" if check["exit_code"] == 0 else f"x{check['exit_code']}"
            print(f"      [{flag}] {check['command'][:66]}")
        for reason in dict.fromkeys(r for run in runs for r in run["reasons"]):
            print(
                textwrap.fill(
                    reason, 100, initial_indent="      → ", subsequent_indent="        "
                )
            )
        if first["errored"]:
            print(f"      ! harness error: {str(first['error'])[:140]}")
        print()


def extract(cases: list[dict], eval_id: str) -> Path:
    """Write each run's produced files and trace to a readable directory."""
    root = OUT / eval_id
    for i, case in enumerate(cases):
        name = f"{case['idx']:02d}-{case['provider']}-{i}"
        folder = root / "".join(
            ch if ch.isalnum() or ch in "-_" else "-" for ch in name
        )
        folder.mkdir(parents=True, exist_ok=True)

        out = case["output"]
        (folder / "case.json").write_text(
            json.dumps(
                {
                    k: case[k]
                    for k in (
                        "description",
                        "vars",
                        "provider",
                        "success",
                        "score",
                        "cost",
                        "error",
                        "reasons",
                    )
                },
                indent=2,
            )
        )

        # The agent's own work, laid out as it wrote it.
        for path, body in (out.get("files") or {}).items():
            target = folder / "workspace" / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body)

        trace = []
        for call in out.get("tool_calls") or []:
            payload = call.get("input") or {}
            detail = (
                payload.get("command")
                or payload.get("file_path")
                or payload.get("skill")
                or ""
            )
            trace.append(f"{call['name']}: {detail}")
        if trace:
            (folder / "trace.txt").write_text("\n".join(trace) + "\n")
        if out.get("checks"):
            (folder / "checks.txt").write_text(
                "\n\n".join(
                    f"$ {c['command']}\nexit {c['exit_code']}\n{c.get('stdout', '')}"
                    f"{c.get('stderr', '')}"
                    for c in out["checks"]
                )
            )
        if out.get("text"):
            (folder / "answer.md").write_text(out["text"])
    return root


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval", dest="eval_id")
    parser.add_argument(
        "--extract",
        action="store_true",
        help="write files, traces and answers to results/runs/",
    )
    parser.add_argument("--failures", action="store_true", help="only failing cases")
    parser.add_argument("--list", action="store_true", help="list available runs")
    args = parser.parse_args()

    conn = connect()
    available = evals(conn)
    if not available:
        raise SystemExit("No eval runs recorded yet.")

    if args.list:
        for row in available:
            print(f"{row['id']}  {(row['description'] or '(no description)')[:60]}")
        return 0

    eval_id = args.eval_id or available[0]["id"]
    print(f"eval: {eval_id}\n")
    cases = load(conn, eval_id)
    if not cases:
        raise SystemExit(f"No results stored for {eval_id}")

    summarise(cases, args.failures)

    if args.extract:
        root = extract(cases, eval_id)
        written = sum(1 for _ in root.rglob("*") if _.is_file())
        print(f"extracted {written} files to {root}")
        print("  workspace/  what the agent wrote     trace.txt  tools it called")
        print("  checks.txt  verification output      answer.md  its final reply")
    else:
        print("Re-run with --extract to write the produced code to results/runs/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
