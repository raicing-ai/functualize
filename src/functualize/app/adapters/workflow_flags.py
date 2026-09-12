"""The ``--wf-*`` family: workflow control on the job command itself.

Tier 3 of the three-tier surface. ``func builtin workflow`` is the superset and
MCP matches it verb for verb; these flags are a **strict subset**, not a
separate design.

**The inclusion test.** The job command's one unique piece of knowledge is
*which workflow*. A verb earns a flag here only if the workflow is implied, the
scope is inferable or already in hand, and it is what someone holding this
command actually wants. That is why answer-only, ``--reopen``, incremental
drafts, ``gate-tool``, ``cancel`` and ``purge`` never reach the job: each needs
an explicit target, or serves an actor who does not have this command in hand.

**One module, two injection points.** ``create_job_click_command`` (cold, built
from a live signature) and ``make_lazy_command`` (warm, built from the discovery
cache) both build their options *and* resolve them here. They have diverged
before over exactly this kind of split — ``contributor/reference/pitfalls.md``
§23 records the release where a job that raised exited 0 on warm boot and 1 on
cold — so the mechanism is shared code rather than a comment asking for care.

**Two control paths, one closed set of outcomes.** ``--wf-status`` and
``--wf-show`` must exit **without running the job**, so they cannot be ordinary
kwargs consumed after the engine is reached; they short-circuit at the top of
the wrapper. The rest resolve to a scope id and fall through to ``execute()``.
:func:`resolve_workflow_flags` returns one :class:`WorkflowFlagOutcome` so each
injection point branches on a closed set rather than on flag combinations.

**``--wf-run-id`` may mint a scope; ``--wf-resume`` may not.** That split *is*
the phantom-run fix. ``--scope-id`` did both, and ``WorkflowRunner.__init__``
does ``scope_id or new_scope_id()`` while the walk calls ``ensure_scope`` — so a
typo'd id silently became a blocked run under the typo, which the caller then
could not find.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

import click

__all__ = [
    "WorkflowFlagOutcome",
    "resolve_workflow_flags",
    "workflow_flag_options",
    "workflow_flag_params",
]

#: The kwargs the `--wf-*` options bind to. Popped before the job body sees
#: them, so a config field is never shadowed by a flag the job never declared.
WF_PARAMS: tuple[str, ...] = (
    "wf_resume",
    "wf_input",
    "wf_gate",
    "wf_status",
    "wf_show",
    "wf_retry_epilogue",
    "wf_run_id",
)

#: Sentinel for an optional-value flag that was given without a value —
#: `--wf-resume` alone means "the only advanceable scope", which is a different
#: request from "not asked for" (None).
_OMITTED = "\0wf-omitted"


@dataclass(frozen=True)
class WorkflowFlagOutcome:
    """What the flags resolved to. Exactly one ``kind``.

    - ``run`` — carry ``scope_id`` into ``execute()``; the job runs.
    - ``short_circuit`` — echo ``text`` and exit ``exit_code``; the job never runs.
    - ``error`` — echo ``text`` to stderr and exit ``exit_code``.
    """

    kind: Literal["run", "short_circuit", "error"]
    scope_id: str | None = None
    deposit: tuple[str | None, dict[str, Any]] | None = None
    retry_epilogue: bool = False
    text: str = ""
    exit_code: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


def workflow_flag_options() -> list[click.Option]:
    """The nine flags, in the order they read on ``--help``.

    Added only to a job that declares a ``@workflow``, so a plain ``@job``'s
    help is unchanged.
    """
    return [
        click.Option(
            ["--wf-resume", "wf_resume"],
            is_flag=False,
            flag_value=_OMITTED,
            default=None,
            metavar="[ID]",
            help=(
                "Advance a scope of this workflow (the only advanceable one if "
                "ID is omitted). Walks in this process."
            ),
        ),
        click.Option(
            ["--wf-input", "wf_input"],
            default=None,
            metavar="JSON",
            help=("Gate input for --wf-resume: recorded, then the walk advances."),
        ),
        click.Option(
            ["--wf-gate", "wf_gate"],
            default=None,
            metavar="NAME",
            help="Which pending gate --wf-input answers, when there are several.",
        ),
        click.Option(
            ["--wf-status", "wf_status"],
            is_flag=True,
            default=False,
            help="List this workflow's scopes, then exit 0.",
        ),
        click.Option(
            ["--wf-show", "wf_show"],
            is_flag=False,
            flag_value=_OMITTED,
            default=None,
            metavar="[ID]",
            help="Full projection of one scope, then exit 0.",
        ),
        click.Option(
            ["--wf-retry-epilogue", "wf_retry_epilogue"],
            is_flag=True,
            default=False,
            help="With --wf-resume: clear a stalled epilogue and re-fire it.",
        ),
        click.Option(
            ["--wf-run-id", "wf_run_id"],
            default=None,
            metavar="ID",
            help="Start under a caller-chosen scope id (idempotent start).",
        ),
    ]


def workflow_flag_params(params: list[Any]) -> list[Any]:
    """``params`` with the workflow flags appended."""
    return [*params, *workflow_flag_options()]


def resolve_workflow_flags(
    app: Any, workflow_name: str, kwargs: dict[str, Any]
) -> WorkflowFlagOutcome:
    """Consume the ``--wf-*`` kwargs and decide what happens.

    **Pops every flag from ``kwargs``**, whether or not it was given: they are
    options of the *command*, not parameters of the job, and one left behind
    reaches the job body as an argument it never declared.

    Args:
        app: The booted app — the projection needs it for graph topology.
        workflow_name: Which workflow this command runs. The single piece of
            knowledge that earns this surface its existence.
        kwargs: The click callback's kwargs, mutated in place.
    """
    flags = {name: kwargs.pop(name, None) for name in WF_PARAMS}

    if flags["wf_status"]:
        return _survey(app, workflow_name)
    if flags["wf_show"] is not None:
        return _show(app, workflow_name, _value(flags["wf_show"]))

    resume = flags["wf_resume"]
    run_id = flags["wf_run_id"]

    if resume is not None and run_id is not None:
        return WorkflowFlagOutcome(
            kind="error",
            text=(
                "--wf-resume advances an existing scope and --wf-run-id starts "
                "a new one under a chosen id. Pass one."
            ),
            exit_code=_usage(),
        )

    deposit = _deposit(flags)
    if isinstance(deposit, WorkflowFlagOutcome):
        return deposit

    if resume is None and deposit is not None:
        return WorkflowFlagOutcome(
            kind="error",
            text="--wf-input needs --wf-resume: it answers the gate the walk "
            "is about to pass.",
            exit_code=_usage(),
        )

    if flags["wf_retry_epilogue"] and resume is None:
        return WorkflowFlagOutcome(
            kind="error",
            text="--wf-retry-epilogue needs --wf-resume.",
            exit_code=_usage(),
        )

    if resume is not None:
        return _resume_target(app, workflow_name, _value(resume), deposit, flags)

    # `--wf-run-id` may mint; a plain invocation mints its own. Both start.
    return WorkflowFlagOutcome(kind="run", scope_id=run_id)


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------


def _usage() -> int:
    from functualize._types.exit_codes import ExitCode

    return int(ExitCode.USAGE)


def _value(raw: Any) -> str | None:
    """An optional-value flag's value, or None when it was given bare."""
    return None if raw == _OMITTED else raw


def _store(app: Any) -> Any:
    """The scope records, on the app's substrate.

    Resolved through the engine rather than from the cwd. This was the site
    `store-substrate`/T7 caught: with a database installed, `--wf-resume`
    looked for the scope in `.functualize/scopes.json` while the walk that
    created it had written to the database, so a perfectly valid id came back
    as "No workflow scope".
    """
    from functualize.app.utils import ScopeStore

    return ScopeStore(app.execution_engine.substrate)


def _deposit(flags: dict[str, Any]) -> tuple[str | None, dict[str, Any]] | None | Any:
    """``(gate, values)`` from ``--wf-input``/``--wf-gate``, or an error."""
    raw = flags["wf_input"]
    if raw is None:
        if flags["wf_gate"] is not None:
            return WorkflowFlagOutcome(
                kind="error",
                text="--wf-gate names which gate --wf-input answers; pass "
                "--wf-input too.",
                exit_code=_usage(),
            )
        return None
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        return WorkflowFlagOutcome(
            kind="error",
            text=f"--wf-input is not valid JSON: {exc}",
            exit_code=_usage(),
        )
    if not isinstance(values, dict):
        return WorkflowFlagOutcome(
            kind="error",
            text="--wf-input must be a JSON object of field values.",
            exit_code=_usage(),
        )
    return flags["wf_gate"], values


def _survey(app: Any, workflow_name: str) -> WorkflowFlagOutcome:
    """``--wf-status`` — this workflow's scopes, then exit 0."""
    from functualize.app.utils import list_scopes

    rows = list_scopes(app, _store(app), workflow_name=workflow_name)
    if not rows:
        return WorkflowFlagOutcome(
            kind="short_circuit", text=f"No active scopes of '{workflow_name}'."
        )
    lines = [
        f"{row['workflow_id']}  {row['state']}  gates: "
        + (", ".join(g["gate"] for g in row["pending_gates"]) or "-")
        for row in rows
    ]
    return WorkflowFlagOutcome(kind="short_circuit", text="\n".join(lines))


def _show(app: Any, workflow_name: str, scope_id: str | None) -> WorkflowFlagOutcome:
    """``--wf-show`` — the **same** full projection ``builtin workflow show``
    renders. The flag saves naming the workflow; it does not reduce the output.
    A reduced form would recreate the split this feature exists to close, where
    one surface knew the graph and the other printed five fields."""
    from functualize.app.utils import describe_scope

    store = _store(app)
    if scope_id is None:
        target = _sole_scope(app, store, workflow_name)
        if isinstance(target, WorkflowFlagOutcome):
            return target
        scope_id = target

    view = describe_scope(app, store, scope_id)
    if view is None:
        return WorkflowFlagOutcome(
            kind="error",
            text=f"No workflow scope '{scope_id}'.",
            exit_code=1,
        )
    return WorkflowFlagOutcome(
        kind="short_circuit", text=json.dumps(view, indent=2), extra={"view": view}
    )


def _sole_scope(app: Any, store: Any, workflow_name: str) -> str | Any:
    """The one advanceable scope of this workflow, or an outcome explaining why
    there is not exactly one.

    **Ambiguity never guesses.** Never "newest wins": ``blocked_at`` resets on
    every re-block, so recency is not computable even if it were wanted.
    """
    from functualize.app.utils import advanceable_scopes

    candidates = advanceable_scopes(store, workflow_name)
    if not candidates:
        return WorkflowFlagOutcome(
            kind="error",
            text=(
                f"No scope of '{workflow_name}' is waiting. "
                "Run it with --wf-status to see its scopes."
            ),
            exit_code=1,
        )
    if len(candidates) > 1:
        listing = "\n".join(f"  {c}" for c in candidates)
        return WorkflowFlagOutcome(
            kind="error",
            text=(
                f"{len(candidates)} scopes of '{workflow_name}' could be "
                f"advanced. Name one:\n{listing}"
            ),
            exit_code=_usage(),
        )
    return candidates[0]


def _resume_target(
    app: Any,
    workflow_name: str,
    scope_id: str | None,
    deposit: tuple[str | None, dict[str, Any]] | None,
    flags: dict[str, Any],
) -> WorkflowFlagOutcome:
    """Resolve ``--wf-resume`` to a scope that **already exists**.

    An unknown id is an error, not a new run. ``--scope-id`` silently started a
    fresh run under whatever was typed, so a typo produced a phantom scope the
    caller could not find and the real run stayed blocked.
    """
    store = _store(app)
    if scope_id is None:
        target = _sole_scope(app, store, workflow_name)
        if isinstance(target, WorkflowFlagOutcome):
            return target
        scope_id = target
    elif store.get_scope(scope_id) is None:
        return WorkflowFlagOutcome(
            kind="error",
            text=(
                f"No workflow scope '{scope_id}'. Nothing was created — pass "
                "--wf-run-id to start a run under a chosen id."
            ),
            exit_code=1,
        )

    return WorkflowFlagOutcome(
        kind="run",
        scope_id=scope_id,
        deposit=deposit,
        retry_epilogue=bool(flags["wf_retry_epilogue"]),
    )


def apply_workflow_flags(
    app: Any, workflow_name: str, kwargs: dict[str, Any]
) -> str | None:
    """Resolve the flags and act on the two non-``run`` outcomes.

    Both injection points call exactly this, so the short-circuit and error
    paths cannot drift between cold and warm boot. Returns the ``scope_id`` to
    pass to ``execute()``.

    Raises:
        SystemExit: for a short-circuit (``--wf-status``/``--wf-show``) or an
            error. The job does not run in either case.
    """
    outcome = resolve_workflow_flags(app, workflow_name, kwargs)

    if outcome.kind == "short_circuit":
        click.echo(outcome.text)
        raise SystemExit(outcome.exit_code)
    if outcome.kind == "error":
        click.echo(f"Error: {outcome.text}", err=True)
        raise SystemExit(outcome.exit_code)

    if outcome.deposit is not None and outcome.scope_id is not None:
        _record(app, outcome)
    if outcome.retry_epilogue and outcome.scope_id is not None:
        _store(app).record_epilogue(outcome.scope_id, None)
    return outcome.scope_id


def _record(app: Any, outcome: WorkflowFlagOutcome) -> None:
    """Answer the gate ``--wf-input`` names, before the walk starts.

    Through the same :func:`answer_gate` the other two surfaces use, so a fused
    answer and a standalone one cannot validate differently. A refusal exits
    here rather than letting the walk run into the gate it was meant to open.
    """
    from functualize.app.utils import answer_gate, resolve_gate

    gate, values = outcome.deposit  # type: ignore[misc]
    store = _store(app)
    resolved = resolve_gate(store, outcome.scope_id, gate)
    if isinstance(resolved, dict):
        click.echo(f"Error: {resolved['message']}", err=True)
        raise SystemExit(_usage() if "ambiguous" in resolved["error"] else 1)

    scope_id, gate_name = resolved
    result = answer_gate(app, store, scope_id, gate_name, values)
    if "error" in result:
        click.echo(f"Error: {result['message']}", err=True)
        raise SystemExit(1)
    if result.get("status") != "answered":
        # An incomplete draft is not a failure, but walking on would return the
        # caller to exactly where they started with no explanation.
        click.echo(result["message"])
        raise SystemExit(_usage())
