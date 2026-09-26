"""Run closes enforce the lifecycle table without changing refused records."""

from pathlib import Path

import pytest

from functualize._primitives.run_format import RUNS_KEY
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

    store.close_run(run_id, status)

    assert store.get_run(run_id)["status"] == status


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
