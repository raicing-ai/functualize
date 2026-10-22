"""Moved builtin command registration for run."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import (
    RUN_STATES,
    _mount,
    _project_substrate,
)

if TYPE_CHECKING:
    import click


def register_run(builtin_app: click.Group) -> None:
    import click

    # --- run (durable-run-layer/T3) ------------------------------------
    #
    # `runs.json` has been written since T2 and read by nothing. These are the
    # read verbs, thin over `app/_run_view.py` — the same projection the MCP
    # tools return, so the two surfaces cannot answer differently.
    #
    # A separate group from `workflow` because they answer different questions:
    # a scope is a workflow's *position* and exists to be resumed, a run is one
    # *execution* and exists to be read afterwards. A workflow that blocked and
    # resumed three times is one scope and four runs.
    run_app = click.Group(
        name="run", help="Read the run log — what executed, and how it ended."
    )

    def _run_store(ctx: Any) -> Any:
        """The store the `builtin run` subcommands read.

        One place, for the reason `_workflow_store` gives: four opinions about
        the same file is how two verbs start disagreeing about it.
        """
        from pathlib import Path

        from functualize.app.utils import RunStore

        substrate = _project_substrate(ctx)
        if substrate is not None:
            return RunStore(substrate)
        return RunStore.for_project(Path.cwd())

    @run_app.command("list")
    @click.option("--job", "job", default=None, help="Only runs of this job.")
    @click.option(
        "--surface",
        "surface",
        default=None,
        help="Only runs started through this door (cli, http, invoke, ...).",
    )
    @click.option(
        "--state",
        "state",
        default=None,
        type=click.Choice(list(RUN_STATES)),
        help="Only runs in this derived state. `abandoned` is a run that never "
        "closed and is not this process — see `run show`.",
    )
    @click.option(
        "--scope", "scope_id", default=None, help="Only runs in this workflow scope."
    )
    @click.option("--limit", type=int, default=20, help="How many rows at most.")
    @click.option(
        "--format",
        "fmt",
        type=click.Choice(["table", "json"]),
        default="table",
        help="Render the runs as a table or JSON.",
    )
    @click.pass_context
    def run_list(
        ctx: click.Context,
        job: str | None,
        surface: str | None,
        state: str | None,
        scope_id: str | None,
        limit: int,
        fmt: str,
    ) -> None:
        """Survey runs, newest first.

        The opposite order from `workflow list`, and deliberately: a scope list
        answers "what is waiting on me", where order is incidental; a run list
        answers "what just happened", where it is the whole question.
        """
        from functualize.app.utils import list_runs

        items = list_runs(
            _run_store(ctx),
            job=job,
            surface=surface,
            state=state,
            scope_id=scope_id,
            limit=limit,
        )
        if fmt == "json":
            import json

            click.echo(json.dumps({"runs": items}, indent=2))
            return
        if not items:
            click.echo("No matching runs.")
            return
        for it in items:
            # A rendering of the shared projection, never a second projection —
            # the moment the one-liner had its own shape, `--format json` and
            # the MCP survey stopped being the same rows.
            took = "-" if it["duration_ms"] is None else f"{it['duration_ms']:.0f}ms"
            click.echo(
                f"{it['run_id']}  {it['job']}  {it['state']}  "
                f"{it['surface'] or '-'}  {took}"
            )

    @run_app.command("show")
    @click.argument("run_id")
    @click.option(
        "--events", is_flag=True, help="Include this run's event log, in seq order."
    )
    @click.option(
        "--tree", is_flag=True, help="Include the runs this run set off, nested."
    )
    @click.option(
        "--format",
        "fmt",
        type=click.Choice(["table", "json"]),
        default="table",
        help="Render the run as text or JSON.",
    )
    @click.pass_context
    def run_show(
        ctx: click.Context, run_id: str, events: bool, tree: bool, fmt: str
    ) -> None:
        """Everything known about one run."""
        import json

        from functualize.app.utils import describe_run, run_events, run_tree

        store = _run_store(ctx)
        payload = run_tree(store, run_id) if tree else describe_run(store, run_id)
        if payload is None:
            click.echo(f"Error: no run '{run_id}'.", err=True)
            raise SystemExit(1)
        if events:
            payload = {**payload, "events": run_events(store, run_id) or []}
        if fmt == "json":
            click.echo(json.dumps(payload, indent=2))
            return
        for key in ("run_id", "job", "state", "surface", "started_at", "ended_at"):
            click.echo(f"{key}: {payload.get(key)}")
        if payload.get("duration_ms") is not None:
            click.echo(f"duration_ms: {payload['duration_ms']:.0f}")
        if payload.get("scope_id"):
            click.echo(f"scope_id: {payload['scope_id']}")
        if payload.get("parent_run_id"):
            click.echo(f"parent_run_id: {payload['parent_run_id']}")
        if events:
            click.echo(f"events: {len(payload.get('events') or [])}")
            for event in payload.get("events") or []:
                click.echo(f"  {event.get('seq')}  {event.get('at')}  {event}")

    _mount(builtin_app, run_app, "run")
