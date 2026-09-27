#!/usr/bin/env python3
"""Refuse a contract-bearing diff whose branch carried no task graph.

`.claude/rules/spec-workflow.md` § *What is mechanically enforced* states the
rule this reports: modifying `src/functualize/**` or `plugins/**/src/**` requires
a `.spec/features/*/tasks.md` carrying a parseable `## Task Dependency Graph`.
Until now the only thing that enforced it was `.claude/hooks/spec_gate.py`, a
`PreToolUse` hook — a project setting of one harness. A hook is a property of the
editor, not of the change: it fires for no other harness, and it fires for none
of the shell, which the same rule excludes from the gate in writing. What the
hook cannot see, nothing else looked at, and a branch that changed three
`src/functualize/**` modules and the documented CLI contract reached `master`
with no task graph and nothing that failed.

This is the same rule at the pull request, where it cannot be outrun by how the
edit was made. It is a check, not a second contract:

* `is_gated` and `has_wave_graph` are imported from the hook rather than
  restated here. Two definitions of one contract is how a gate and the check
  beside it drift, and drift in this one fails open — the direction that
  produced it.
* `spec-artifacts-cleared` is untouched: it refuses a tree that still *keeps*
  `.spec/features/**` at merge. This refuses a branch whose contract-bearing
  change never *had* one. They are the two directions of one file, and both stay
  ungated by `spec-only-change`, because the change this job is about is exactly
  the change that job is not looking at.

The task graph may have arrived and been cleared again — the two-push sequence
deletes it in the branch's last commit — so the branch tip alone is not the
question. A graph added anywhere in the range counts, and a graph still at the
tip counts. Nothing else does:

* a `.spec/features/<name>/` directory whose `tasks.md` carries no parseable
  graph is not a graph, exactly as at write time;
* a directory that exists but belongs to another feature is *not* refused. The
  hook surveys any feature directory, so refusing a sibling's would make this
  check stricter than the gate it reports, and stricter is not the same as
  correct.

There is no exemption, and this does not add one. The write-time gate's
`.spec/EXEMPT` token and its `Spec-exempt:` line were removed on 2026-09-16: the
token was honoured for one hour by file mtime and was never merge-time state, so
it could not have covered a branch either. A change genuinely too small to
specify is a member decision that arrives in the repository as a
`.spec/features/**` artifact, not as a token a diff can mint for itself. Note
that a mechanical version bump inside `src/functualize/__init__.py` *is* a
contract-bearing change under this path rule: it rides a pull request whose range
carries the graph, like every other shipped-code change.

Inputs, all from the environment so the workflow owns the git invocation:

``SPEC_TASK_GRAPH_BASE``  the pull request's base sha
``SPEC_TASK_GRAPH_HEAD``  the pull request's head sha
``SPEC_TASK_GRAPH_PR``    the pull request number, to reach a fork's head
``SPEC_TASK_GRAPH_ROOT``  the checkout to inspect (default: the working
                          directory)

Every unresolved, unreadable or unparseable input is a failure with its reason
printed. This job exists because the alternative was silence, so a check that
cannot decide refuses rather than passes.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

#: The write-time gate whose contract this reports. Loaded by path, never
#: imported from the package, for the reason the hook itself records: it runs
#: outside the project venv, in clean clones.
GATE = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "spec_gate.py"

#: What a contract-bearing diff must carry. Named once, because a failure
#: message that does not name the missing artifact is a failure message that
#: sends its reader looking.
REQUIRED = "`.spec/features/*/tasks.md` with a parseable `## Task Dependency Graph`"

#: A branch that changes four hundred gated files is not made clearer by
#: printing four hundred paths, and Actions truncates around that size anyway.
MAX_LISTED_PATHS = 20

_SHA_LENGTH = 40
_HEX = frozenset("0123456789abcdef")


class UnusableError(Exception):
    """The check cannot decide. That is a failure, not a pass."""


def _git(root: str | Path, *args: str) -> tuple[int, str]:
    """Run git in `root` and return (returncode, stdout)."""
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout


def _load_gate() -> object:
    """Import the write-time gate without running it.

    `spec_gate.py` is a `PreToolUse` hook: its `main()` reads a harness payload
    off stdin, and its `if __name__ == "__main__"` guard is what keeps importing
    it harmless. Registered in `sys.modules` before execution because a module
    whose classes resolve `sys.modules[cls.__module__]` finds `None` there
    otherwise, and the error surfaces nowhere near the cause.
    """
    spec = importlib.util.spec_from_file_location("_fz_spec_gate_for_task_graph", GATE)
    if spec is None or spec.loader is None:
        raise UnusableError(f"could not load the write-time gate at {GATE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as error:  # noqa: BLE001 - any failure is fail-closed
        del sys.modules[spec.name]
        raise UnusableError(
            f"could not load the write-time gate at {GATE} ({type(error).__name__})"
        ) from error
    return module


def _resolve(root: Path, rev: str, pull_request: str) -> str | None:
    """Return `rev` if this checkout holds it, else reach for a fork's head."""
    if _git(root, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")[0] == 0:
        return rev
    if pull_request:
        # A fork's head commit is not a branch in this repository; it lives in
        # `refs/pull/<N>/head`, which `fetch-depth: 0` does not reach.
        _git(
            root,
            "fetch",
            "--no-tags",
            "origin",
            f"+refs/pull/{pull_request}/head:refs/remotes/pr/{pull_request}",
        )
        if _git(root, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")[0] == 0:
            return rev
    return None


def _merge_base(root: Path, base: str, head: str) -> str:
    """The commit the branch's own diff is measured from.

    Not the base tip. A branch cut from an older `master` differs from the tip
    by every file `master` has moved since, in reverse — so diffing the two tips
    would report an unrelated `src/functualize/**` change as this branch's and
    refuse a pull request that touched no contract-bearing path at all. The
    merge base is the branch's own range, and it is what a reviewer's "Files
    changed" tab shows.
    """
    code, out = _git(root, "merge-base", base, head)
    merge_base = out.strip().splitlines()[0] if out.strip() else ""
    if code != 0 or not merge_base:
        raise UnusableError(f"could not find a merge base for {base} and {head}")
    return merge_base


def _changed_paths(root: Path, merge_base: str, head: str) -> list[str]:
    code, out = _git(root, "diff", "--name-only", merge_base, head)
    if code != 0:
        raise UnusableError(f"could not diff {merge_base}..{head}")
    return [line for line in out.splitlines() if line.strip()]


def _graphs_added_in_range(root: Path, merge_base: str, head: str) -> list[str]:
    """The `.spec/features/**/tasks.md` blobs the range added, as `sha:path`."""
    code, out = _git(
        root,
        "log",
        "--format=%H",
        "--diff-filter=A",
        "--name-only",
        f"{merge_base}..{head}",
        "--",
        ".spec/features",
    )
    if code != 0:
        raise UnusableError(f"could not walk {merge_base}..{head} for .spec/features")
    found: list[str] = []
    commit = ""
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        if len(line) == _SHA_LENGTH and set(line) <= _HEX:
            commit = line
        elif (
            commit and line.startswith(".spec/features/") and line.endswith("tasks.md")
        ):
            found.append(f"{commit}:{line}")
    return found


def _carried_by_the_range(root: Path, gate: object, blobs: list[str]) -> str | None:
    for blob in blobs:
        code, text = _git(root, "show", blob)
        if code == 0 and gate.has_wave_graph(text):  # type: ignore[attr-defined]
            return blob.split(":", 1)[1]
    return None


def main() -> int:
    base = os.environ.get("SPEC_TASK_GRAPH_BASE", "").strip()
    head = os.environ.get("SPEC_TASK_GRAPH_HEAD", "").strip()
    pull_request = os.environ.get("SPEC_TASK_GRAPH_PR", "").strip()
    root = Path(os.environ.get("SPEC_TASK_GRAPH_ROOT") or os.getcwd()).resolve()

    if not base or not head:
        print(
            "::error::SPEC_TASK_GRAPH_BASE and SPEC_TASK_GRAPH_HEAD must both name "
            "the pull request's base and head commit; nothing was checked. "
            "Refusing the pull request rather than passing it."
        )
        return 1

    try:
        gate = _load_gate()
        resolved_base = _resolve(root, base, pull_request)
        resolved_head = _resolve(root, head, pull_request)
        if resolved_base is None or resolved_head is None:
            raise UnusableError(
                f"could not resolve {base} and {head} in {root} "
                f"(a fork's head needs SPEC_TASK_GRAPH_PR; it was "
                f"{pull_request or 'unset'})"
            )
        merge_base = _merge_base(root, resolved_base, resolved_head)
        changed = _changed_paths(root, merge_base, resolved_head)
        gated = [path for path in changed if gate.is_gated(path, str(root))]  # type: ignore[attr-defined]
    except UnusableError as error:
        print(
            f"::error::{error}; nothing was checked. Refusing the pull request "
            "rather than passing it."
        )
        return 1

    span = f"{merge_base[:12]}..{resolved_head[:12]}"
    if not gated:
        print(
            f"OK: no contract-bearing path changed in {span} "
            f"({len(changed)} file(s) changed, none under src/functualize/ or "
            "plugins/**/src/)."
        )
        return 0

    try:
        _, _, graph_at_tip = gate.survey_features(str(root))  # type: ignore[attr-defined]
        blobs = _graphs_added_in_range(root, merge_base, resolved_head)
        carried = None if graph_at_tip else _carried_by_the_range(root, gate, blobs)
    except UnusableError as error:
        print(
            f"::error::{error}; nothing was checked. Refusing the pull request "
            "rather than passing it."
        )
        return 1

    if graph_at_tip:
        print(
            f"OK: the branch tip carries {REQUIRED} for {len(gated)} "
            "contract-bearing path(s)."
        )
        return 0

    if carried:
        print(
            f"OK: {carried} carries the task graph for {len(gated)} "
            "contract-bearing path(s), and was cleared before merge as the "
            "two-push sequence requires."
        )
        return 0

    listed = "\n".join(f"  {path}" for path in gated[:MAX_LISTED_PATHS])
    omitted = len(gated) - MAX_LISTED_PATHS
    if omitted > 0:
        listed += f"\n  … and {omitted} more"
    print(
        f"::error::This branch changes contract-bearing code and carries no "
        f"{REQUIRED}. There is no exemption. Refusing the pull request. "
        "Recover by running /agentic-specify then /agentic-plan, and let "
        ".spec/features/<name>/ travel with this branch: it is cleared in the "
        "branch's last commit, before merge."
    )
    print(f"  range: {span} (base {resolved_base[:12]}, head {resolved_head[:12]})")
    print(f"  contract-bearing path(s) changed ({len(gated)}):")
    print(listed)
    print(
        f"  {REQUIRED} added anywhere in the range: "
        f"{'no' if not blobs else ', '.join(blobs)}"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
