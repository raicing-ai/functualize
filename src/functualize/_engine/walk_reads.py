"""Adapt workflow records to the pure walk reader and inject job parameters."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from functualize._primitives.walk_reads import (
    NotCarriable,
    NotRecorded,
    Recorded,
    read_node,
)
from functualize._types.errors import FromStepUnavailableError
from functualize._types.from_job import from_step_refs

if TYPE_CHECKING:
    from functualize._engine.context import ExecutionContext


def step_records(runtime_store: Any, scope_id: str) -> dict[str, dict[str, Any]]:
    """Get this walk's node records through the workflow persistence port."""
    return {
        step.step_key: {
            "status": step.status,
            "return_value": step.result,
            "return_value_reusable": step.reusable,
            "return_value_kind": step.result_kind,
            "return_value_type": step.result_type,
        }
        for step in runtime_store.workflows.steps(scope_id)
    }


def inject_from_step(
    job_name: str,
    function: Any,
    context: ExecutionContext,
    scope_id: str | None,
    records: Mapping[str, Mapping[str, Any]],
    live: Mapping[str, Any],
) -> None:
    """Supply declared walk reads without looking outside this walk."""
    for parameter, source in from_step_refs(function).items():
        if parameter in context.call_kwargs:
            continue
        node = source.ref.name
        if scope_id is None:
            raise FromStepUnavailableError(
                node=node,
                parameter=parameter,
                reader=job_name,
                scope_id=None,
                reason="job is outside a workflow walk",
            )
        result = read_node(records, node, source.declared_type)
        if isinstance(result, Recorded):
            context.call_kwargs[parameter] = result.value
            context.injected.add(parameter)
            continue
        if isinstance(result, NotCarriable) and node in live:
            context.call_kwargs[parameter] = live[node]
            context.injected.add(parameter)
            continue
        if isinstance(result, NotRecorded) and source.has_default:
            continue
        reason = (
            "node has no record in this walk"
            if isinstance(result, NotRecorded)
            else "recorded value cannot be carried to this reader"
        )
        raise FromStepUnavailableError(
            node=node,
            parameter=parameter,
            reader=job_name,
            scope_id=scope_id,
            reason=reason,
        )
