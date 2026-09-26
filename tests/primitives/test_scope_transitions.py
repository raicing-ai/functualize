"""A refused scope move leaves the durable envelope untouched."""

from pathlib import Path

import pytest

from functualize._primitives.scope_format import SCOPES_KEY
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.errors import IllegalTransition


@pytest.mark.parametrize(
    ("current", "target"),
    [("cancelled", "running"), ("blocked", "completed")],
)
def test_an_illegal_scope_move_refuses_without_writing(
    tmp_path: Path, current: str, target: str
) -> None:
    substrate = JsonFileSubstrate(tmp_path)
    store = ScopeStore(substrate)
    store.ensure_scope("wf", "demo")
    store.set_scope_status("wf", current)
    path = substrate.path_for(SCOPES_KEY)
    before = path.read_bytes()

    with pytest.raises(IllegalTransition) as raised:
        store.set_scope_status("wf", target)

    assert (raised.value.machine, raised.value.current, raised.value.target) == (
        "scope",
        current,
        target,
    )
    assert path.read_bytes() == before
    assert ScopeStore(substrate).get_scope("wf")["status"] == current


def test_a_resumed_scope_can_complete(tmp_path: Path) -> None:
    store = ScopeStore(JsonFileSubstrate(tmp_path))
    store.ensure_scope("wf", "demo")
    store.set_scope_status("wf", "blocked")
    store.set_scope_status("wf", "running")
    store.set_scope_status("wf", "completed")

    assert store.get_scope("wf")["status"] == "completed"
