"""MCP workflow tools — discover and advance blocked workflow scopes.

These tools let an external agent drive a `@workflow` across turns:

- ``get_workflow_state`` — one scope's topology, progress, and pending gates
- ``list_workflows`` — survey scopes, with filters
- ``answer_gate`` — record input for a gate, addressed by either identifier
- ``get_gate_draft`` — what is supplied, missing and invalid on one gate
- ``resume_workflow`` — deposit input for a scope with exactly one pending gate
- ``cancel_workflow`` — terminate a scope

**Where the truth lives.** Everything reported here comes from two places that
outlive the process that wrote them: the *state store* (``.functualize/state.json``
— scope status, step records, gate records, walk position) and the *discovery
cache* (graph topology, via ``JobDescriptor.workflow``). Neither requires
importing the module that declared the workflow, so an agent can inspect a
workflow blocked by a run that has long since exited. Only :meth:`resume_gate`
materializes anything, and only because validating input means having the real
Pydantic model rather than a JSON schema of it.

**Resume is replay, not injection.** Depositing input does not restart anything.
It fills the gate's payload slot; the next invocation of the workflow job replays
the walk, finds the gate answered, and continues past it (§D.7). So a successful
deposit reports ``input_accepted`` — not ``resumed`` — because nothing has run
yet, and the caller still has to invoke the job.
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
    StateStore,
    answer_gate,
    deposit_gate_input,
    describe_scope,
    gate_draft,
    list_scopes,
    resolve_gate,
    tool_entries,
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


class GateToolPolicy:
    """Decides whether a job tool may run while a gate is waiting.

    `Gate(name, awaits, tools)` declares what an agent may use while resolving
    that gate, and `tools` is a *permission*: a job tool call arriving while
    the gate waits is refused unless the job is named. Enforcement lives here,
    at the dispatch chokepoint every per-job tool passes through, rather than
    in a helper the tools call voluntarily — a check that a caller can skip by
    not calling it is not a permission.

    **Only per-job tools are governed.** The workflow tools
    (`get_workflow_state`, `resume_gate`, …) do not route through dispatch and
    are therefore never refused. That is deliberate and load-bearing: an agent
    that could not inspect or answer the gate blocking it would have no way
    out of the block at all.

    **Which gate governs.** A tool call carries no scope id, so when several
    scopes wait at once the policy takes the union of their lists — an
    intersection would let two unrelated workflows deadlock each other. A gate
    that declares no tools asks for no restriction, so a single such gate
    lifts the restriction entirely rather than being read as "permit nothing".
    """

    def __init__(self, app: Any, *, store: StateStore | None = None) -> None:
        self._app = app
        self._store = store

    @property
    def store(self) -> StateStore:
        if self._store is None:
            self._store = StateStore.for_project(Path.cwd())
        return self._store

    def permitted(self, tool_name: str) -> bool:
        """True when ``tool_name`` may run right now.

        The requested name is canonicalized first: tools are jobs, jobs are
        addressed canonically, and an agent that asks for `order_history`
        means the `order-history` on the allow-list. Comparing raw strings
        refused a permitted call and told the agent it lacked permission,
        which is a maximally misleading way to fail.
        """
        allowed = self.allowed_tools()
        return allowed is None or _canonical(tool_name) in allowed

    def allowed_tools(self) -> set[str] | None:
        """The permitted job tools, or None when nothing is restricted."""
        declared: list[list[str]] = []
        for scope_id in self.store.scope_ids():
            scope = self.store.get_scope(scope_id)
            if scope is None or scope.get("status") not in _LIVE_STATUSES:
                continue
            for _name, record in _pending_gates(scope):
                entries = tool_entries(record)
                if not entries:
                    return None  # a gate asking for no restriction wins
                declared.append([e["tool"] for e in entries])

        if not declared:
            return None
        return {tool for tools in declared for tool in tools}

    def refusal(self, tool_name: str) -> dict[str, Any]:
        """The error envelope for a refused call."""
        allowed = self.allowed_tools() or set()
        return {
            "error": "tool_not_permitted",
            "message": (
                f"'{tool_name}' is not permitted while a workflow gate is "
                "awaiting input. Resolve the gate with resume_gate, or use "
                "one of the tools it allows."
            ),
            "tool": tool_name,
            "allowed_tools": sorted(allowed),
        }


class WorkflowToolProvider:
    """MCP tools over persisted workflow scopes.

    Args:
        app: The FunctualizeApp, used for the discovery cache and for
            materializing gate models on resume.
        store: State store to read. Defaults to the project store resolved
            from the working directory, the same way the engine resolves it.
    """

    def __init__(self, app: Any, *, store: StateStore | None = None) -> None:
        self._app = app
        self._store = store

    @property
    def store(self) -> StateStore:
        """The state store, resolved from the cwd on first use."""
        if self._store is None:
            self._store = StateStore.for_project(Path.cwd())
        return self._store

    def register_tools(self, mcp: Any) -> None:
        """Register the workflow tools with a FastMCP server instance."""
        mcp.add_tool(self._get_workflow_state)
        mcp.add_tool(self._list_workflows)
        mcp.add_tool(self._answer_gate)
        mcp.add_tool(self._get_gate_draft)
        mcp.add_tool(self._resume_workflow)
        mcp.add_tool(self._call_gate_tool)
        mcp.add_tool(self._cancel_workflow)
        logger.info("WorkflowToolProvider: registered 7 workflow MCP tools")

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
        resolved = resolve_gate(
            self.store, workflow_id, gate, include_answered=reopen
        )
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
        self, workflow_id: str, input: dict[str, Any]
    ) -> dict[str, Any]:
        scope = self.store.get_scope(workflow_id)
        if scope is None:
            return _error("workflow_not_found", f"No workflow scope '{workflow_id}'.")

        pending = [name for name, _ in _pending_gates(scope)]
        if not pending:
            return _error(
                "workflow_not_paused",
                f"Workflow '{workflow_id}' has no gate awaiting input "
                f"(status: {scope.get('status')}).",
            )
        if len(pending) > 1:
            return {
                "error": "ambiguous_gate",
                "message": (
                    f"Workflow '{workflow_id}' has {len(pending)} pending "
                    "gates. Use resume_gate to name one."
                ),
                "pending_gates": pending,
            }

        return self._deposit(workflow_id, pending[0], input)

    _resume_workflow.__name__ = "resume_workflow"
    _resume_workflow.__qualname__ = "resume_workflow"
    _resume_workflow.__doc__ = (
        "Provide input for a workflow that is blocked on exactly one gate. "
        "Equivalent to resume_gate, addressed by scope instead of gate name. "
        "Args: workflow_id — the scope identifier; input — field values."
    )

    @_refuse_unreadable_scopes
    async def _call_gate_tool(
        self, workflow_id: str, tool: str, args: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Run one of a blocked gate's tools, inside that gate's scope."""
        scope = self.store.get_scope(workflow_id)
        if scope is None:
            return _error("workflow_not_found", f"No workflow scope '{workflow_id}'.")

        entry = None
        for _gate_name, record in _pending_gates(scope):
            for candidate in tool_entries(record):
                if _canonical(candidate["tool"]) == _canonical(tool):
                    entry = candidate
        if entry is None:
            return {
                "error": "tool_not_permitted",
                "message": (
                    f"'{tool}' is not offered by any gate awaiting input in "
                    f"workflow '{workflow_id}'."
                ),
                "tool": tool,
                "allowed_tools": sorted(
                    e["tool"]
                    for _n, r in _pending_gates(scope)
                    for e in tool_entries(r)
                ),
            }

        supplied = dict(args or {})
        # A bound argument is refused, never silently overridden: an agent
        # that believes it set a value and did not is worse off than one told
        # no, and it is the difference between a permission and a preference.
        overreach = sorted(set(entry["bound"]) & set(supplied))
        if overreach:
            return {
                "error": "argument_not_permitted",
                "message": (
                    f"{', '.join(overreach)} is fixed by gate policy for "
                    f"'{tool}' and cannot be supplied."
                ),
                "tool": tool,
                "bound": entry["bound"],
            }

        bound_values, failure = self._bound_values(scope, tool)
        if failure is not None:
            return failure

        # From here the canonical name is the one of record: it is the job
        # that actually ran, and an audit trail spelled however the caller
        # happened to type it cannot be grouped or compared.
        tool = _canonical(tool)

        try:
            result = self._app.execute(
                tool, scope_id=workflow_id, **{**bound_values, **supplied}
            )
        except Exception as exc:
            return _error("tool_failed", f"'{tool}' raised {type(exc).__name__}: {exc}")

        self.store.record_tool_call(
            workflow_id,
            {
                "tool": tool,
                "args": supplied,
                "status": getattr(result.status, "value", str(result.status)),
                "return_value": result.return_value,
                "called_at": _now(),
            },
        )
        return {
            "tool": tool,
            "status": getattr(result.status, "value", str(result.status)),
            "return_value": result.return_value,
            "workflow_id": workflow_id,
        }

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
        scope = self.store.get_scope(workflow_id)
        if scope is None:
            return _error("workflow_not_found", f"No workflow scope '{workflow_id}'.")

        status = scope.get("status")
        if status not in _LIVE_STATUSES:
            return _error(
                "workflow_not_active",
                f"Workflow '{workflow_id}' is already {status}.",
            )

        self.store.set_scope_status(workflow_id, "cancelled")
        return {
            "status": "cancelled",
            "workflow_id": workflow_id,
            "message": f"Workflow '{workflow_id}' has been cancelled.",
        }

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

    def _deposit(
        self, scope_id: str, gate: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Validate against the gate's model, then fill its payload slot.

        Delegates to the lifted ``deposit_gate_input`` (D2b): the CLI
        ``func builtin workflow resume`` calls the *same* function, so there is
        one notion of "accept input for a gate" rather than a plugin-local copy.
        """
        return deposit_gate_input(self._app, self.store, scope_id, gate, payload)


def _now() -> str:
    """UTC timestamp for a recorded call."""
    return datetime.now(UTC).isoformat()


def _error(code: str, message: str) -> dict[str, Any]:
    """A flat error envelope — ``error`` is the machine-readable code."""
    return {"error": code, "message": message}
