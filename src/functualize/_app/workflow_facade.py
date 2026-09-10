"""Workflow scope creation and lookup — `app.workflows`.

Extracted from :class:`~functualize.app.core.FunctualizeApp`
(engine-sealed-construction/T9). A scope is one walk's identity and its step
records; creating one starts a run, fetching one resumes it. Two members, and
the pair is the whole public surface for it — the walk itself is the engine's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize._engine.capabilities.workflow_scope import WorkflowScope
    from functualize.app.core import FunctualizeApp

__all__ = ["WorkflowScopeFacade"]


class WorkflowScopeFacade:
    """`app.workflows` — create or fetch a workflow scope."""

    __slots__ = ("_app",)

    def __init__(self, app: FunctualizeApp) -> None:
        self._app = app

    def create_workflow_scope(
        self,
        scope_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> WorkflowScope:
        """Create a new WorkflowScope with the given identifier."""
        from functualize._app.impl import create_workflow_scope

        scope: WorkflowScope = create_workflow_scope(self._app, scope_id, metadata)
        return scope

    def get_workflow_scope(self, scope_id: str) -> WorkflowScope:
        """Retrieve an existing WorkflowScope by identifier."""
        from functualize._app.impl import get_workflow_scope

        scope: WorkflowScope = get_workflow_scope(self._app, scope_id)
        return scope
