"""Run creation and closes pass the lifecycle table; a refusal writes nothing."""

from pathlib import Path

import pytest

from functualize._primitives.run_format import RUNS_KEY, empty_runs
from functualize._primitives.run_store import RunStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.enums import RunStatus
from functualize._types.errors import IllegalTransition


@pytest.mark.parametrize("status", [member.value.lower() for member in RunStatus])
def test_a_running_run_can_close_with_every_run_status(
    tmp_path: Path, status: str
) -> None:
    store = RunStore(JsonFileSubstrate(tmp_path))
    run_id = store.open_run({"job": "build", "surface": "func.job"})
    assert store.get_run(run_id)["status"] == "running"

    store.close_run(run_id, status)

    assert store.get_run(run_id)["status"] == status


def test_an_explicit_running_creation_status_is_accepted(tmp_path: Path) -> None:
    """The one creation edge may also be named by the caller."""
    store = RunStore(JsonFileSubstrate(tmp_path))

    run_id = store.open_run(
        {"job": "build", "surface": "func.job", "status": "running"}
    )

    assert store.get_run(run_id)["status"] == "running"


@pytest.mark.parametrize("status", ["success", "bogus"])
def test_a_creation_status_off_the_edge_is_refused_and_writes_nothing(
    tmp_path: Path, status: str
) -> None:
    """Creation is `(None, "running")` and nothing else.

    `success` is a member of the vocabulary and is still refused — opening a run
    is not closing one — and `bogus` is outside it, refused by the same
    membership test. Both are refused before the store is touched, so the log is
    left as it was rather than holding a run in a state the table never named.
    """
    substrate = JsonFileSubstrate(tmp_path)
    store = RunStore(substrate)

    with pytest.raises(IllegalTransition) as raised:
        store.open_run({"job": "build", "surface": "func.job", "status": status})

    assert (raised.value.machine, raised.value.current, raised.value.target) == (
        "run",
        None,
        status,
    )
    assert store._read() == empty_runs()


def test_a_refused_creation_leaves_a_stored_run_log_byte_identical(
    tmp_path: Path,
) -> None:
    substrate = JsonFileSubstrate(tmp_path)
    store = RunStore(substrate)
    store.open_run({"job": "build", "surface": "func.job"})
    path = substrate.path_for(RUNS_KEY)
    before = path.read_bytes()

    with pytest.raises(IllegalTransition):
        store.open_run({"job": "other", "surface": "func.job", "status": "bogus"})

    assert path.read_bytes() == before


def test_a_terminal_run_cannot_close_again(tmp_path: Path) -> None:
    substrate = JsonFileSubstrate(tmp_path)
    store = RunStore(substrate)
    run_id = store.open_run({"job": "build", "surface": "func.job"})
    store.close_run(run_id, "success")
    path = substrate.path_for(RUNS_KEY)
    before = path.read_bytes()

    with pytest.raises(IllegalTransition) as raised:
        store.close_run(run_id, "failure", failure_detail="late result")

    assert (raised.value.machine, raised.value.current, raised.value.target) == (
        "run",
        "success",
        "failure",
    )
    assert path.read_bytes() == before
    assert RunStore(substrate).get_run(run_id)["status"] == "success"


def test_a_nonterminal_run_can_close_again(tmp_path: Path) -> None:
    store = RunStore(JsonFileSubstrate(tmp_path))
    run_id = store.open_run({"job": "build", "surface": "func.job"})
    store.close_run(run_id, "blocked")
    store.close_run(run_id, "success")

    assert store.get_run(run_id)["status"] == "success"
