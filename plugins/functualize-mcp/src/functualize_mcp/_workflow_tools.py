"""MCP workflow tools — discover and advance blocked workflow scopes.

These tools let an external agent drive a `@workflow` across turns:

- ``get_workflow_state`` — one scope's topology, progress, and pending gates
- ``list_workflows`` — survey scopes, with filters
- ``answer_gate`` — record input for a gate, addressed by either identifier
- ``get_gate_draft`` — what is supplied, missing and invalid on one gate
- ``resume_workflow`` — deposit input for a scope with exactly one pending gate
- ``resume_workflow`` — **advance** a scope, optionally answering a gate
- ``cancel_workflow`` — terminate a scope
- ``purge_workflows`` — delete finished scopes

**Where the truth lives.** Everything reported here comes from two places that
outlive the process that wrote them: the *state store* (``.functualize/state.json``
— scope status, step records, gate records, walk position) and the *discovery
cache* (graph topology, via ``JobDescriptor.workflow``). Neither requires
importing the module that declared the workflow, so an agent can inspect a
workflow blocked by a run that has long since exited. Only :meth:`resume_gate`
materializes anything, and only because validating input means having the real
Pydantic model rather than a JSON schema of it.

**``answer`` records; ``resume`` advances.** One meaning each, on every surface.
``answer_gate`` fills the gate's payload slot and runs nothing;
``resume_workflow`` walks the graph in this process and returns what the walk
did. Until this split, *every* tool here was a deposit and nothing an agent
could call advanced a blocked run — the only continuation was re-invoking the
job from a shell, which an agent over MCP cannot do.
"""

from __future__ import annotations

import functools
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize.app.utils import (
    LIVE_STATUSES as _LIVE_STATUSES,
)
from functualize.app.utils import (
    RUN_STATES,
    StateStore,
    answer_gate,
    call_gate_tool,
    cancel_scope,
    describe_run,
    describe_scope,
    gate_draft,
    list_runs,
    list_scopes,
    purge_scopes,
    resolve_advanceable,
    resolve_gate,
    resume_scope,
    run_events,
    run_tree,
)
from functualize.app.utils import (
    GateToolPolicy as _GateToolPolicy,
)
from functualize.app.utils import (
    pending_gates as _pending_gates,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["GateToolPolicy", "WorkflowToolProvider"]

logger = logging.getLogger(__name__)


def _refuse_unreadable_scopes(fn: Any) -> Any:
    """Turn an unreadable scope store into an error envelope, not a traceback.

    Applied to every workflow tool. An agent must never be told a scope does
    not exist when the truth is that the file holding it could not be read —
    that reads as "the run finished or was never started", and the agent acts
    on it. Parity with the CLI, which exits 2 for the same condition.

    ``functools.wraps`` preserves ``__name__``/``__doc__``, and the explicit
    assignments after each tool definition still apply to the wrapper.
    """

    @functools.wraps(fn)
    async def _wrapped(*args: Any, **kwargs: Any) -> Any:
        from functualize.app.utils import ScopeStoreUnreadableError

        try:
            return await fn(*args, **kwargs)
        except ScopeStoreUnreadableError as exc:
            # A count, never content: scope records hold gate payloads.
            return _error(
                "scope_store_unreadable",
                f"{exc}".replace("\n", " ").replace("       ", " "),
            )

    return _wrapped


def _canonical(name: str) -> str:
    """A tool name in the canonical form jobs are registered under."""
    from functualize._types.naming import normalize_name

    return normalize_name(name) or name


#: The gate-tool permission, lifted to ``app/_workflow_control.py``.
#:
#: It governed one surface while only one surface could run a job. That stopped
#: being true when ``builtin workflow resume`` began advancing walks, so the
#: policy moved to where every job-executing path can reach it and this name
#: stays as the plugin's door onto it — ``_server.py`` is unchanged in shape.
GateToolPolicy = _GateToolPolicy


class WorkflowToolProvider:
    """MCP tools over persisted workflow scopes.

    Args:
        app: The FunctualizeApp, used for the discovery cache and for
            materializing gate models on resume.
        store: State store to read. Defaults to the project store resolved
            from the working directory, the same way the engine resolves it.
        run_store: Run log to read. Same defaulting; separate because scopes
            and runs are separate files answering separate questions.
    """

    def __init__(
        self,
        app: Any,
        *,
        store: StateStore | None = None,
        run_store: Any | None = None,
    ) -> None:
        self._app = app
        self._store = store
        self._run_store = run_store

    @property
    def store(self) -> StateStore:
        """The state store, resolved from the cwd on first use."""
        if self._store is None:
            self._store = StateStore.for_project(Path.cwd())
        return self._store

    @property
    def run_store(self) -> Any:
        """The run log, resolved from the cwd on first use.

        Separate from `store` because they are separate files answering
        separate questions — a scope is a workflow's position, a run is one
        execution. Resolved the same way, so the two cannot disagree about
        which project they are in.
        """
        if self._run_store is None:
            from functualize._primitives.run_store import RunStore

            self._run_store = RunStore.for_project(Path.cwd())
        return self._run_store

    def register_tools(self, mcp: Any) -> None:
        """Register the workflow tools with a FastMCP server instance."""
        mcp.add_tool(self._get_workflow_state)
        mcp.add_tool(self._list_workflows)
        mcp.add_tool(self._answer_gate)
        mcp.add_tool(self._get_gate_draft)
        mcp.add_tool(self._resume_workflow)
        mcp.add_tool(self._call_gate_tool)
        mcp.add_tool(self._cancel_workflow)
        mcp.add_tool(self._purge_workflows)
        # The run log's read verbs (`durable-run-layer`/T3), verb for verb with
        # `func builtin run` and over the same projection — decision A3, pinned
        # by the parity test.
        mcp.add_tool(self._list_runs)
        mcp.add_tool(self._get_run)
        mcp.add_tool(self._get_run_events)
        logger.info("WorkflowToolProvider: registered 11 workflow MCP tools")

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @_refuse_unreadable_scopes
    async def _get_workflow_state(self, workflow_id: str) -> dict[str, Any]:
        view = describe_scope(self._app, self.store, workflow_id)
        if view is None:
            return _error("workflow_not_found", f"No workflow scope '{workflow_id}'.")
        return view

    _get_workflow_state.__name__ = "get_workflow_state"
    _get_workflow_state.__qualname__ = "get_workflow_state"
    _get_workflow_state.__doc__ = (
        "Inspect one workflow scope: its graph, which steps have completed, "
        "where the walk stopped, and any gates awaiting input. "
        "Args: workflow_id — the scope identifier."
    )

    @_refuse_unreadable_scopes
    async def _list_workflows(
        self,
        workflow_name: str | None = None,
        state: str | None = None,
        blocked_on: str | None = None,
    ) -> dict[str, Any]:
        return {
            "workflows": list_scopes(
                self._app,
                self.store,
                workflow_name=workflow_name,
                state=state,
                blocked_on=blocked_on,
            )
        }

    _list_workflows.__name__ = "list_workflows"
    _list_workflows.__qualname__ = "list_workflows"
    _list_workflows.__doc__ = (
        "Survey workflow scopes. With no arguments, lists every scope still "
        "running or blocked. Filters: workflow_name — only runs of that "
        "workflow; state — waiting (needs an answer), ready (answered, needs "
        "resume), running, completed, stalled, failed, cancelled; blocked_on — "
        "only runs waiting at that gate. Naming a state widens the search to "
        "finished runs too."
    )

    @_refuse_unreadable_scopes
    async def _answer_gate(
        self,
        values: dict[str, Any],
        workflow_id: str | None = None,
        gate: str | None = None,
        mode: str = "merge",
        commit: bool = True,
        reopen: bool = False,
        unset: list[str] | None = None,
        clear: bool = False,
    ) -> dict[str, Any]:
        resolved = resolve_gate(self.store, workflow_id, gate, include_answered=reopen)
        if isinstance(resolved, dict):
            return resolved
        scope_id, gate_name = resolved
        return answer_gate(
            self._app,
            self.store,
            scope_id,
            gate_name,
            values,
            mode=mode,
            unset=unset,
            clear=clear,
            commit=commit,
            reopen=reopen,
        )

    _answer_gate.__name__ = "answer_gate"
    _answer_gate.__qualname__ = "answer_gate"
    _answer_gate.__doc__ = (
        "Record input for a workflow gate. Does not run the workflow — call "
        "resume_workflow to advance it. Address the gate by workflow_id, by "
        "gate, or by both; either may be omitted when it is unambiguous. Input "
        "accumulates in a draft and the gate is answered only once the draft "
        "validates whole, so several actors can fill different fields of it. "
        "Args: values — field values; workflow_id; gate; mode — merge "
        "(default) or replace; commit — validate and answer when complete "
        "(default true); reopen — move an already-recorded answer back into "
        "the draft to correct it; unset — field names to drop; clear — discard "
        "the draft first."
    )

    @_refuse_unreadable_scopes
    async def _get_gate_draft(
        self, workflow_id: str | None = None, gate: str | None = None
    ) -> dict[str, Any]:
        resolved = resolve_gate(self.store, workflow_id, gate)
        if isinstance(resolved, dict):
            return resolved
        scope_id, gate_name = resolved
        return gate_draft(self._app, self.store, scope_id, gate_name)

    _get_gate_draft.__name__ = "get_gate_draft"
    _get_gate_draft.__qualname__ = "get_gate_draft"
    _get_gate_draft.__doc__ = (
        "Inspect a gate's accumulated draft: what has been supplied, what is "
        "still missing (with each field's type and description), and what is "
        "invalid. Changes nothing. Args: workflow_id; gate — either may be "
        "omitted when unambiguous."
    )

    @_refuse_unreadable_scopes
    async def _resume_workflow(
        self,
        workflow_id: str | None = None,
        input: dict[str, Any] | None = None,
        gate: str | None = None,
        retry_epilogue: bool = False,
    ) -> dict[str, Any]:
        resolved = resolve_advanceable(self.store, workflow_id)
        if isinstance(resolved, dict):
            return resolved
        return resume_scope(
            self._app,
            self.store,
            resolved,
            input=input,
            gate=gate,
            retry_epilogue=retry_epilogue,
            # An MCP tool asked for this resume; `guarded_execute` used to
            # stamp every one of them `app.execute` (rre F9).
            surface="mcp.tool",
        )

    _resume_workflow.__name__ = "resume_workflow"
    _resume_workflow.__qualname__ = "resume_workflow"
    _resume_workflow.__doc__ = (
        "Advance a paused workflow to its next stopping point, optionally "
        "answering a gate on the way. This is the tool that *runs* the "
        "workflow — answer_gate only records. workflow_id may be omitted when "
        "exactly one scope can be advanced. Args: workflow_id; input — gate "
        "values to record first; gate — which pending gate the input answers, "
        "when several; retry_epilogue — clear a stalled epilogue so the "
        "workflow body runs again."
    )

    @_refuse_unreadable_scopes
    async def _purge_workflows(
        self, state: str | None = None, older_than_days: float | None = None
    ) -> dict[str, Any]:
        return purge_scopes(self.store, state=state, older_than_days=older_than_days)

    _purge_workflows.__name__ = "purge_workflows"
    _purge_workflows.__qualname__ = "purge_workflows"
    _purge_workflows.__doc__ = (
        "Delete finished workflow scopes. Never touches a run that is still "
        "running, waiting or ready. Args: state — one of completed, stalled, "
        "failed, cancelled; older_than_days — only scopes whose newest "
        "recorded result is older than this."
    )

    @_refuse_unreadable_scopes
    async def _call_gate_tool(
        self, workflow_id: str, tool: str, args: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Run one of a blocked gate's tools, inside that gate's scope."""
        return call_gate_tool(self._app, self.store, workflow_id, tool, args)

    _call_gate_tool.__name__ = "call_gate_tool"
    _call_gate_tool.__qualname__ = "call_gate_tool"
    _call_gate_tool.__doc__ = (
        "Run a tool offered by a gate that is awaiting input, inside that "
        "workflow's scope. Arguments the gate fixes cannot be supplied. The "
        "call is recorded on the scope but never memoized — calling twice "
        "runs twice. Args: workflow_id; tool — a name from the gate's tools; "
        "args — the remaining arguments."
    )

    @staticmethod
    def _resolve_bound(scope: dict[str, Any], bound: dict[str, Any]) -> dict[str, Any]:
        """Replace each `FromStep` marker with this scope's recorded result.

        Without this the marker object itself was handed to the job as the
        argument value — so `Tool(read_file, allowed=FromStep("setup-vfs"))`
        passed a `FromStep` where a file list was expected, and the narrowing
        the gate exists to enforce silently did not happen.

        A step with no record resolves to None rather than raising: the walk
        may legitimately not have reached it, and the job's own signature is
        the right place for that to be an error.
        """
        from functualize._primitives.fingerprint import reusable_return_value
        from functualize._types.from_job import FromStep

        if not any(isinstance(v, FromStep) for v in bound.values()):
            return dict(bound)

        steps = scope.get("steps") or {}
        resolved: dict[str, Any] = {}
        for arg, value in bound.items():
            if not isinstance(value, FromStep):
                resolved[arg] = value
                continue
            record = next(
                (
                    r
                    for key, r in steps.items()
                    if key.split("::", 1)[0] == value.name and isinstance(r, dict)
                ),
                None,
            )
            resolved[arg] = reusable_return_value(record, job_name=value.name)
        return resolved

    def _bound_values(
        self, scope: dict[str, Any], tool: str
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """The gate's pinned argument *values*, from the live declaration.

        Only the parameter *names* are persisted — a bound value is arbitrary
        and need not be JSON-safe. Reading the values here costs nothing
        extra, because running the job requires materializing its module
        anyway.
        """
        workflow_name = scope.get("workflow")
        try:
            entry = self._app.execution_engine.materialize_job(workflow_name)
            declaration = entry.function.__functualize_workflow__
            for node in declaration.gates():
                for spec in node.tool_specs():
                    # `spec.name` is canonical; `tool` is whatever the agent
                    # typed. Comparing them raw silently found no spec and ran
                    # the job with *no* bound values — the cap the gate exists
                    # to enforce would simply not apply.
                    if spec.name == _canonical(tool):
                        return self._resolve_bound(scope, spec.bound), None
        except Exception as exc:
            return {}, _error(
                "tool_unresolvable",
                f"Cannot load gate policy for '{tool}' from workflow "
                f"'{workflow_name}': {type(exc).__name__}: {exc}",
            )
        return {}, None

    @_refuse_unreadable_scopes
    async def _cancel_workflow(self, workflow_id: str) -> dict[str, Any]:
        return cancel_scope(self.store, workflow_id)

    _cancel_workflow.__name__ = "cancel_workflow"
    _cancel_workflow.__qualname__ = "cancel_workflow"
    _cancel_workflow.__doc__ = (
        "Cancel a running or blocked workflow scope. Cancelled scopes are not "
        "resumable. Args: workflow_id — the scope identifier."
    )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _scopes(self) -> Iterator[tuple[str, dict[str, Any]]]:
        """Every known scope, as ``(scope_id, record)``."""
        for scope_id in self.store.scope_ids():
            scope = self.store.get_scope(scope_id)
            if scope is not None:
                yield scope_id, scope

    def _all_pending_gates(self) -> list[dict[str, Any]]:
        """Every gate awaiting input, across all live scopes.

        Returned on a miss so a caller that guessed the gate name wrong can
        see the real ones without a second round trip.
        """
        return [
            {"gate": name, "workflow_id": scope_id, "workflow": scope.get("workflow")}
            for scope_id, scope in self._scopes()
            if scope.get("status") in _LIVE_STATUSES
            for name, _ in _pending_gates(scope)
        ]

    # ------------------------------------------------------------------
    # The run log (`durable-run-layer`/T3)
    # ------------------------------------------------------------------

    async def _list_runs(
        self,
        job: str | None = None,
        surface: str | None = None,
        state: str | None = None,
        scope_id: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        return {
            "runs": list_runs(
                self.run_store,
                job=job,
                surface=surface,
                state=state,
                scope_id=scope_id,
                limit=limit,
            )
        }

    _list_runs.__name__ = "list_runs"
    _list_runs.__qualname__ = "list_runs"
    _list_runs.__doc__ = (
        "Survey runs, newest first — what executed in this project and how it "
        "ended. Filters: job — only runs of that job; surface — only runs "
        "started through that door (app.cli, http, invoke, mcp.tool, ...); "
        "state — one of "
        + ", ".join(RUN_STATES)
        + "; scope_id — only runs that executed in that workflow scope, which "
        "is how a blocked-and-resumed workflow's several runs are found; "
        "limit — how many rows at most, applied after filtering. "
        "A run is one execution and is read afterwards; a workflow scope is a "
        "position and is resumed. Use list_workflows for the latter."
    )

    async def _get_run(self, run_id: str, tree: bool = False) -> dict[str, Any]:
        view = (
            run_tree(self.run_store, run_id)
            if tree
            else describe_run(self.run_store, run_id)
        )
        if view is None:
            return _error("run_not_found", f"No run '{run_id}'.")
        return view

    _get_run.__name__ = "get_run"
    _get_run.__qualname__ = "get_run"
    _get_run.__doc__ = (
        "Everything known about one run: the job, the door it came through, "
        "how it ended, how long it took, the scope it ran in and its parent. "
        "Args: run_id — the run identifier; tree — when true, nest the runs "
        "this run set off (a workflow step, a dependency, an invoked child) "
        "instead of listing their ids."
    )

    async def _get_run_events(self, run_id: str) -> dict[str, Any]:
        events = run_events(self.run_store, run_id)
        if events is None:
            return _error("run_not_found", f"No run '{run_id}'.")
        return {"run_id": run_id, "events": events}

    _get_run_events.__name__ = "get_run_events"
    _get_run_events.__qualname__ = "get_run_events"
    _get_run_events.__doc__ = (
        "One run's event log, in sequence order. Ordered by seq rather than "
        "timestamp, so a replay is correct across processes on different "
        "clocks. An empty list means the run emitted nothing (or its events "
        "aged out); a run_not_found error means there is no such run. "
        "Args: run_id — the run identifier."
    )


def _now() -> str:
    """UTC timestamp for a recorded call."""
    return datetime.now(UTC).isoformat()


def _error(code: str, message: str) -> dict[str, Any]:
    """A flat error envelope — ``error`` is the machine-readable code."""
    return {"error": code, "message": message}
