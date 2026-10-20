"""Tool-call approval tests — gating through the real agent loop.

Every test drives the loop with pydantic-ai's scripted models
(``TestModel`` / ``FunctionModel``): no network, no API key. The scenarios
E1–E10 are pinned by the approved shape intent and the feature spec; the
ungated control (E1) doubles as the regression fence — a scope that never
called ``approval_required()`` behaves exactly as before.

Validates: spec acceptance criteria E1–E10 (see
``.spec/features/tool-call-approval/spec.md``).
"""

from __future__ import annotations

from typing import Any

import pytest
from functualize_ai import AI, ToolScope
from functualize_ai._config import AIConfig
from functualize_ai._errors import AINotAvailableError
from functualize_ai_pydantic import PydanticAI, PydanticAIProvider
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel

REFUSAL = "Tool call refused: approval required for '{name}'."


class _RecordingBus:
    """Duck-typed event bus that records emissions for assertions."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_name: str, **payload: Any) -> None:
        self.events.append((event_name, payload))

    def tool_called(self) -> list[dict[str, Any]]:
        return [p for n, p in self.events if n == "ai.tool.called"]


@pytest.fixture
def bus() -> _RecordingBus:
    return _RecordingBus()


@pytest.fixture
def ran() -> list[Any]:
    """Shared record of which tool bodies executed and with what args."""
    return []


@pytest.fixture
def make_delete(ran: list[Any]):
    """A destructive tool the model can call."""

    def _make(name: str = "delete") -> Any:
        def delete(job_id: int) -> str:
            """Delete a row."""
            ran.append((name, job_id))
            return f"deleted {job_id}"

        delete.__name__ = name
        return delete

    return _make


def _loop_cap(bus: _RecordingBus, model: Any) -> PydanticAI:
    return PydanticAI(_provider=object(), _event_bus=bus, _model=model)


def _scripted_two_step_delete() -> FunctionModel:
    """A model that calls delete(job_id=1), then delete(job_id=2), then stops."""

    async def fn(messages: list[Any], info: Any) -> ModelResponse:
        tool_returns = sum(
            1
            for m in messages
            for p in getattr(m, "parts", [])
            if getattr(p, "part_kind", "") == "tool-return"
        )
        if tool_returns == 0:
            return ModelResponse(
                parts=[ToolCallPart(tool_name="delete", args={"job_id": 1})]
            )
        if tool_returns == 1:
            return ModelResponse(
                parts=[ToolCallPart(tool_name="delete", args={"job_id": 2})]
            )
        return ModelResponse(parts=[TextPart(content="done")])

    return FunctionModel(fn)


def _allow_all(name: str, args: dict[str, Any], ctx: Any) -> bool:
    return True


def _deny_all(name: str, args: dict[str, Any], ctx: Any) -> bool:
    return False


# ---------------------------------------------------------------------------
# E1 — ungated control: identical to today
# ---------------------------------------------------------------------------


class TestE1UngatedControl:
    def test_ungated_tool_runs_once_with_success_event(
        self, bus: _RecordingBus, ran: list[Any], make_delete
    ) -> None:
        cap = _loop_cap(bus, TestModel(call_tools=["delete"]))
        result = cap.run_agent_loop(
            "clean up", tools=ToolScope.functions([make_delete()])
        )

        assert ran == [("delete", 0)]
        assert result.tool_calls[0].tool_name == "delete"
        assert result.tool_calls[0].result == "deleted 0"
        assert [p["status"] for p in bus.tool_called()] == ["success"]


# ---------------------------------------------------------------------------
# E2 — approval_required() with no gate: deny every call, loop completes
# ---------------------------------------------------------------------------


class TestE2NoGateDeniesAll:
    def test_tool_never_runs_and_model_sees_refusal(
        self, bus: _RecordingBus, ran: list[Any], make_delete
    ) -> None:
        scope = ToolScope.functions([make_delete()]).approval_required()
        cap = _loop_cap(bus, TestModel(call_tools=["delete"]))
        result = cap.run_agent_loop("clean up", tools=scope)

        assert ran == []
        refusal = REFUSAL.format(name="delete")
        assert result.tool_calls[0].result == refusal
        # The run completes normally — a refusal is not a failure.
        assert isinstance(result.output, str)

    def test_event_reports_denied_not_success(
        self, bus: _RecordingBus, ran: list[Any], make_delete
    ) -> None:
        scope = ToolScope.functions([make_delete()]).approval_required()
        cap = _loop_cap(bus, TestModel(call_tools=["delete"]))
        cap.run_agent_loop("clean up", tools=scope)

        statuses = [p["status"] for p in bus.tool_called()]
        assert statuses == ["denied"]


# ---------------------------------------------------------------------------
# E3 — the gate receives (tool_name, args, ToolCallContext) and decides
# ---------------------------------------------------------------------------


class TestE3GateContract:
    def test_gate_decides_per_call_and_receives_the_triple(
        self, bus: _RecordingBus, ran: list[Any], make_delete
    ) -> None:
        from functualize_ai import ToolCallContext

        seen: list[tuple[Any, Any, Any]] = []

        def gate(tool_name: str, args: dict[str, Any], ctx: Any) -> bool:
            seen.append((tool_name, dict(args), ctx))
            return args.get("job_id") != 1

        scope = ToolScope.functions([make_delete()]).approval_required(gate)
        cap = _loop_cap(bus, _scripted_two_step_delete())
        result = cap.run_agent_loop("clean up", tools=scope)

        refusal = REFUSAL.format(name="delete")
        results = [tc.result for tc in result.tool_calls]
        assert results == [refusal, "deleted 2"]
        assert ran == [("delete", 2)]
        assert seen[0] == (
            "delete",
            {"job_id": 1},
            ToolCallContext(job_name=None, description="Delete a row."),
        )
        assert seen[1][0] == "delete" and seen[1][1] == {"job_id": 2}
        statuses = sorted(p["status"] for p in bus.tool_called())
        assert statuses == ["denied", "success"]


# ---------------------------------------------------------------------------
# E4 — only a strict True admits
# ---------------------------------------------------------------------------


class TestE4StrictTrue:
    @pytest.mark.parametrize("bad_return", [None, 1, "yes"])
    def test_truthy_non_true_denies(
        self, bus: _RecordingBus, ran: list[Any], make_delete, bad_return: Any
    ) -> None:
        def gate(tool_name: str, args: dict[str, Any], ctx: Any) -> Any:
            return bad_return

        scope = ToolScope.functions([make_delete()]).approval_required(gate)
        cap = _loop_cap(bus, TestModel(call_tools=["delete"]))
        result = cap.run_agent_loop("clean up", tools=scope)

        assert ran == []
        assert result.tool_calls[0].result == REFUSAL.format(name="delete")
        assert [p["status"] for p in bus.tool_called()] == ["denied"]


# ---------------------------------------------------------------------------
# E5 — a raising gate ends the run with its own exception
# ---------------------------------------------------------------------------


class TestE5GateRaises:
    def test_runtime_error_reaches_caller_unwrapped(
        self, bus: _RecordingBus, ran: list[Any], make_delete
    ) -> None:
        def boom(tool_name: str, args: dict[str, Any], ctx: Any) -> bool:
            raise RuntimeError("gate exploded")

        scope = ToolScope.functions([make_delete()]).approval_required(boom)
        cap = _loop_cap(bus, TestModel(call_tools=["delete"]))

        with pytest.raises(RuntimeError, match="gate exploded") as excinfo:
            cap.run_agent_loop("clean up", tools=scope)
        assert not isinstance(excinfo.value, AINotAvailableError)
        assert ran == []


# ---------------------------------------------------------------------------
# E6 — per-tool approval across a union
# ---------------------------------------------------------------------------


class TestE6UnionPerTool:
    def test_gated_operand_refused_plain_operand_runs(
        self, bus: _RecordingBus, ran: list[Any], make_delete
    ) -> None:
        def read_row(job_id: int) -> str:
            """Read a row."""
            ran.append(("read_row", job_id))
            return f"read {job_id}"

        gated = ToolScope.functions([make_delete()]).approval_required(_deny_all)
        plain = ToolScope.functions([read_row])
        cap = _loop_cap(bus, TestModel(call_tools=["delete", "read_row"]))
        result = cap.run_agent_loop("clean up", tools=gated + plain)

        assert ran == [("read_row", 0)]
        by_name = {tc.tool_name: tc.result for tc in result.tool_calls}
        assert by_name["delete"] == REFUSAL.format(name="delete")
        assert by_name["read_row"] == "read 0"
        by_status = {p["tool_name"]: p["status"] for p in bus.tool_called()}
        assert by_status == {"delete": "denied", "read_row": "success"}


# ---------------------------------------------------------------------------
# E7 — gated wins regardless of filter order (same tool name)
# ---------------------------------------------------------------------------


class TestE7GatedWins:
    def test_same_name_gated_in_either_order(
        self, bus: _RecordingBus, ran: list[Any], make_delete
    ) -> None:
        def shadow(job_id: int) -> str:
            """Shadow copy."""
            ran.append(("shadow", job_id))
            return "shadow"

        shadow.__name__ = "delete"

        gated = ToolScope.functions([make_delete()]).approval_required(_deny_all)
        plain = ToolScope.functions([shadow])

        for combined in (gated + plain, plain + gated):
            ran.clear()
            bus.events.clear()
            cap = _loop_cap(bus, TestModel(call_tools=["delete"]))
            result = cap.run_agent_loop("clean up", tools=combined)
            assert ran == [], combined
            assert result.tool_calls[0].result == REFUSAL.format(name="delete")


# ---------------------------------------------------------------------------
# E8 — applying approval twice ANDs the gates
# ---------------------------------------------------------------------------


class TestE8DoubleApplyAnds:
    def test_allow_then_deny_is_refused(
        self, bus: _RecordingBus, ran: list[Any], make_delete
    ) -> None:
        scope = (
            ToolScope.functions([make_delete()])
            .approval_required(_allow_all)
            .approval_required(_deny_all)
        )
        cap = _loop_cap(bus, TestModel(call_tools=["delete"]))
        result = cap.run_agent_loop("clean up", tools=scope)

        assert ran == []
        assert result.tool_calls[0].result == REFUSAL.format(name="delete")


# ---------------------------------------------------------------------------
# E9 — identical refusal on all three entry points
# ---------------------------------------------------------------------------


class TestE9AllEntryPoints:
    def _deny_scope(self, make_delete) -> ToolScope:
        return ToolScope.functions([make_delete()]).approval_required()

    def test_run_agent_loop(
        self, bus: _RecordingBus, ran: list[Any], make_delete
    ) -> None:
        cap = _loop_cap(bus, TestModel(call_tools=["delete"]))
        result = cap.run_agent_loop("clean up", tools=self._deny_scope(make_delete))
        assert ran == []
        assert result.tool_calls[0].result == REFUSAL.format(name="delete")
        assert [p["status"] for p in bus.tool_called()] == ["denied"]

    def test_run_with_history(
        self, bus: _RecordingBus, ran: list[Any], make_delete
    ) -> None:
        cap = _loop_cap(bus, TestModel(call_tools=["delete"]))
        result = cap.run_with_history(
            [{"role": "user", "content": "clean up"}],
            tools=self._deny_scope(make_delete),
        )
        assert ran == []
        assert result.tool_calls[0].result == REFUSAL.format(name="delete")
        assert [p["status"] for p in bus.tool_called()] == ["denied"]

    def test_ai_run_through_provider(
        self, bus: _RecordingBus, ran: list[Any], make_delete
    ) -> None:
        config = AIConfig(provider="pydantic", model="test")
        provider = PydanticAIProvider(config)
        ai = AI(_provider=provider, _event_bus=bus)
        result = ai.run(
            "clean up",
            tools=self._deny_scope(make_delete),
            model=TestModel(call_tools=["delete"]),
        )
        assert ran == []
        assert result.tool_calls[0].result == REFUSAL.format(name="delete")
        assert [p["status"] for p in bus.tool_called()] == ["denied"]

    def test_ai_run_gate_exception_unwrapped(
        self, bus: _RecordingBus, ran: list[Any], make_delete
    ) -> None:
        def boom(tool_name: str, args: dict[str, Any], ctx: Any) -> bool:
            raise RuntimeError("gate exploded")

        scope = ToolScope.functions([make_delete()]).approval_required(boom)
        config = AIConfig(provider="pydantic", model="test")
        provider = PydanticAIProvider(config)
        ai = AI(_provider=provider, _event_bus=bus)

        with pytest.raises(RuntimeError, match="gate exploded") as excinfo:
            ai.run(
                "clean up",
                tools=scope,
                model=TestModel(call_tools=["delete"]),
            )
        assert not isinstance(excinfo.value, AINotAvailableError)
        assert ran == []
        failures = [p for n, p in bus.events if n == "ai.call.failed"]
        assert len(failures) == 1  # the failure is observable, then raised


# ---------------------------------------------------------------------------
# E10 — ToolDef construction stays valid without approval (unit fence)
# ---------------------------------------------------------------------------


class TestE10ToolDefConstruction:
    def test_translator_accepts_legacy_defs(self) -> None:
        from functualize_ai import ToolDef
        from functualize_ai_pydantic import ToolScopeTranslator

        def tool(x: int) -> str:
            """Doc."""
            return str(x)

        tool_def = ToolDef(
            "tool", "Doc.", {"type": "object", "properties": {}}, None, tool
        )
        translated = ToolScopeTranslator().translate([tool_def])
        assert len(translated) == 1
