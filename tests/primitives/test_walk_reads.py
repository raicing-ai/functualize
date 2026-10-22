"""Walk-local result reads share one record interpretation."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from functualize._primitives.walk_reads import (
    NotCarriable,
    NotRecorded,
    Recorded,
    read_node,
    resolve_bound_values,
)
from functualize._types.errors import FromStepUnavailableError
from functualize.workflow import FromStep


def _record(value: Any, *, reusable: bool = True) -> dict[str, Any]:
    return {
        "status": "success",
        "return_value": value,
        "return_value_reusable": reusable,
    }


class Approval(BaseModel):
    ok: bool


class TestReadNode:
    def test_canonical_name_matches_the_record_prefix(self) -> None:
        records = {"approve::": _record({"ok": True})}
        assert read_node(records, "approve") == Recorded({"ok": True})
        assert read_node(records.items(), "approve") == Recorded({"ok": True})
        assert read_node(records, "appro") == NotRecorded()

    def test_declared_type_rebuilds_a_recorded_model(self) -> None:
        records = {"approve::": _record({"ok": True})}
        assert read_node(records, "approve", Approval) == Recorded(Approval(ok=True))

    def test_deliberate_none_is_still_recorded(self) -> None:
        assert read_node({"empty::": _record(None)}, "empty") == Recorded(None)

    def test_missing_or_failed_node_is_not_recorded(self) -> None:
        assert read_node({}, "absent") == NotRecorded()
        assert read_node({"failed::": {"status": "failed"}}, "failed") == NotRecorded()

    def test_nonserializable_or_invalid_value_is_not_carriable(self) -> None:
        assert read_node({"lock::": _record(None, reusable=False)}, "lock") == (
            NotCarriable()
        )
        assert read_node({"approve::": _record({"ok": "wrong"})}, "approve", int) == (
            NotCarriable()
        )


class TestResolveBoundValues:
    def test_multiple_markers_and_literals_are_resolved(self) -> None:
        records = {
            "one::": _record("first"),
            "approve::": _record({"ok": True}),
        }
        assert resolve_bound_values(
            records.items(),
            {"name": FromStep("one"), "answer": FromStep("approve"), "limit": 2},
        ) == {"name": "first", "answer": {"ok": True}, "limit": 2}

    @pytest.mark.parametrize(
        ("records", "reason"),
        [
            ({}, "no record"),
            ({"node::": _record(None, reusable=False)}, "cannot be carried"),
        ],
    )
    def test_unavailable_binding_names_the_read(
        self, records: dict[str, dict[str, Any]], reason: str
    ) -> None:
        with pytest.raises(FromStepUnavailableError) as caught:
            resolve_bound_values(
                records,
                {"allowed": FromStep("node")},
                reader="approve",
                scope_id="run-1",
            )
        error = caught.value
        assert (error.node, error.parameter, error.reader, error.scope_id) == (
            "node",
            "allowed",
            "approve",
            "run-1",
        )
        assert "FromStep('node')" in str(error)
        assert reason in str(error)
