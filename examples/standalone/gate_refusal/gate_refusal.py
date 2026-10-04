"""Answering a gate by the name it was declared with.

A workflow declares ``Gate(name="approve_refund", ...)`` — the Python
spelling. The walk parks it under the canonical node name ``approve-refund``,
and the public answer path accepts either spelling, so the name an author
types is the name that works. This example shows the two halves a caller
cares about: the declared spelling answers, and a name that matches nothing
raises :class:`GateNotFoundError` naming the gates that do exist — a miss
the caller cannot ignore.

Run it from an empty directory (the walk writes its scope records to
``.functualize/`` beside you).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from functualize.app.core import FunctualizeApp
from functualize.app.utils import GateNotFoundError, ScopeStore, answer_gate
from functualize.types import RunRequest
from functualize.workflow import END, Edge, Gate, Step, workflow


class Approval(BaseModel):
    """What the gate waits for before the release may proceed."""

    approved: bool


def build_app() -> FunctualizeApp:
    """The release workflow: one gate, declared with a two-word name."""
    app = FunctualizeApp(name="release")

    def build() -> str:
        return "artifact"

    def deploy() -> str:
        return "deployed"

    @workflow(
        steps=[
            Step("build"),
            Gate(name="approve_refund", awaits=Approval),
            Step("deploy"),
        ],
        edges=[
            Edge(source="build", target="approve_refund"),
            Edge(source="approve_refund", target="deploy"),
            Edge(source="deploy", target=END),
        ],
    )
    def release() -> str:
        return "release complete"

    app.register_dynamic_job("build", build)
    app.register_dynamic_job("deploy", deploy)
    app.register_dynamic_job("release", release)
    return app


def park_at_the_gate(app: FunctualizeApp, scope_id: str) -> None:
    """Start the walk under a chosen scope id; it blocks at the gate."""
    app.execute(
        RunRequest(
            job_name="release", surface="app.execute", workflow_scope_id=scope_id
        )
    )


def answer_by_declared_name(
    app: FunctualizeApp, store: ScopeStore, scope_id: str
) -> dict[str, Any]:
    """Record the approval using the name the workflow declared it with."""
    payload = Approval(approved=True).model_dump()
    return answer_gate(app, store, scope_id, "approve_refund", payload)


def the_miss_a_caller_cannot_ignore(
    app: FunctualizeApp, store: ScopeStore, scope_id: str
) -> str:
    """What a mistyped gate name does: raises, carrying the real roster.

    The exception knows the reference as typed, the scope it was addressed
    to, and the gates that scope actually has — everything a caller needs to
    correct itself.
    """
    try:
        answer_gate(app, store, scope_id, "nope", {"approved": True})
    except GateNotFoundError as exc:
        return f"'{exc.gate}' in '{exc.scope_id}' is not one of: {', '.join(exc.known)}"
    raise AssertionError("an unknown gate reference must raise, not return")


def main() -> None:
    app = build_app()
    store = ScopeStore(app.substrate)

    park_at_the_gate(app, "rel-1")
    answered = answer_by_declared_name(app, store, "rel-1")
    print(f"answered: {answered['gate']} -> {answered['status']}")
    print(f"missed:   {the_miss_a_caller_cannot_ignore(app, store, 'rel-1')}")


if __name__ == "__main__":
    main()
