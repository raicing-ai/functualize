#!/usr/bin/env python3
"""Decide whether a run passes — by failure *shape*, not by a percentage.

An aggregate pass rate is the wrong gate for a non-deterministic suite, and
this repo has already produced the proof: 60/63 is 95.2%, which clears the
threshold everyone reaches for first, while hiding one case that failed all
three repeats. A case at 0/k is a reproducible defect. A case at 1/k..k-1/k is
the model being a model.

promptfoo cannot express that distinction. `PROMPTFOO_PASS_RATE_THRESHOLD` is
global across the suite, so a case can fail every repeat and still exit 0 if
the others carry the average (promptfoo#5847). Hence this.

Three gates, in the order they matter:

  1. harness errors    — never a result at all; always blocking
  2. hard failures     — any case at 0/k; always blocking
  3. the aggregate     — a floor, as a backstop only

Flaky cases (1..k-1) are reported and do not block. With k=3 the 95% CI on a
2/3 case runs roughly [0.09, 0.99]: it is not distinguishable from a 3/3, and
gating on it trains everyone to ignore the gate.

    npm run gate                      # the latest run
    npm run gate -- --floor 95        # stricter aggregate backstop
    npm run gate -- --arm with-skills # ignore the baseline ablation arm
    npm run gate -- --eval <id>
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from inspect_run import connect, evals, label, load  # noqa: E402

DEFAULT_FLOOR = float(os.environ.get("FZ_EVAL_FLOOR", "90"))


def group(cases: list[dict]) -> dict[tuple, list[dict]]:
    """Same identity rule as the inspector: repeats are one case, not k cases."""
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for case in cases:
        variables = case["vars"]
        identity = (
            variables.get("query") or variables.get("task") or case["description"]
        )
        grouped[(str(identity)[:120], case["provider"])].append(case)
    return grouped


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval", dest="eval_id")
    parser.add_argument(
        "--floor",
        type=float,
        default=DEFAULT_FLOOR,
        help="aggregate pass-rate backstop, percent",
    )
    parser.add_argument(
        "--arm", default="", help="only gate this provider label (e.g. with-skills)"
    )
    parser.add_argument(
        "--exclude-arm",
        default="baseline",
        metavar="LABEL",
        help="drop this provider label before gating (default: "
        "baseline — the ablation arm is *designed* to fail, "
        "so gating on it would fail every run). Pass '' to "
        "gate every arm.",
    )
    parser.add_argument(
        "--max-age",
        type=float,
        default=0.0,
        metavar="MINUTES",
        help="fail if the latest run is older than this — guards "
        "CI against grading a stale run when the eval itself "
        "crashed (0 disables, the default)",
    )
    args = parser.parse_args()

    conn = connect()
    available = evals(conn)
    if not available:
        raise SystemExit("No eval runs recorded yet.")
    eval_id = args.eval_id or available[0]["id"]

    # promptfoo writes nothing when it dies early, so without this the gate
    # would happily re-grade yesterday's green run and call the pipeline good.
    if args.max_age and not args.eval_id:
        # created_at is epoch milliseconds.
        age_min = (time.time() - available[0]["created_at"] / 1000.0) / 60.0
        if age_min > args.max_age:
            print(
                f"FAIL  latest run {eval_id} is {age_min:.0f} min old "
                f"(limit {args.max_age:.0f}) — did the eval actually run?"
            )
            return 1

    cases = load(conn, eval_id)
    if args.arm:
        cases = [c for c in cases if c["provider"] == args.arm]
    dropped = 0
    if args.exclude_arm:
        keep = [c for c in cases if c["provider"] != args.exclude_arm]
        dropped, cases = len(cases) - len(keep), keep
    if not cases:
        raise SystemExit(
            f"No results stored for {eval_id}"
            + (f" (arm {args.arm!r})" if args.arm else "")
        )

    grouped = group(cases)
    hard, flaky, errored = [], [], []
    for (_identity, provider), runs in sorted(grouped.items()):
        ok = sum(r["success"] for r in runs)
        name = f"{provider}  {label(runs[0])}"
        # `error` is set for assertion failures too, so it cannot be the
        # discriminator — promptfoo's failure_reason can (see inspect_run).
        if any(r["errored"] for r in runs):
            errored.append((name, next(str(r["error"]) for r in runs if r["errored"])))
        if ok == 0:
            hard.append((name, len(runs), runs))
        elif ok < len(runs):
            flaky.append((name, ok, len(runs)))

    passed = sum(c["success"] for c in cases)
    rate = 100.0 * passed / len(cases)

    print(f"gate: {eval_id}\n")
    print(f"  {len(grouped)} cases · {len(cases)} runs · {passed} passed")
    if dropped:
        print(f"  ({dropped} {args.exclude_arm!r} runs excluded — ablation arm)")
    print()

    # 1. Harness errors. Not a verdict on the skill at all — the run did not
    #    happen. Counting these toward a pass rate launders a broken setup into
    #    a quality number.
    if errored:
        print(f"  FAIL  {len(errored)} case(s) errored — the run did not happen")
        for name, err in errored:
            print(f"        ✖ {name}")
            print(f"          {' '.join(err.split())[:96]}")
        print("        Run `npm run doctor` — this is credentials, sandbox or timeout,")
        print("        not skill quality.")
    else:
        print("  ok    no harness errors")

    # 2. The gate promptfoo does not give you.
    if hard:
        print(
            f"\n  FAIL  {len(hard)} case(s) failed every repeat — reproducible, not noise"
        )
        for name, k, runs in hard:
            print(f"        ✖ [0/{k}] {name}")
            for reason in dict.fromkeys(r for run in runs for r in run["reasons"]):
                print(f"          → {' '.join(reason.split())[:94]}")
    else:
        print("  ok    no case failed every repeat")

    if flaky:
        print(f"\n  warn  {len(flaky)} flaky case(s) — reported, not blocking")
        for name, ok, k in flaky:
            print(f"        ~ [{ok}/{k}] {name}")

    # 3. Backstop. Catches broad erosion that no single case makes obvious.
    floor_ok = rate >= args.floor
    print(
        f"\n  {'ok  ' if floor_ok else 'FAIL'}  pass rate {rate:.1f}% "
        f"{'≥' if floor_ok else '<'} {args.floor:.1f}% floor"
    )

    ok = not errored and not hard and floor_ok
    print("\n" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
