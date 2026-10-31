"""The gated skill selection: two skills offered, one gate, no fallback.

The decision the feature makes is which skill's body to mount, and this module
is that decision as a real workflow — not a prompt and not a helper the
measurement could bypass. ``build_selection`` declares it, ``select`` walks it
through a fresh app, and ``decision_record`` is the only thing read back, so a
number in a report can always be traced to the gate that produced it.

No fallback is declared and that is deliberate (C-4). A proposal that does not
clear the thresholds, or a provider that cannot answer, leaves the gate
**blocked**: the outcome is :data:`ESCALATED`, never the native (unselected)
behaviour. A silent fall to the baseline is the one result this measurement
must not be able to report as a decision.

Five routes, one per catalog option. Each is a job that records nothing and
returns its own name — the walk's interesting state is the gate's evidence,
which the framework records, not a counter kept here.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from functualize.app import FunctualizeApp
from functualize.app.utils import ScopeStore, decision_record
from functualize.plugin import DecisionGateResolver, DecisionProvider
from functualize.types import JobResult, RunRequest
from functualize.workflow import (
    END,
    ChoiceDecision,
    ConditionalEdge,
    Edge,
    FromStep,
    Gate,
    Step,
    workflow,
)
from tests.skill_router_eval.catalog import OPTIONS, Entry, option_meanings

__all__ = [
    "ESCALATED",
    "SELECT_INSTRUCTIONS",
    "Selection",
    "SkillChoice",
    "build_selection",
    "select",
    "select_decision",
]

#: What the gate is asked. The request itself is the state; the instruction is
#: fixed, so a run's wording cannot drift into the corpus.
SELECT_INSTRUCTIONS = (
    "Choose the one functualize skill whose instructions this request needs "
    "before work starts, or none if no functualize skill applies."
)

#: The outcome when no proposal was accepted. Not an ``OPTIONS`` value: an
#: escalated request has no selection, which is a different answer from `none`.
ESCALATED = "escalated"

_APP_NAME = "skill-router"
_WORKFLOW = "select"
_SURFACE = "app.execute"
_DECISION = "decision"
_INTAKE = "intake"

#: The declaration's thresholds, in one place: the lock stores them from here.
ACCEPT_AT = 0.70
MIN_MARGIN = 0.10

Skill = Literal[
    "functualize",
    "functualize-app",
    "functualize-cli",
    "functualize-skill",
    "none",
]

class SkillChoice(BaseModel):
    """The gate's answer: one catalog option.

    ``skill`` has no default on purpose — a default would answer the gate
    without a decision, which is exactly the silent native fallback C-4 rules
    out.
    """

    skill: Skill

def select_decision(entries: Sequence[Entry]) -> ChoiceDecision:
    """The gate's declaration, built from the catalog the run was given."""
    return ChoiceDecision(
        field="skill",
        instructions=SELECT_INSTRUCTIONS,
        options=option_meanings(entries),
        state=FromStep(_INTAKE),
        accept_at=ACCEPT_AT,
        min_margin=MIN_MARGIN,
        fallback=None,
    )

def _stub(option: str) -> Any:
    """A route's job: say which route ran, do nothing else."""

    def job() -> str:
        return option

    return job

def build_selection(
    app: FunctualizeApp, text: str, entries: Sequence[Entry]
) -> None:
    """Register workflow ``select`` and its one job per option on ``app``."""

    def intake() -> str:
        return text

    @workflow(
        steps=[
            Step(_INTAKE),
            Gate(name=_WORKFLOW, awaits=SkillChoice, decide=select_decision(entries)),
            *(Step(option) for option in OPTIONS),
        ],
        edges=[
            Edge(_INTAKE, _WORKFLOW),
            ConditionalEdge(
                source=_WORKFLOW,
                condition=lambda answer: answer["skill"],
                targets={option: option for option in OPTIONS},
            ),
            *(Edge(option, END) for option in OPTIONS),
        ],
    )
    def select_workflow() -> str:
        return "selected"

    app.register_dynamic_job(_INTAKE, intake)
    for option in OPTIONS:
        app.register_dynamic_job(option, _stub(option))
    app.register_dynamic_job(_WORKFLOW, select_workflow)

@dataclass(frozen=True)
class Selection:
    """One request's selection, read back from the gate's record.

    ``outcome`` is the accepted option, or :data:`ESCALATED` when the gate did
    not decide. ``decided_by`` is the record's own answer to who took the gate —
    ``"decision"`` here, ``None`` when nobody did — so a report can tell a
    decision from a block without inferring it from ``outcome``.
    """

    outcome: str
    decided_by: str | None
    record: Mapping[str, Any]

    @property
    def rule_digest(self) -> str | None:
        """The digest of the rule the gate applied, as it recorded it."""
        evidence = self.record.get("evidence") or {}
        rule = evidence.get("rule") or {}
        return rule.get("digest")

def _walk(
    text: str,
    provider: DecisionProvider,
    *,
    entries: Sequence[Entry],
    project: Path,
    scope: str,
) -> tuple[JobResult, Selection]:
    """Drive one walk and return both its run result and the gate's record.

    The process's working directory is set to ``project`` for the walk and
    restored afterwards: the app resolves its project root and its substrate
    from there, and a caller must not inherit either.

    The run result is returned alongside the selection so the status is
    readable, not inferred: a blocked gate is a fact of the walk, and
    :func:`select` is not the only thing entitled to know it.
    """
    project = Path(project).resolve()
    previous = Path.cwd()
    os.chdir(project)
    try:
        app = FunctualizeApp(name=_APP_NAME)
        build_selection(app, text, entries)
        app.gates.register_gate_strategy(_DECISION, DecisionGateResolver(provider))
        result = app.execute(
            RunRequest(
                job_name=_WORKFLOW,
                surface=_SURFACE,
                workflow_scope_id=scope,
            )
        )
        record = decision_record(ScopeStore(app.substrate), scope, _WORKFLOW)
    finally:
        os.chdir(previous)
    payload = dict(record or {})
    decided_by = payload.get("decided_by")
    outcome = payload.get("route") if decided_by == _DECISION else ESCALATED
    selection = Selection(
        outcome=outcome or ESCALATED, decided_by=decided_by, record=payload
    )
    return result, selection

def select(
    text: str,
    provider: DecisionProvider,
    *,
    entries: Sequence[Entry],
    project: Path,
    scope: str,
) -> Selection:
    """Walk one request through the selection workflow and read its record."""
    return _walk(
        text, provider, entries=entries, project=project, scope=scope
    )[1]
