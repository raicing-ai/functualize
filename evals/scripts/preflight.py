#!/usr/bin/env python3
"""Fail fast on a misconfigured eval run.

Every check here is free. Skipping them means discovering a missing API key
after promptfoo has already spun up workspaces, or a missing container image
after the first case has burned a minute of wall clock.

    npm run preflight
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "providers"))

from _harness import (  # noqa: E402
    CONTAINER_IMAGE,
    REPO_ROOT,
    child_env,
    credential_conflicts,
    resolve_sandbox_mode,
    select_credential,
)

OK, WARN, BAD = "ok  ", "warn", "FAIL"
findings: list[tuple[str, str]] = []


def check(level: str, message: str) -> None:
    findings.append((level, message))


def effective_modes() -> dict[str, str]:
    """Where each suite will actually run, after env-over-YAML precedence.

    Printed rather than inferred: "which of these is containerised" is the
    question this whole file exists to answer, and it has been wrong before.
    """
    return {
        "triggering (Skill-only probe)": resolve_sandbox_mode(None, "host"),
        "task suites (agent + shell)": resolve_sandbox_mode("docker", "docker"),
    }


def main() -> int:
    try:
        modes = effective_modes()
    except RuntimeError as exc:
        print(f"[{BAD}] {exc}")
        return 1

    want_docker = "docker" in modes.values()

    # --- where things will run ----------------------------------------------
    override = os.environ.get("FZ_EVAL_SANDBOX")
    for label, mode in modes.items():
        level = WARN if mode == "host" and "task" in label else OK
        check(level, f"{label}: {mode}")
    if override:
        check(OK, f"FZ_EVAL_SANDBOX={override} overrides every suite's `sandbox:` key")

    # --- credentials --------------------------------------------------------
    inherit = os.environ.get("FZ_EVAL_INHERIT_HOME") == "1"
    try:
        chosen = select_credential()
    except RuntimeError as exc:
        check(BAD, str(exc))
        chosen = None
    else:
        if chosen:
            value = os.environ[chosen]
            check(OK, f"credential: {chosen} ({value[:8]}…, {len(value)} chars)")
        elif inherit:
            check(WARN, "FZ_EVAL_INHERIT_HOME=1 — reusing your own ~/.claude login")
        else:
            check(
                BAD,
                "No credential — every agent call fails at the API.\n"
                "       Export ANTHROPIC_API_KEY, or `claude setup-token` then export\n"
                "       CLAUDE_CODE_OAUTH_TOKEN, or set FZ_EVAL_INHERIT_HOME=1 to reuse\n"
                "       your own login (host mode only). A logged-in `claude` does NOT\n"
                "       propagate on its own: the agent gets an isolated HOME.",
            )

        # `claude` prefers ANTHROPIC_API_KEY when several are set, so a stale
        # key in a shell profile silently beats a deliberate subscription
        # token. The harness forwards one; say which, and which it dropped.
        ignored = credential_conflicts()
        if ignored:
            check(
                WARN,
                f"also set but NOT forwarded: {', '.join(ignored)}\n"
                f"       The agent will authenticate as {chosen}. Override with\n"
                f"       FZ_EVAL_AUTH=api-key or FZ_EVAL_AUTH=oauth.",
            )

    # --- the agent itself ---------------------------------------------------
    if shutil.which("claude"):
        check(OK, "claude CLI on PATH (needed for sandbox: host)")
    elif want_docker:
        check(OK, "claude CLI not on host — fine, the image ships it")
    else:
        check(BAD, "sandbox: host requires the claude CLI on PATH")

    # --- container ----------------------------------------------------------
    if want_docker:
        engine = os.environ.get("FZ_EVAL_ENGINE") or next(
            (e for e in ("podman", "docker") if shutil.which(e)), None
        )
        if not engine:
            check(BAD, "sandbox: docker needs podman or docker on PATH")
        else:
            check(OK, f"container engine: {engine}")
            probe = subprocess.run(
                [engine, "image", "inspect", CONTAINER_IMAGE],
                capture_output=True,
                text=True,
            )
            if probe.returncode == 0:
                check(OK, f"image present: {CONTAINER_IMAGE}")
            else:
                check(BAD, f"image missing: {CONTAINER_IMAGE} — run `npm run image`")
    else:
        check(
            WARN,
            "Nothing is containerised. The task suites would run an agent with\n"
            "       bypassPermissions and Bash directly on this machine — read the\n"
            "       safety note in README.md before starting one.",
        )

    # --- source snapshot ----------------------------------------------------
    git = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
    )
    if git.returncode != 0:
        check(BAD, f"{REPO_ROOT} is not a git checkout; cannot build a source snapshot")
    else:
        dirty = (
            subprocess.run(
                ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
                capture_output=True,
                text=True,
            )
            .stdout.strip()
            .splitlines()
        )
        check(OK, f"source snapshot will include {len(dirty)} uncommitted change(s)")

    # --- what the agent will and will not see -------------------------------
    check(OK, f"env passed to the agent: {', '.join(sorted(child_env()))}")
    check(OK, "run `npm run doctor` to prove the credential actually works")

    for level, message in findings:
        print(f"[{level}] {message}")

    failures = sum(level == BAD for level, _ in findings)
    print()
    print("preflight failed" if failures else "preflight passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
