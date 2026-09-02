#!/usr/bin/env python3
"""Run ONE case, see what the agent did, edit the skill, run it again.

The suite scripts (`npm run task`) are the wrong tool for improving a skill:
they run 9 cases x 2 arms x 3 repeats, cost dollars, take half an hour, and
hand back a scoreboard. Skill work is a loop over a *single* scenario — read
the trace, find the question the agent could not answer from the skill, answer
it in the skill, run that one case again.

    npm run case                        # list every case, with its slug
    npm run case -- secret              # run the one whose slug matches
    npm run case -- secret --repeat 3   # ...three times, once it looks right
    npm run case -- secret --both       # ...and the baseline arm too
    npm run case -- secret --show       # ...printing the agent's full reply

Defaults are chosen for the loop, not for the verdict: one repeat, the
`with-skills` arm only, workspace kept on disk. That is ~1/6 the cost of the
same case under `npm run task`. Use `npm run task` + `npm run gate` when you
want the verdict.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "providers"))

from _harness import select_credential  # noqa: E402
from inspect_run import connect, evals, extract, load  # noqa: E402

EVALS = Path(__file__).resolve().parent.parent
SUITES = sorted(EVALS.glob("suites/*.yaml"))


def slug(description: str) -> str:
    """A short, stable, typeable handle for a case."""
    words = re.findall(r"[a-z0-9]+", description.lower())
    # Skip the leading verb where it carries no information: every case
    # description starts with one, so `resolves-`/`uses-`/`declines-` prefixes
    # would make the slugs collide on their first characters.
    return "-".join(words[:5])


class Case:
    def __init__(self, suite: Path, index: int, test: dict, body: dict) -> None:
        self.suite, self.index, self.test, self.body = suite, index, test, body
        self.description = (test.get("description") or "").strip()
        self.vars = test.get("vars") or {}
        # Routing cases carry no description — their identity is the query, so
        # slug from that instead of numbering them `case-7` and making the
        # listing useless.
        self.slug = slug(self.description or self.query) or f"case-{index}"

    @property
    def query(self) -> str:
        for key in ("query", "task"):
            if self.vars.get(key):
                return " ".join(str(self.vars[key]).split())
        return ""

    @property
    def title(self) -> str:
        return self.description or self.query[:90]

    def filter_argv(self) -> list[str]:
        """How to tell promptfoo to run only this case.

        `--filter-pattern` matches the description, which a routing case does
        not have; index is the only handle there. Anchored either way, so a
        fragment that also appears in a sibling case cannot widen the run.
        """
        if self.description:
            return ["--filter-pattern", f"^{re.escape(self.description)}$"]
        return ["--filter-range", f"{self.index}:{self.index + 1}"]

    @property
    def suite_name(self) -> str:
        return self.suite.stem

    @property
    def arms(self) -> list[str]:
        """Provider labels this suite defines.

        The routing suite has one arm called `router`, not the `with-skills` /
        `baseline` pair — so the default arm filter has to be checked against
        the suite rather than assumed, or it filters every test out and
        promptfoo reports a cheerful zero-case success.
        """
        labels = []
        for provider in self.body.get("providers") or []:
            if isinstance(provider, dict) and provider.get("label"):
                labels.append(provider["label"])
        return labels

    def asserts(self) -> list[str]:
        """One line per assertion — the contract this case is graded on.

        Includes `defaultTest.assert`: the routing suite grades every case
        from there and nowhere else, so a per-test-only read shows an empty
        contract for the entire suite.
        """
        lines = []
        inherited = (self.body.get("defaultTest") or {}).get("assert") or []
        for item in [*inherited, *(self.test.get("assert") or [])]:
            kind = item.get("type", "?")
            if kind == "python":
                name = Path(str(item.get("value", ""))).name
                config = item.get("config") or {}
                labels = [
                    f"{group_name}: {entry.get('label', entry.get('pattern', ''))}"
                    for group_name, group in config.items()
                    if isinstance(group, list)
                    for entry in group
                    if isinstance(entry, dict)
                ]
                detail = "; ".join(labels) or ", ".join(
                    f"{k}={v}" for k, v in config.items() if not isinstance(v, list)
                )
                lines.append(f"{name}  {detail}".strip())
            else:
                lines.append(
                    f"{kind}  {' '.join(str(item.get('value', '')).split())[:90]}"
                )
        return lines


def discover() -> list[Case]:
    found = []
    for suite in SUITES:
        try:
            body = yaml.safe_load(suite.read_text()) or {}
        except yaml.YAMLError as exc:
            print(f"warn: cannot parse {suite.name}: {exc}", file=sys.stderr)
            continue
        for index, test in enumerate(body.get("tests") or []):
            if isinstance(test, dict):
                found.append(Case(suite, index, test, body))
    return found


def show_listing(cases: list[Case]) -> None:
    by_suite: dict[str, list[Case]] = {}
    for case in cases:
        by_suite.setdefault(case.suite_name, []).append(case)
    for suite_name, group in by_suite.items():
        print(f"\n{suite_name}")
        for case in group:
            fixture = case.vars.get("fixture") or "-"
            print(f"  {case.slug:<44} [{fixture}]")
            print(f"  {'':<44} {case.title}")
    print("\nRun one:  npm run case -- <slug fragment>")


def resolve(cases: list[Case], query: str) -> Case:
    pattern = re.compile(query, re.IGNORECASE)
    hits = [c for c in cases if pattern.search(c.slug) or pattern.search(c.title)]
    if not hits:
        raise SystemExit(f"No case matches {query!r}. `npm run case` lists them.")
    if len(hits) > 1:
        # Ambiguity must not silently pick one: the whole point is that you
        # know which single case you are iterating on.
        exact = [c for c in hits if c.slug == query]
        if len(exact) == 1:
            return exact[0]
        print(f"{query!r} matches {len(hits)} cases — narrow it:")
        for case in hits:
            print(f"  {case.slug:<44} {case.suite_name}")
        raise SystemExit(2)
    return hits[0]


def promptfoo() -> str:
    local = EVALS / "node_modules" / ".bin" / "promptfoo"
    return str(local) if local.exists() else "promptfoo"


def report(started_at: float, case: Case, show_answer: bool) -> int:
    """Read back what just happened, from the DB, in one screen."""
    conn = connect()
    available = evals(conn)
    if not available or available[0]["created_at"] / 1000.0 < started_at - 5:
        print("\nNo eval was recorded — promptfoo failed before storing results.")
        return 1
    eval_id = available[0]["id"]
    runs = load(conn, eval_id)
    if not runs:
        print(f"\nNo results stored for {eval_id}.")
        return 1

    print(f"\n{'─' * 72}\n{eval_id}   {case.slug}\n")
    failed = 0
    for run in runs:
        out = run["output"]
        mark = "PASS" if run["success"] else "FAIL"
        failed += not run["success"]
        print(
            f"{mark}  {run['provider']}  ${run['cost']:.3f}  "
            f"{out.get('num_turns', '?')} turns"
        )

        for reason in dict.fromkeys(run["reasons"]):
            print(f"      why: {' '.join(reason.split())[:150]}")
        if run["errored"]:
            print(f"      harness error: {' '.join(str(run['error']).split())[:150]}")

        print(f"      skills: {out.get('skills_loaded') or 'NONE LOADED'}")
        for command in out.get("bash_commands") or []:
            print(f"      $ {' '.join(command.split())[:96]}")
        for check in out.get("checks") or []:
            flag = "ok" if check["exit_code"] == 0 else f"exit {check['exit_code']}"
            print(f"      [{flag}] {check['command'][:80]}")
        if out.get("workspace"):
            print(f"      workspace: {out['workspace']}")
        if show_answer and out.get("text"):
            print(
                "\n"
                + "\n".join(f"      | {line}" for line in out["text"].splitlines())
                + "\n"
            )
        print()

    root = extract(runs, eval_id)
    print(f"trace + files: {root}")
    print("Read the trace, fix the skill, run this same command again.")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(usage="npm run case -- [slug] [options]")
    parser.add_argument("query", nargs="?", help="slug fragment or regex")
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="repeats (default 1 — raise it once the case looks fixed)",
    )
    parser.add_argument(
        "--both",
        action="store_true",
        help="run the baseline arm too (default: with-skills only)",
    )
    parser.add_argument("--arm", default="", help="run exactly this provider label")
    parser.add_argument("--model", default="", help="override the pinned model")
    parser.add_argument(
        "--host",
        action="store_true",
        help="FZ_EVAL_SANDBOX=host — debug the harness, not the skill",
    )
    parser.add_argument(
        "--show", action="store_true", help="print the agent's full reply"
    )
    parser.add_argument("--dry-run", action="store_true", help="print the command only")
    args = parser.parse_args()

    cases = discover()
    if not args.query:
        show_listing(cases)
        return 0

    case = resolve(cases, args.query)
    arm = args.arm or ("" if args.both else "with-skills")
    if arm and arm not in case.arms:
        # Filtering on a label the suite does not define leaves zero tests, and
        # promptfoo exits 0 on zero tests — a silent no-op that reads as a pass.
        print(
            f"note     {case.suite_name} has no {arm!r} arm "
            f"({', '.join(case.arms) or 'no labelled providers'}) — running all of them"
        )
        arm = ""

    print(f"suite    {case.suite.relative_to(EVALS)}")
    print(f"case     {case.slug}")
    print(f"          {case.title}")
    print(f"fixture  {case.vars.get('fixture') or '-'}")
    print(f"arm      {arm or 'both'}   repeat {args.repeat}")
    print("graded on")
    for line in case.asserts():
        print(f"  · {line}")
    for command in case.vars.get("checks") or []:
        print(f"  · must run: {command}")
    print()

    argv = [
        promptfoo(),
        "eval",
        "-c",
        str(case.suite),
        "--no-cache",
        "--repeat",
        str(args.repeat),
        *case.filter_argv(),
    ]
    if arm:
        argv += ["--filter-providers", f"^{re.escape(arm)}$"]

    env = dict(os.environ)
    # Keep the workspace: half of iterating is going in and re-running a check
    # by hand against the .venv the agent actually built.
    env.setdefault("FZ_EVAL_KEEP", "all")
    if args.model:
        env["FZ_EVAL_MODEL"] = args.model
    if args.host:
        env["FZ_EVAL_SANDBOX"] = "host"

    if args.dry_run:
        print(" ".join(argv))
        return 0

    # A missing credential does not error the run — the agent starts, `claude`
    # replies "Please run /login", and the case reports as a FAILING SKILL.
    # One line here is cheaper than debugging a skill that was never consulted.
    if not select_credential() and not os.environ.get("FZ_EVAL_INHERIT_HOME"):
        raise SystemExit(
            "No credential in this shell, so the agent would fail to log in and\n"
            "the case would report as a failing skill. Export one of\n"
            "  CLAUDE_CODE_OAUTH_TOKEN   (subscription — `claude setup-token`)\n"
            "  ANTHROPIC_API_KEY         (API billing)\n"
            "then re-run. `npm run doctor` proves it authenticates."
        )

    started_at = time.time()
    # promptfoo's own exit code is "did every assertion pass", which for one
    # case is exactly what we want to know — but the report is the point, so
    # run it either way.
    subprocess.run(argv, cwd=EVALS, env=env)
    return report(started_at, case, args.show)


if __name__ == "__main__":
    raise SystemExit(main())
