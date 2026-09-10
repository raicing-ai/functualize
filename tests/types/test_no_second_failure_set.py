"""No second copy of "which statuses are not a failure", anywhere in `src/`.

`functualize._types.outcome` is the authority: `is_failure(status, family=...)`.
The feature's headline acceptance criterion (AC-2) is that no other module
carries its own set — and its gate was

    rg 'RunStatus.SUCCESS, RunStatus.SKIPPED, RunStatus.BLOCKED' src/

which found nothing, while `_engine/capabilities/invoke.py` held exactly that
set wrapped across three lines by `ruff format`. Sixth time on this branch that
a single-line pattern missed a wrapped one, and the first time it hid a real
divergence: the wrapped copy read BLOCKED as *not* a failure while the same
command's exit code read it as one.

So the check is an **AST scan**, where formatting is not a variable. It finds
every literal collection of two or more `RunStatus` members, wherever it is
written and however it is wrapped.

**The allowlist is the point.** A grep that finds nothing tells you nothing; a
scan with named exceptions makes each surviving set something a person decided
to keep, in writing. Adding to it should feel like an argument, because it is.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src" / "functualize"

#: `module path -> why this collection of statuses is not a delivery decision`.
#:
#: A delivery decision answers *how does this run reach a boundary* — an exit
#: code, a panel, a status code, a CI annotation. Those belong to `outcome.py`.
#: A **graph** decision answers *did this step satisfy the edge that depends on
#: it*, which is the scheduler's business and has no boundary in it at all.
_ALLOWED: dict[str, str] = {
    "_types/outcome.py": "the authority itself",
    "_engine/executor.py": (
        "graph edges: the dependency scheduler and the walk ask whether a "
        "predecessor satisfied its edge, not how a run is delivered"
    ),
    "_engine/capabilities/workflow.py": (
        "graph edges: which step statuses stop a walk"
    ),
    "_engine/capabilities/runcontext.py": (
        "not a failure question at all: `_TERMINAL_STATES` is the lifecycle "
        "state machine's 'can this transition?', which has no boundary in it"
    ),
    "_engine/capabilities/invoke.py": (
        "graph edges: whether an invoked dependency counts as satisfied. The "
        "*delivery* set that used to live here — the one that decided the "
        "`::error::` annotation — moved to `_cli/parallel_output.py`, which is "
        "the surface that renders it"
    ),
}


def _status_sets(path: Path) -> list[int]:
    """Line numbers of literal collections holding 2+ `RunStatus` members."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Tuple | ast.Set | ast.List):
            continue
        members = [
            e
            for e in node.elts
            if isinstance(e, ast.Attribute)
            and isinstance(e.value, ast.Name)
            and e.value.id == "RunStatus"
        ]
        if len(members) >= 2:
            found.append(node.lineno)
    return found


def test_no_module_outside_the_allowlist_carries_a_status_set() -> None:
    offenders: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_SRC).as_posix()
        if rel in _ALLOWED:
            continue
        for line in _status_sets(path):
            offenders.append(f"{rel}:{line}")

    assert not offenders, (
        "A second answer to 'is this status a failure?' has appeared. Ask "
        "`functualize.types.is_failure(status, family=...)` instead, or — if it "
        "is a graph decision rather than a delivery one — add the module to "
        "`_ALLOWED` with the reason:\n  " + "\n  ".join(offenders)
    )


def test_the_scan_can_actually_find_something() -> None:
    """The falsifier this whole file exists because of.

    An empty result is exactly what the broken grep produced. So: the scan is
    pointed at a module known to contain a set, and must find it.
    """
    assert _status_sets(_SRC / "_types" / "outcome.py"), (
        "the scan found no status collection in the authority module itself, "
        "which means it would find none anywhere"
    )


def test_every_allowlisted_module_still_has_one() -> None:
    """An allowlist entry that no longer applies is a hole nobody can see.

    If a module stops carrying a status set, its exemption must go with it —
    otherwise a *new* set can be added there later and this test will wave it
    through on the strength of an argument made about different code.
    """
    stale = [
        rel
        for rel in _ALLOWED
        if (_SRC / rel).exists() and not _status_sets(_SRC / rel)
    ]
    assert not stale, (
        "these modules no longer contain a status collection, so their "
        f"`_ALLOWED` entries should be deleted: {stale}"
    )
