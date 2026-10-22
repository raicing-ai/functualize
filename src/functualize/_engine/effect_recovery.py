"""Durable attempt and operator verdict for an effecting workflow step."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from functualize._engine.frontier import TERMINAL_SUCCESS, StepStatus, WalkState
from functualize._engine.gate_service import GateAsk
from functualize._types.errors import ScopeCancelledError
from functualize._types.workflow import InDoubt

if TYPE_CHECKING:
    from functualize._engine.workflow_walker import (
        WalkReport,
        WorkflowWalker,
        _Ledger,
        _NodeRun,
    )
    from functualize._types.persistence import StepView


@dataclass(frozen=True)
class Ran:
    """The effect happened; the job must not be entered again."""

    value: Any
    reusable: bool


@dataclass(frozen=True)
class DidNotRun:
    """The operator permits another attempt."""


class EffectRecovery:
    """Own the effecting path while the walker keeps its pure-step path."""

    def __init__(self, walker: WorkflowWalker) -> None:
        self._walker = walker

    def begin(self, name: str, previous: StepView | None) -> None:
        """Persist the attempt before control reaches the job callback."""
        walker = self._walker
        walker._walk.record(
            walker._key(name),
            StepStatus.ATTEMPTING,
            completed_at=None,
            effecting=True,
            attempt=(previous.attempt if previous else 0) + 1,
            started_at=datetime.now(UTC),
        )

    def verdict(
        self, name: str, record: StepView, ledger: _Ledger
    ) -> Ran | DidNotRun | WalkReport:
        """Ask only the derived recovery gate for this exact doubt."""
        from functualize._engine.workflow_walker import WalkReport

        walker = self._walker
        gate = walker._declaration.recovery_gate(name)
        if gate is None:
            raise ValueError(f"effecting step {name!r} has no recovery gate")
        walker._walk.record(
            walker._key(name),
            StepStatus.IN_DOUBT,
            completed_at=None,
            effecting=True,
            attempt=record.attempt,
            started_at=record.started_at,
        )
        prompt = {
            "step": name,
            "attempt": record.attempt,
            "iteration": walker._iteration,
            "started_at": record.started_at.isoformat() if record.started_at else None,
        }
        resolution = walker._walk.resolution(gate.name)
        supersedes = (
            resolution.request.request_id
            if resolution is not None
            and resolution.request.status == "consumed"
            and resolution.request.prompt != prompt
            else None
        )
        answer = walker._gates.service(
            gate,
            walker._walk,
            walker._gate_registry,
            walker._prompt_gates,
            ledger=ledger,
            ask=GateAsk(
                position=name,
                prompt=prompt,
                ladder=["prompt"] if walker._prompt_gates else None,
                supersedes=supersedes,
            ),
        )
        if isinstance(answer, WalkReport):
            reason = (
                f"in_doubt: step {name}, attempt {record.attempt}, "
                f"started_at {prompt['started_at']}"
            )
            return replace(answer, blocked_reason=reason)
        verdict = InDoubt.model_validate(answer.value)
        if verdict.outcome == "did_not_run":
            return DidNotRun()
        return Ran(verdict.value, verdict.value is not None)

    def service(self, name: str, ledger: _Ledger) -> _NodeRun | WalkReport:
        """Replay, ask about an interrupted attempt, or run a new attempt."""
        from functualize._engine.workflow_walker import (
            StepBlocked,
            StepOutcome,
            WalkOutcome,
            WalkReport,
            _NodeRun,
        )

        walker = self._walker
        record = walker._walk.step(walker._key(name))
        if record is not None and record.status in TERMINAL_SUCCESS:
            return _NodeRun(
                record.result,
                replayed=True,
                reusable=False
                if record.result_kind == "missing_recovery_value"
                else None,
            )
        if record is not None and record.status in (
            StepStatus.ATTEMPTING,
            StepStatus.IN_DOUBT,
        ):
            decision = self.verdict(name, record, ledger)
            if isinstance(decision, WalkReport):
                return decision
            if isinstance(decision, Ran):
                return _NodeRun(
                    decision.value, replayed=True, reusable=decision.reusable
                )
        self.begin(name, record)
        try:
            outcome = walker._run_step(name)
        except StepBlocked as blocked:
            attempt = walker._walk.step(walker._key(name))
            walker._walk.record(
                walker._key(name),
                StepStatus.BLOCKED,
                completed_at=datetime.now(UTC),
                effecting=True,
                attempt=attempt.attempt if attempt else 0,
                started_at=attempt.started_at if attempt else None,
            )
            walker._walk.move(WalkState.BLOCKED, name)
            return WalkReport(
                WalkOutcome.BLOCKED,
                walker._scope_id,
                tuple(ledger.executed),
                tuple(ledger.replayed),
                blocked_on=blocked.blocked_on,
                results=ledger.results,
            )
        except ScopeCancelledError as stopped:
            return walker._cancelled(name, stopped)
        except Exception as exc:
            routed = walker._failure_route(name, exc)
            if routed is None:
                return walker._fail(name, f"{type(exc).__name__}: {exc}")
            return _NodeRun(None, failure_route=routed)
        if isinstance(outcome, StepOutcome):
            return _NodeRun(outcome.value, inputs=outcome.inputs)
        return _NodeRun(outcome)
