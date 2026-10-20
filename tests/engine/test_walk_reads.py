"""Walk-record adaptation and parameter injection."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Annotated

import pytest

from functualize._engine.context import ExecutionContext
from functualize._engine.walk_reads import inject_from_step, step_records
from functualize._types.errors import FromStepUnavailableError
from functualize.workflow import FromStep


def _record(value: object, *, reusable: bool = True) -> dict[str, object]:
    return {
        "status": "success",
        "return_value": value,
        "return_value_reusable": reusable,
        "return_value_kind": "json" if reusable else "none",
        "return_value_type": None,
    }


def test_step_records_uses_one_scope_and_preserves_record_fields() -> None:
    seen: list[str] = []

    def steps(scope_id: str) -> list[SimpleNamespace]:
        seen.append(scope_id)
        return [
            SimpleNamespace(
                step_key="approve::0",
                status="success",
                result={"ok": True},
                reusable=True,
                result_kind="json",
                result_type=None,
            )
        ]

    store = SimpleNamespace(workflows=SimpleNamespace(steps=steps))
    assert step_records(store, "walk-1")["approve::0"]["return_value"] == {"ok": True}
    assert seen == ["walk-1"]


def test_recorded_value_is_injected() -> None:
    def reader(value: Annotated[str, FromStep("plan")]) -> str:
        return value

    context = ExecutionContext("reader", reader, {})
    inject_from_step("reader", reader, context, "walk-1", {"plan": _record("yes")}, {})
    assert context.call_kwargs == {"value": "yes"}
    assert context.injected == {"value"}


def test_explicit_argument_wins_even_outside_walk() -> None:
    def reader(value: Annotated[str, FromStep("plan")]) -> str:
        return value

    context = ExecutionContext("reader", reader, {"value": "explicit"})
    inject_from_step("reader", reader, context, None, {}, {})
    assert context.call_kwargs == {"value": "explicit"}


def test_missing_scope_has_named_failure() -> None:
    def reader(value: Annotated[str, FromStep("plan")]) -> str:
        return value

    with pytest.raises(FromStepUnavailableError) as caught:
        inject_from_step(
            "reader", reader, ExecutionContext("reader", reader, {}), None, {}, {}
        )
    assert "FromStep('plan')" in str(caught.value)
    assert "value" in str(caught.value) and "reader" in str(caught.value)


def test_unreusable_record_uses_live_value() -> None:
    def reader(value: Annotated[object, FromStep("plan")]) -> object:
        return value

    handle = object()
    context = ExecutionContext("reader", reader, {})
    inject_from_step(
        "reader",
        reader,
        context,
        "walk-1",
        {"plan": _record(None, reusable=False)},
        {"plan": handle},
    )
    assert context.call_kwargs["value"] is handle


def test_skipped_node_uses_declared_default() -> None:
    def reader(value: Annotated[str, FromStep("plan")] = "fallback") -> str:
        return value

    context = ExecutionContext("reader", reader, {})
    inject_from_step("reader", reader, context, "walk-1", {}, {})
    assert context.call_kwargs == {}


def test_missing_record_without_default_fails() -> None:
    def reader(value: Annotated[str, FromStep("plan")]) -> str:
        return value

    with pytest.raises(FromStepUnavailableError, match="plan"):
        inject_from_step(
            "reader", reader, ExecutionContext("reader", reader, {}), "walk-1", {}, {}
        )


def test_unreusable_record_does_not_use_declared_default() -> None:
    def reader(value: Annotated[str, FromStep("plan")] = "fallback") -> str:
        return value

    with pytest.raises(FromStepUnavailableError, match="plan"):
        inject_from_step(
            "reader",
            reader,
            ExecutionContext("reader", reader, {}),
            "walk-1",
            {"plan": _record(None, reusable=False)},
            {},
        )
