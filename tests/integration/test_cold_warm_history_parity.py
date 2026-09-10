"""A cold run and a warm run of one job leave the same trace — AC-6.

`run-request-entry` AC-6 asks for two things: *"a cold-boot run and a warm-boot
run of the same job produce the same result **and the same recorded history
entry**."* The AC→test table named `TestWarmBootParity`, which compares a **file
trace of execution order**, and `test_lazy_true_engine_materialization.py`,
which compares *import counts* and one warm result. Both are real tests of real
things and neither compares the two runs' results, and nothing anywhere asserted
anything about history cold-versus-warm.

That gap is not academic on this branch: the two boots take **different
wrappers** to the same engine (`click_params.py` eagerly, `lazy_command.py` from
a cached descriptor), and `deliver_job_result`'s own docstring records what it
cost the last time only one of them handled a case — *"Cold boot exited 1, warm
boot exited 0, for the same job and the same failure."*

The history record is the sharper half of the criterion. It carries `status` and
an `args_hash` computed from the call's kwargs, so it is the one artefact that
would notice the two paths **binding arguments differently** — a config field
resolved to its pydantic default on the warm path, say, which is exactly the
defect `FieldDescriptor.from_config_model` exists to prevent. A result
comparison alone would miss that whenever the job's output does not happen to
depend on the field.

Timestamps and durations are excluded because they are the two things that
*must* differ.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

from functualize._primitives.state_store import StateStore
from tests.conftest import surfaces

_JOB = textwrap.dedent(
    '''
    from functualize.job import job


    @job
    def greet(name: str = "world", times: int = 2) -> None:
        """Say hello."""
        for _ in range(times):
            print(f"hello {name}")
    '''
)

#: The fields that identify *the run*, as opposed to when it happened.
_IDENTITY = ("namespace", "job", "args_hash", "status")


def _history(root: Path) -> list[dict[str, Any]]:
    return StateStore.for_project(root).get_history()


def _assert_warm(root: Path) -> None:
    """The second run is only *warm* if the first one left a cache.

    Without this, every assertion in the file could be comparing two cold runs
    and would pass for a reason that has nothing to do with the criterion —
    the same vacuity the reviewer found in the tests AC-6 was assigned to.
    """
    from functualize._primitives.cache_format import CACHE_FILENAME
    from functualize.app.utils import resolve_cache_path

    cache = resolve_cache_path(root)
    assert cache.exists(), (
        f"no discovery cache under {root}, so the second run is not warm and "
        f"this file proves nothing (looked for {CACHE_FILENAME})"
    )


@surfaces("func")
def test_the_two_boots_produce_the_same_output(cli_run, project_tree) -> None:
    root = project_tree(jobs={"greet.py": _JOB}, convention_dirs=True)

    cold = cli_run(["greet", "--name", "ana"], cwd=root)
    _assert_warm(root)
    warm = cli_run(["greet", "--name", "ana"], cwd=root)

    assert cold.exit_code == 0, cold.stdout + cold.stderr
    assert cold.exit_code == warm.exit_code
    assert cold.stdout == warm.stdout


@surfaces("func")
def test_the_two_boots_record_the_same_history_entry(cli_run, project_tree) -> None:
    """The half nothing asserted, and the half that would catch a binding drift."""
    root = project_tree(jobs={"greet.py": _JOB}, convention_dirs=True)

    cli_run(["greet", "--name", "ana"], cwd=root)
    _assert_warm(root)
    cli_run(["greet", "--name", "ana"], cwd=root)

    records = _history(root)
    assert len(records) == 2, f"expected one record per run, got {records}"

    warm, cold = records  # newest first
    for field in _IDENTITY:
        assert cold[field] == warm[field], (
            f"cold and warm disagree about {field!r}: "
            f"{cold[field]!r} vs {warm[field]!r}"
        )


@surfaces("func")
def test_a_different_argument_is_a_different_hash(cli_run, project_tree) -> None:
    """The falsifier.

    Without it, `args_hash` agreeing across the two runs would prove nothing —
    a hash that ignored its input, or was `None` on both paths, would satisfy
    the test above perfectly.
    """
    root = project_tree(jobs={"greet.py": _JOB}, convention_dirs=True)

    cli_run(["greet", "--name", "ana"], cwd=root)
    cli_run(["greet", "--name", "bo"], cwd=root)

    hashes = {record["args_hash"] for record in _history(root)}
    assert len(hashes) == 2, (
        "two runs with different arguments recorded the same args_hash, so the "
        f"hash is not reading its input: {hashes}"
    )


@surfaces("func")
def test_a_default_bound_on_one_path_only_would_show_up(cli_run, project_tree) -> None:
    """States what the parity test is *for*, with the argument left implicit.

    `times` is never passed, so both boots must bind the same default. A warm
    path that resolved defaults differently — the shape of the bug
    `from_config_model` exists to prevent — changes the hash on run 2 while the
    printed output stays identical, which is precisely why comparing results is
    not enough.
    """
    root = project_tree(jobs={"greet.py": _JOB}, convention_dirs=True)

    cold = cli_run(["greet"], cwd=root)
    _assert_warm(root)
    warm = cli_run(["greet"], cwd=root)

    assert cold.stdout == warm.stdout
    records = _history(root)
    assert records[0]["args_hash"] == records[1]["args_hash"]
