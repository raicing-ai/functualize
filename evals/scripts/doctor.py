#!/usr/bin/env python3
"""Prove the credential works and the agent can actually run — end to end.

`preflight` checks that a key is *set*. This checks that it *works*, by making
one real (tiny) call through the exact code path the suites use: same env
allowlist, same sandbox wrapper, same streaming parser. If this passes, a
timeout in a real run is a slow agent; if it fails, the message says why.

Costs a fraction of a cent.

Three things fail independently here, so each is probed separately:

  * the sandbox (can it run a command at all)
  * the agent path (can `claude -p` reach the API)
  * the grading path (can `llm-rubric` assertions authenticate)

The last one matters because `llm-rubric` defaults to gpt-5 over the OpenAI
API, so every rubric can be broken while the agent runs perfectly — which
reports as failing skills rather than as a configuration problem.

    npm run doctor                   # both sandbox modes + the grader
    npm run doctor -- host           # one mode
    npm run doctor -- --no-grader    # skip the grading probe
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "providers"))

import claude_grader  # noqa: E402  — the grading path, checked separately
from _harness import (  # noqa: E402
    CONTAINER_IMAGE,
    build_workspace,
    child_env,
    container_engine,
    credential_conflicts,
    has_credential,
    run_check,
    run_claude,
    select_credential,
)

PROMPT = "Reply with exactly the word FUNCTUALIZE-OK and nothing else."
EXPECTED = "FUNCTUALIZE-OK"


def probe(mode: str) -> bool:
    print(f"\n─── {mode} " + "─" * (58 - len(mode)))

    if mode == "docker":
        try:
            engine = container_engine()
        except RuntimeError as exc:
            print(f"  SKIP  {exc}")
            return True
        inspect = subprocess.run(
            [engine, "image", "inspect", CONTAINER_IMAGE], capture_output=True
        )
        if inspect.returncode != 0:
            print(f"  FAIL  image {CONTAINER_IMAGE} missing — run `npm run image`")
            return False

    workspace, sandbox = build_workspace(None, with_skills=False, mode=mode)
    try:
        # 1. Can the sandbox run anything at all?
        probe_check = run_check(sandbox, "echo shell-ok", timeout_s=120)
        if probe_check["exit_code"] != 0:
            print(f"  FAIL  sandbox cannot run a shell: {probe_check['stderr'][:200]}")
            return False
        print("  ok    sandbox runs commands")

        # 2. Is the claude binary reachable *inside* the sandbox?
        version = run_check(sandbox, "claude --version", timeout_s=120)
        if version["exit_code"] != 0:
            where = "the image" if mode == "docker" else "PATH"
            print(f"  FAIL  claude not found on {where}: {version['stderr'][:200]}")
            return False
        print(f"  ok    claude present: {version['stdout'].strip()[:40]}")

        # 3. The real thing: one tiny round trip to the API.
        print("  ...   calling the API (a few seconds)")
        run = run_claude(sandbox, PROMPT, max_turns=2, allowed_tools=[], timeout_s=120)

        if run.error:
            print(f"  FAIL  {run.error[:400]}")
            _explain(run.error)
            return False
        if EXPECTED not in (run.text or ""):
            print(f"  WARN  API answered but unexpectedly: {(run.text or '')[:120]!r}")
            return True
        print(f"  ok    API round trip: {run.text.strip()[:40]} (${run.cost_usd:.4f})")
        return True
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
        if sandbox.agent_home:
            shutil.rmtree(sandbox.agent_home, ignore_errors=True)


def _explain(error: str) -> None:
    lowered = error.lower()
    if "401" in lowered or "authentication" in lowered:
        print(
            "        The credential reached the API and was refused. Either the\n"
            "        key is wrong/expired, or it belongs to an account without\n"
            "        API access — a Claude subscription login is NOT an API key.\n"
            "        For a subscription: `claude setup-token`, then export\n"
            "        CLAUDE_CODE_OAUTH_TOKEN. Or set FZ_EVAL_INHERIT_HOME=1 to\n"
            "        reuse your existing login (host mode only)."
        )
    elif "403" in lowered:
        print("        Authenticated, but this key is not permitted to use the model.")
    elif "credit" in lowered or "quota" in lowered or "429" in lowered:
        print("        The key works but the account is out of credit or rate limited.")
    elif "timeout" in lowered:
        print(
            "        No response and no API error — so the request never left.\n"
            "        Check network/proxy reachability to api.anthropic.com, and\n"
            "        ANTHROPIC_BASE_URL if you set one."
        )


def probe_grader() -> bool:
    """Grade one trivial rubric for real.

    A separate arm because it is a separate failure: `llm-rubric` defaults to
    gpt-5 over the OpenAI API, so the graders can be completely broken while
    every agent call succeeds. That is not hypothetical — it reported as three
    failing skills that were in fact routing correctly.
    """
    print("\n─── grader " + "─" * 52)

    rubric = (
        "You are grading a response against a rubric.\n\n"
        "Rubric: the response mentions the colour blue.\n"
        'Response: "The sky is blue today."\n\n'
        "Does the response satisfy the rubric?"
    )
    try:
        result = claude_grader.call_api(rubric, {"config": {"timeout_s": 120}}, {})
    except Exception as exc:  # noqa: BLE001 - a doctor must not itself crash
        print(f"  FAIL  grader raised: {exc}")
        return False

    if result.get("error"):
        print(f"  FAIL  {result['error'][:300]}")
        _explain(result["error"])
        return False

    verdict = json.loads(result["output"])
    reason = verdict.get("reason", "")

    # A grader that cannot produce the JSON contract fails *every* rubric, so
    # this is broken rather than merely surprising.
    if reason.startswith("grader returned no JSON") or reason.startswith("grader JSON"):
        print(f"  FAIL  {reason[:150]}")
        print("        The grading model is not following the JSON contract, so")
        print("        every llm-rubric assertion would fail. Try a larger model")
        print("        via FZ_EVAL_GRADER_MODEL.")
        return False

    if not verdict["pass"]:
        # The rubric is trivially satisfiable, so a genuine "fail" verdict means
        # the grader is not reading the prompt properly.
        print(f"  WARN  grader failed a rubric it should pass: {reason[:110]}")
        print("        Verdicts may be unreliable; consider FZ_EVAL_GRADER_MODEL.")
        return True

    print(f"  ok    grader verdict: pass — {verdict['reason'][:60]}")
    print("  ok    llm-rubric assertions will authenticate")
    return True


def main() -> int:
    modes = [a for a in sys.argv[1:] if not a.startswith("-")] or ["host", "docker"]

    try:
        chosen = select_credential()
    except RuntimeError as exc:
        print(f"FAIL  {exc}")
        return 1

    env = child_env()
    print(f"credential         : {chosen or '(none)'}")
    ignored = credential_conflicts()
    if ignored:
        print(
            f"  ignored          : {', '.join(ignored)}  (override with FZ_EVAL_AUTH)"
        )
    print(f"HOME for the agent : {env.get('HOME')}")
    print(f"env passed         : {', '.join(sorted(env))}")

    if not has_credential():
        print(
            "\nFAIL  No credential. Export ANTHROPIC_API_KEY, or run\n"
            "      `claude setup-token` and export CLAUDE_CODE_OAUTH_TOKEN, or\n"
            "      set FZ_EVAL_INHERIT_HOME=1 to reuse your existing login."
        )
        return 1

    results = {mode: probe(mode) for mode in modes}

    # The grading path is checked whenever the agent path was, because the two
    # fail independently and only one of them is obvious from a suite run.
    if "--no-grader" not in sys.argv:
        results["grader"] = probe_grader()

    print("\n" + "─" * 64)
    for name, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
