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
question. A graph held by any commit of the range counts, the head commit
included. Nothing else does:

* every answer is read from the range's commit objects, never from the
  checkout. An untracked, staged or locally edited `tasks.md` is not part of the
  change a reviewer merges, and a checkout that differs from the head commit —
  a local run, or CI's merge commit — must not decide what the range carried.
  The gated-path test is lexical for the same reason: it is asked of the
  committed path against an empty directory, so no symlink in the checkout can
  move a changed path out of `src/functualize/`;
* only `.spec/features/<name>/tasks.md` is the artifact — the one file per
  feature directory the hook's `survey_features` reads, not any file under
  `.spec/features/` whose name ends in `tasks.md`;
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
``SPEC_TASK_GRAPH_ROOT``  the repository whose objects are read (default:
                          the working directory); its worktree is never read

Every unresolved, unreadable or unparseable input is a failure with its reason
printed. This job exists because the alternative was silence, so a check that
cannot decide refuses rather than passes.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
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
    """Run git in `root` and return (returncode, stdout).

    A git that cannot be started at all — not on `PATH`, not executable — is
    the same answer as a git that failed: nothing was checked. Left uncaught it
    is a traceback, which fails closed but says nothing about why.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        raise UnusableError(
            f"could not run git ({type(error).__name__}: {error})"
        ) from error
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


def _gated(gate: object, changed: list[str]) -> list[str]:
    """The changed paths the hook's `is_gated` calls shipped code.

    Asked against an empty directory, not the checkout. `is_gated` resolves
    real paths so that a symlink planted in a *worktree* cannot walk a write out
    of the gated tree; here the paths come from commits, where git records a
    symlink as a blob and never a path through one, so the lexical answer is the
    exact one. Resolving them against the checkout would instead let whatever
    the checkout holds — a local symlink, a stale tree — move a committed
    `src/functualize/**` path out of the gate, and the check would pass.
    """
    with tempfile.TemporaryDirectory(prefix="spec-task-graph-") as nowhere:
        return [path for path in changed if gate.is_gated(path, nowhere)]  # type: ignore[attr-defined]


def _is_feature_tasks(path: str) -> bool:
    """`.spec/features/<name>/tasks.md` — the one file `survey_features` reads."""
    parts = path.split("/")
    return (
        len(parts) == 4
        and parts[:2] == [".spec", "features"]
        and parts[3] == "tasks.md"
    )


def _tasks_in_range(
    root: Path, merge_base: str, head: str
) -> list[tuple[str, str, str]]:
    """Every feature `tasks.md` a commit of the range holds, newest commit first.

    Returned as `(commit, path, blob)`. Read from each commit's tree, so the
    head commit's own graph, a graph added and cleared again, a graph that only
    became parseable in a later edit, and one that arrived through a merge are
    all seen — and nothing outside the commits is.
    """
    code, out = _git(root, "rev-list", f"{merge_base}..{head}")
    if code != 0:
        raise UnusableError(f"could not list the commits of {merge_base}..{head}")
    commits = [
        line for line in out.split() if len(line) == _SHA_LENGTH and set(line) <= _HEX
    ]
    if not commits:
        raise UnusableError(f"{merge_base}..{head} holds no commit")
    found: list[tuple[str, str, str]] = []
    for commit in commits:
        code, listing = _git(
            root, "ls-tree", "-r", "-z", commit, "--", ".spec/features"
        )
        if code != 0:
            raise UnusableError(f"could not read the tree of {commit}")
        for entry in listing.split("\0"):
            meta, _, path = entry.partition("\t")
            fields = meta.split()
            if len(fields) == 3 and fields[1] == "blob" and _is_feature_tasks(path):
                found.append((commit, path, fields[2]))
    return found


def _carried_by_the_range(
    root: Path, gate: object, tasks: list[tuple[str, str, str]]
) -> tuple[str, str] | None:
    """The first `(commit, path)` whose `tasks.md` carries a parseable graph."""
    verdicts: dict[str, bool] = {}
    for commit, path, blob in tasks:
        if blob not in verdicts:
            code, text = _git(root, "cat-file", "blob", blob)
            if code != 0:
                raise UnusableError(f"could not read {path} at {commit}")
            verdicts[blob] = bool(gate.has_wave_graph(text))  # type: ignore[attr-defined]
        if verdicts[blob]:
            return commit, path
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
        gated = _gated(gate, changed)
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
        tasks = _tasks_in_range(root, merge_base, resolved_head)
        carried = _carried_by_the_range(root, gate, tasks)
    except UnusableError as error:
        print(
            f"::error::{error}; nothing was checked. Refusing the pull request "
            "rather than passing it."
        )
        return 1

    if carried and carried[0] == resolved_head:
        print(
            f"OK: the head commit {resolved_head[:12]} carries {carried[1]} with a "
            f"parseable `## Task Dependency Graph` for {len(gated)} "
            "contract-bearing path(s)."
        )
        return 0

    if carried:
        print(
            f"OK: {carried[1]} carries the task graph at {carried[0][:12]} for "
            f"{len(gated)} contract-bearing path(s), and was cleared before merge "
            "as the two-push sequence requires."
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
    graphless = sorted({path for _, path, _ in tasks})
    print(
        f"  {REQUIRED} in any commit of the range: no"
        + (f" (without a parseable graph: {', '.join(graphless)})" if graphless else "")
    )
    print(
        "  Only committed objects count: an untracked or uncommitted "
        "`.spec/features/` in the checkout is not part of the range."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
