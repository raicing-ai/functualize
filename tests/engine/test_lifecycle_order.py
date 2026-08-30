"""The execution lifecycle's order is a contract, not a comment.

`_execute_lifecycle` is a twenty-step linear procedure and almost every step's
position is a **constraint**, argued in a comment beside it:

* deps before the pre-flight, because a dep may regenerate a file this job
  fingerprints;
* `FromJob` before the pre-flight, because a guard may read one;
* config before the pre-flight, because a guard may take it;
* the `Sources` bind between the pre-flight and the force override, because the
  override discards the decision that bind reads.

Those are good comments and unenforceable ones. Nothing made a wrong order
fail, and the audit that found this named it as the structural cause of three
separate defects. `contributor/reference/execution-lifecycle.md` writes the
sequence down; this file is what stops that page becoming another comment.

Two kinds of check, deliberately:

1. **Structural** — the order of the calls in the method source, compared
   against the documented sequence. Reorder the method and this fails, which is
   what a document alone cannot do.
2. **Behavioural** — three orderings observed through a real run, because a
   source-order check would happily pass on a method whose steps had stopped
   working.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess

PROJECT_ROOT = pathlib.Path(__file__).parent.parent.parent
_EXECUTOR = PROJECT_ROOT / "src" / "functualize" / "_engine" / "executor.py"


# The call that marks each documented step, in the order the page states. Steps
# with no distinctive call of their own (the force branch, the pre-flight
# result's own branch) are omitted rather than pinned to an incidental helper.
_DOCUMENTED_ORDER = [
    "_run_workflow_prelude",  # 2  workflow prelude
    "ExecutionContext",  # 3  build the context
    "_resolve_di_parameters",  # 4  DI          -> context.injected
    "RunContext",  # 5  ensure a RunContext
    "_resolve_config_model",  # 6  config      -> context.injected
    "_resolve_group_options",  # 7  group opts  -> context.injected
    "redacted_snapshot",  # 8  resolved_inputs snapshot
    "_run_dependencies",  # 9  Deps
    "_inject_from_job",  # 10 FromJob     -> context.injected
    "_run_mode_skip",  # 11 Exec.run session skip
    "_preflight_check",  # 12 pre-flight
    "_bind_preflight_capabilities",  # 13 Sources et al
    "_preflight_result",  # 15 skip / refuse / block
    "_exec_policy",  # 17 the body, wrapped in the retry policy
    "_run_deferred_shells",  # 18 sh.defer() unwind, in a finally
    "record_body",  # 19 workflow body-once-per-scope
]


def _call_order() -> list[str]:
    """Every call inside `_execute_lifecycle`, in source order."""
    tree = ast.parse(_EXECUTOR.read_text())
    fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_execute_lifecycle"
    )
    calls: list[tuple[int, str]] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if name:
            calls.append((node.lineno, name))
    return [name for _lineno, name in sorted(calls)]


def test_the_method_follows_the_documented_sequence() -> None:
    """The order in `execution-lifecycle.md`, checked against the source.

    Reordering two steps in `_execute_lifecycle` fails this. That is the whole
    point: the constraints were prose, and prose does not fail.
    """
    order = _call_order()
    positions = {}
    for step in _DOCUMENTED_ORDER:
        assert step in order, (
            f"{step} is documented in contributor/reference/execution-lifecycle.md "
            f"but no longer appears in _execute_lifecycle. If the step was renamed "
            f"or removed, update the page and this list together."
        )
        positions[step] = order.index(step)

    actual = sorted(_DOCUMENTED_ORDER, key=lambda step: positions[step])
    assert actual == _DOCUMENTED_ORDER, (
        "the lifecycle order changed. Documented:\n  "
        + " -> ".join(_DOCUMENTED_ORDER)
        + "\nactual:\n  "
        + " -> ".join(actual)
        + "\nIf the new order is correct, update "
        "contributor/reference/execution-lifecycle.md in the same commit — the "
        "page states *why* each step sits where it does, and a reorder that "
        "leaves the reasons behind is how the constraints were lost the first "
        "time."
    )


def test_the_sources_bind_precedes_the_force_override() -> None:
    """Step 13 before step 14, which is the subtlest constraint of the twenty.

    The force branch discards the pre-flight decision. Binding after it would
    hand a job an empty source map on exactly the runs a `FromJob` dependent
    triggers — a capability that is injected, wired, and silently empty.
    """
    source = _EXECUTOR.read_text()
    bind = source.index("_bind_preflight_capabilities(context, preflight_decision)")
    override = source.index("preflight_decision = None")
    assert bind < override, (
        "the pre-flight bind moved after the force override; a forced run would "
        "give the job an empty Sources map with no error"
    )


def test_the_four_writers_of_context_injected_are_still_four() -> None:
    """`context.injected` is an exact subtraction, and the args hash depends on it.

    A fifth injection site that forgets to record itself silently changes every
    fingerprint key — defect D1, verbatim. This does not stop that; it makes the
    person adding one read the page.
    """
    source = _EXECUTOR.read_text()
    tree = ast.parse(source)
    fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_execute_lifecycle"
    )
    lines = source.splitlines()
    start, end = fn.lineno, fn.end_lineno or fn.lineno
    writes = sum(1 for line in lines[start - 1 : end] if "context.injected.add" in line)
    # One literal call site in _execute_lifecycle (DI); the other three are in
    # the helpers it calls. The count that matters is the total across the
    # engine.
    total = sum(1 for line in lines if "injected.add" in line)
    assert writes >= 1
    assert total == 4, (
        f"{total} sites write context.injected, not 4. Update the list in "
        "contributor/reference/execution-lifecycle.md — an injection site that "
        "does not record itself changes every fingerprint key, silently."
    )


# ─── behavioural: the orderings observed through a real run ────────────────

_MAIN = """
from functualize.app import FunctualizeApp, JobSources
from functualize.app.adapters import CliAdapter

app = FunctualizeApp("o", job_sources=JobSources(directories=["jobs"]))
adapter = CliAdapter()

if __name__ == "__main__":
    adapter(app)
    adapter.run()
"""

_JOBS = """
from pathlib import Path
from typing import Annotated

from functualize.job import Deps, Fingerprint, FromJob, Sources, job

JOB_GROUP = "o"


@job(group=JOB_GROUP)
def upstream() -> str:
    print("STEP dep-body")
    Path("built.txt").write_text("made by the dep\\n")
    return "from-upstream"


@job(
    group=JOB_GROUP,
    deps=Deps("o.upstream"),
    cache=Fingerprint(sources=["built.txt"]),
)
def downstream(
    value: Annotated[str, FromJob("o.upstream")],
    sources: Sources,
) -> None:
    print(f"STEP body fromjob={value!r} sources={sorted(sources.keys())}")
"""


def _project(tmp_path: pathlib.Path) -> pathlib.Path:
    (tmp_path / "main.py").write_text(_MAIN)
    (tmp_path / "config.base.toml").write_text('[general]\napp_name = "o"\n')
    (tmp_path / ".functualize").mkdir()
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "o.py").write_text(_JOBS)
    return tmp_path


def _run(project: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "--project", str(PROJECT_ROOT), "python", "main.py", *args],
        capture_output=True,
        text=True,
        cwd=str(project),
        timeout=120,
    )


def test_a_dep_runs_before_this_jobs_own_freshness_is_decided(
    tmp_path: pathlib.Path,
) -> None:
    """Step 9 before step 12 — the ordering `make` also uses.

    `downstream` fingerprints `built.txt`, which `upstream` writes. If freshness
    were decided first, it would compare against a file the dep is about to
    create — and on a cold run, against a file that does not exist yet.
    """
    project = _project(tmp_path)

    result = _run(project, "o", "downstream")

    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout
    assert "STEP dep-body" in out
    assert "STEP body" in out
    assert out.index("STEP dep-body") < out.index("STEP body")
    # And the dep's output was fingerprintable by the time the pre-flight ran:
    # a second run is fresh rather than re-running.
    second = _run(project, "o", "downstream")
    assert "STEP body" not in second.stdout, second.stdout


def test_sources_is_bound_by_the_time_the_body_runs(
    tmp_path: pathlib.Path,
) -> None:
    """Step 13 before step 17, cold and warm.

    DI creates `Sources` empty at step 4 because the resolved map does not exist
    yet. If the second phase were lost, the body would see an empty mapping with
    no error anywhere.
    """
    project = _project(tmp_path)

    first = _run(project, "o", "downstream")
    assert "sources=['built.txt']" in first.stdout, first.stdout

    # Warm: the command is now built from the cache, which is the path that
    # historically dropped wiring.
    (project / "built.txt").write_text("changed\n")
    second = _run(project, "o", "downstream")
    assert "sources=['built.txt']" in second.stdout, second.stdout


def test_a_fromjob_value_arrives_before_the_body(tmp_path: pathlib.Path) -> None:
    """Step 10 — after the upstreams have run, before the pre-flight."""
    project = _project(tmp_path)

    result = _run(project, "o", "downstream")

    assert "fromjob='from-upstream'" in result.stdout, result.stdout
