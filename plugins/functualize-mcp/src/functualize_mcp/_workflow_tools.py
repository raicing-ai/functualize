"""MCP workflow tools — discover and advance blocked workflow scopes.

These tools let an external agent drive a `@workflow` across turns:

- ``get_workflow_state`` — one scope's topology, progress, and pending gates
- ``list_active_workflows`` — every scope that is still runnable
- ``resume_gate`` — deposit input for a gate, addressed by gate name
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

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize.app.utils import (
    StateStore,
    deposit_gate_input,
)
from functualize.app.utils import (
    pending_gates as _pending_gates,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["GateToolPolicy", "WorkflowToolProvider"]

logger = logging.getLogger(__name__)

#: Discovery records parameter types as strings; MCP wants JSON-schema types.
_JSON_TYPES = {
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "list": "array",
    "dict": "object",
    "str": "string",
}

#: Scope statuses that can still accept input or make progress.
_LIVE_STATUSES = frozenset({"running", "blocked"})


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
                entries = _tool_entries(record)
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
        mcp.add_tool(self._list_active_workflows)
        mcp.add_tool(self._resume_gate)
        mcp.add_tool(self._resume_workflow)
        mcp.add_tool(self._call_gate_tool)
        mcp.add_tool(self._cancel_workflow)
        logger.info("WorkflowToolProvider: registered 6 workflow MCP tools")

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    async def _get_workflow_state(self, workflow_id: str) -> dict[str, Any]:
        scope = self.store.get_scope(workflow_id)
        if scope is None:
            return _error("workflow_not_found", f"No workflow scope '{workflow_id}'.")
        return self._describe(workflow_id, scope)

    _get_workflow_state.__name__ = "get_workflow_state"
    _get_workflow_state.__qualname__ = "get_workflow_state"
    _get_workflow_state.__doc__ = (
        "Inspect one workflow scope: its graph, which steps have completed, "
        "where the walk stopped, and any gates awaiting input. "
        "Args: workflow_id — the scope identifier."
    )

    async def _list_active_workflows(self) -> dict[str, Any]:
        workflows = [
            self._describe(scope_id, scope)
            for scope_id, scope in self._scopes()
            if scope.get("status") in _LIVE_STATUSES
        ]
        return {"workflows": workflows}

    _list_active_workflows.__name__ = "list_active_workflows"
    _list_active_workflows.__qualname__ = "list_active_workflows"
    _list_active_workflows.__doc__ = (
        "List every workflow scope still running or blocked, with its "
        "position and pending gates. Completed, failed, and cancelled "
        "scopes are omitted."
    )

    async def _resume_gate(self, gate: str, input: dict[str, Any]) -> dict[str, Any]:
        matches = [
            scope_id
            for scope_id, scope in self._scopes()
            if scope.get("status") in _LIVE_STATUSES
            and any(name == gate for name, _ in _pending_gates(scope))
        ]

        if not matches:
            return {
                "error": "gate_not_found",
                "message": f"No blocked workflow is awaiting gate '{gate}'.",
                "pending_gates": self._all_pending_gates(),
            }
        if len(matches) > 1:
            return {
                "error": "ambiguous_gate",
                "message": (
                    f"Gate '{gate}' is pending in {len(matches)} scopes. "
                    "Use resume_workflow with a workflow_id to disambiguate."
                ),
                "workflow_ids": matches,
            }

        return self._deposit(matches[0], gate, input)

    _resume_gate.__name__ = "resume_gate"
    _resume_gate.__qualname__ = "resume_gate"
    _resume_gate.__doc__ = (
        "Provide input for a gate, addressed by gate name. Input is validated "
        "against the gate's model and nothing is stored if it fails. Accepting "
        "input does not run the workflow — invoke the workflow job to continue "
        "it. Args: gate — the gate name; input — field values."
    )

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

    async def _call_gate_tool(
        self, workflow_id: str, tool: str, args: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Run one of a blocked gate's tools, inside that gate's scope."""
        scope = self.store.get_scope(workflow_id)
        if scope is None:
            return _error("workflow_not_found", f"No workflow scope '{workflow_id}'.")

        entry = None
        for _gate_name, record in _pending_gates(scope):
            for candidate in _tool_entries(record):
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
                    for e in _tool_entries(r)
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

    def _describe(self, scope_id: str, scope: dict[str, Any]) -> dict[str, Any]:
        """Full state for one scope — topology from the cache, progress from
        the store."""
        workflow_name = scope.get("workflow")
        topology = self._topology(workflow_name)
        steps = scope.get("steps", {})

        return {
            "workflow_id": scope_id,
            "workflow": workflow_name,
            "status": scope.get("status"),
            "steps": topology["steps"],
            "edges": topology["edges"],
            "current_position": scope.get("position"),
            # Nodes, not steps: an answered gate is recorded here too, and
            # calling that a "completed step" would contradict `steps`, where
            # gates are a distinct kind.
            #
            # Full records, not just names. The store has held each step's
            # return value and resolved inputs all along; publishing only the
            # names meant an agent could see *that* a step ran and never what
            # it produced — so it had to be told the run's own results out of
            # band, which is the workflow asking the agent to be its plumbing.
            "results": {
                _job_of(key): {
                    "status": record.get("status"),
                    "return_value": record.get("return_value"),
                    "inputs": record.get("inputs", {}),
                    "completed_at": record.get("completed_at"),
                }
                for key, record in steps.items()
                if isinstance(record, dict)
            },
            "branches": dict(scope.get("branches", {})),
            "pending_gates": [
                self._gate_summary(scope_id, scope, name, record)
                for name, record in _pending_gates(scope)
            ],
        }

    def _topology(self, workflow_name: Any) -> dict[str, Any]:
        """The declared graph — cached shape first, live declaration as fallback.

        The cached ``descriptor.workflow`` is written only by directory
        discovery, so a workflow declared inside a **plugin** (or via
        ``register_dynamic_job``) has ``.workflow is None`` and used to report an
        empty graph over MCP — an agent could advance a workflow it could not
        see. When the cached shape is absent, fall back to the live declaration
        on ``descriptor.function``; it is origin-agnostic and already in hand.

        Still empty when the job is gone entirely — a scope outlives the
        declaration that made it, and a stale scope should report its progress
        rather than raise. The fallback also returns empty (never raises) for a
        job that has no workflow at all.
        """
        empty: dict[str, Any] = {"steps": [], "edges": []}
        if not isinstance(workflow_name, str):
            return empty
        descriptor = self._app.get_job(workflow_name)
        if descriptor is None:
            return empty
        shape = getattr(descriptor, "workflow", None)
        if shape is None:
            shape = self._live_workflow_shape(descriptor)
        return shape.to_dict() if shape is not None else empty

    def _live_workflow_shape(self, descriptor: Any) -> Any:
        """Project the workflow graph from the descriptor's live function.

        Covers the provider-built case the discovery cache cannot: reads
        ``function.__functualize_workflow__`` directly (via the same projection
        discovery uses, ``workflow_shape_of``) rather than the cached field.
        Returns None for a descriptor with no concrete function or no workflow.
        """
        from functualize._types.workflow import workflow_shape_of

        func = getattr(descriptor, "function", None)
        if func is None:
            return None
        try:
            return workflow_shape_of(func)
        except Exception:  # pragma: no cover - defensive; projection is pure
            return None

    def _gate_summary(
        self,
        scope_id: str,
        scope: dict[str, Any],
        name: str,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        """What an agent needs to answer one gate."""
        schema = record.get("input_schema") or {}
        return {
            "gate": name,
            "model": record.get("model"),
            "input_schema": schema,
            "unresolved_fields": list(schema.get("required", [])),
            "tools": self._tool_summaries(record),
            "blocked_at": record.get("blocked_at"),
            "workflow_context": {
                "workflow_id": scope_id,
                "workflow": scope.get("workflow"),
                "position": scope.get("position"),
            },
        }

    def _tool_summaries(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        """What an agent needs to *call* each offered tool, not just name it.

        Publishing the name alone costs the agent a `get_job_schema` round
        trip per tool. Publishing the schema **minus the gate's bound
        parameters** is also what makes narrowing real: a pinned argument is
        not in the agent's vocabulary, so the forbidden call cannot be
        expressed rather than merely being refused.

        Schemas come from the discovery cache, so this stays import-free.
        """
        summaries: list[dict[str, Any]] = []
        for entry in _tool_entries(record):
            name = entry["tool"]
            bound = entry["bound"]
            descriptor = self._app.get_job(name)
            summary: dict[str, Any] = {
                "tool": name,
                "description": (getattr(descriptor, "docstring", None) or "").strip(),
                "bound": bound,
            }
            schema = _job_input_schema(descriptor)
            if schema is not None:
                summary["input_schema"] = _without(schema, bound)
            if descriptor is None:
                # Listed but not discoverable: say so rather than publishing a
                # tool the agent will only fail to call.
                summary["unavailable"] = f"No registered job named '{name}'."
            summaries.append(summary)
        return summaries

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


def _job_input_schema(descriptor: Any) -> dict[str, Any] | None:
    """A JSON-schema view of a job's arguments, from the discovery cache.

    Reads ``config_fields`` and ``parameters`` both: discovery files a job's
    arguments under whichever fits how they were declared (a Pydantic config
    class versus plain annotated parameters), and a tool schema that silently
    published nothing for one of those shapes would be worse than no schema —
    the agent would believe the tool takes no arguments.
    """
    if descriptor is None:
        return None
    properties: dict[str, Any] = {}
    required: list[str] = []
    fields = list(getattr(descriptor, "config_fields", None) or [])
    fields += list(getattr(descriptor, "parameters", None) or [])
    for param in fields:
        name = getattr(param, "name", None)
        if not isinstance(name, str) or name in properties:
            continue
        entry: dict[str, Any] = {
            "type": _JSON_TYPES.get(
                str(getattr(param, "type_annotation", "")), "string"
            )
        }
        description = getattr(param, "description", "") or ""
        if description:
            entry["description"] = description
        default = getattr(param, "default", None)
        if default is not None:
            entry["default"] = default
        choices = getattr(param, "choices", None)
        if choices:
            entry["enum"] = list(choices)
        properties[name] = entry
        if getattr(param, "required", False):
            required.append(name)
    return {"type": "object", "properties": properties, "required": required}


def _without(schema: dict[str, Any], bound: list[str]) -> dict[str, Any]:
    """The schema with ``bound`` parameters removed, root and required."""
    if not bound:
        return schema
    hidden = set(bound)
    properties = {
        key: value
        for key, value in (schema.get("properties") or {}).items()
        if key not in hidden
    }
    required = [key for key in (schema.get("required") or []) if key not in hidden]
    return {**schema, "properties": properties, "required": required}


def _tool_entries(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize a gate record's persisted ``tools`` to entry dicts.

    Tolerates the pre-`Tool` shape (a bare list of names) so a scope blocked
    by an older run still reports and enforces sensibly rather than crashing
    or silently granting everything.
    """
    entries: list[dict[str, Any]] = []
    for raw in record.get("tools") or []:
        if isinstance(raw, str):
            entries.append({"tool": raw, "bound": []})
        elif isinstance(raw, dict) and isinstance(raw.get("tool"), str):
            bound = raw.get("bound") or []
            entries.append(
                {"tool": raw["tool"], "bound": [b for b in bound if isinstance(b, str)]}
            )
    return entries


def _job_of(step_key: str) -> str:
    """Job name out of a ``<job_name>::<args_hash>`` step key."""
    return step_key.split("::", 1)[0]


def _now() -> str:
    """UTC timestamp for a recorded call."""
    return datetime.now(UTC).isoformat()


def _error(code: str, message: str) -> dict[str, Any]:
    """A flat error envelope — ``error`` is the machine-readable code."""
    return {"error": code, "message": message}
