"""Moved builtin command registration for workflow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import (
    WORKFLOW_STATES,
    ExitCode,
    _mount,
    contextlib,
)

if TYPE_CHECKING:
    import click


def register_workflow(builtin_app: click.Group) -> None:
    import click

    # --- Workflow sub-group (D2b: MCP↔CLI parity over the state store) ---
    # These mirror the MCP workflow tools. `list`/`state`/`cancel` read the
    # state store directly (public, no boot); `resume` answers gate input
    # through the same lifted `resume_scope` path as the MCP tool, so there
    # is one notion of "accept input for a gate".
    #
    # `--format` is domain-aware and command-owned: `list`/`state` know their
    # items are workflow scopes, so `json` emits structured scope objects — a
    # different concern from the global `--output`, which only serializes the
    # dispatch layer's return value.
    workflow_app = click.Group(
        name="workflow", help="Inspect and resume persisted workflow scopes."
    )

    #: One error code to exit code table. Both `builtin workflow` and the MCP
    #: tools use the same codes (`contracts.md` §7); only the CLI needs to turn
    #: them into exits, and doing it per-command is how two verbs end up
    #: disagreeing about what "ambiguous" is worth.
    _workflow_exits = {
        "workflow_not_found": 1,
        "workflow_held": 1,
        "gate_not_found": 1,
        "gate_not_answered": 1,
        "validation_error": 1,
        "gate_unresolvable": 1,
        "no_advanceable_scope": 1,
        "ambiguous_gate": int(ExitCode.USAGE),
        "ambiguous_scope": int(ExitCode.USAGE),
        "scope_cancelled": int(ExitCode.USAGE),
        "gate_already_answered": int(ExitCode.USAGE),
        "gate_already_consumed": int(ExitCode.USAGE),
        "tool_not_permitted": int(ExitCode.USAGE),
        "argument_not_permitted": int(ExitCode.USAGE),
        # The two refusals a relational store gives the answer verbs: it
        # keeps drafts only as submissions, and has no step deletion.
        "draft_requires_commit": int(ExitCode.USAGE),
        "epilogue_retry_unsupported": int(ExitCode.USAGE),
    }

    def _workflow_store(ctx: Any) -> Any:
        """The legacy scope helper for verbs outside the operator slice."""
        from functualize.app.utils import ScopeStore

        return ScopeStore(_workflow_app_ref(ctx).substrate)

    def _workflow_operator_store(ctx: Any) -> Any:
        """The selected store for list, show, answer, resume, cancel and reclaim."""
        from functualize.app.utils import selected_workflow_store

        return selected_workflow_store(_workflow_app_ref(ctx))

    @contextlib.contextmanager
    def _workflow_refusal() -> Any:
        """Exit rather than a traceback on the two refusals that raise.

        An unreadable scope store exits 2; an unknown gate reference exits 1 —
        the code `gate_not_found` already maps to.
        """
        from functualize.app.utils import GateNotFoundError, ScopeStoreUnreadableError

        try:
            yield
        except ScopeStoreUnreadableError as exc:
            click.echo(f"Error: {exc}", err=True)
            raise SystemExit(ExitCode.USAGE) from exc
        except GateNotFoundError as exc:
            click.echo(f"Error: {exc}", err=True)
            raise SystemExit(1) from exc

    def _render_walk_event(event: dict[str, Any]) -> str:
        """One walk event as a line.

        Renders the event's own fields and nothing else — no lookup of the
        scope to fill in what the event did not say. An event that carries no
        node is a walk-level one, and printing it without a node is the honest
        rendering; going to find one would be the reconstruction AC-11 rules
        out, arrived at by the back door.
        """
        payload = event.get("payload") or {}
        name = str(event.get("type") or event.get("event", "")).removeprefix(
            "workflow."
        )
        node = payload.get("node") or ""
        outcome = payload.get("outcome") or ""
        iteration = payload.get("iteration")
        parts = [f"{int(event.get('seq', 0)):>4}", f"{name:<10}"]
        if node:
            parts.append(str(node))
        if iteration:
            parts.append(f"(pass {int(iteration) + 1})")
        if outcome:
            parts.append(f"-> {outcome}")
        return "  ".join(parts)

    def _render_scope(detail: dict[str, Any]) -> None:
        """One scope as text — the same projection `--format json` emits.

        The text form summarizes; it does not *reduce*. Anything omitted here
        is reachable with `--format json`, and nothing is computed differently.
        """
        click.echo(f"Workflow: {detail['workflow']}")
        click.echo(f"State:    {detail['state']}  (status: {detail['status']})")
        click.echo(f"Position: {detail['current_position']}")

        results = detail.get("results") or {}
        if results:
            click.echo("Steps:")
            for name, record in results.items():
                click.echo(
                    f"  {name}: {record.get('status')} -> {record.get('return_value')!r}"
                )

        # Always printed, `-` when empty: an absent line cannot tell "nothing
        # was recorded" from "nothing was read".
        for label, key in (
            ("Branches", "branches"),
            ("Failure routes", "failure_routes"),
        ):
            entries = detail.get(key) or {}
            listed = ", ".join(f"{src} -> {tgt}" for src, tgt in entries.items())
            click.echo(f"{label}: {listed or '-'}")

        gates = detail.get("pending_gates") or []
        if not gates:
            click.echo("Pending gates: -")
        else:
            click.echo("Pending gates:")
            for gate in gates:
                missing = ", ".join(gate.get("unresolved_fields") or []) or "-"
                click.echo(f"  {gate['gate']} ({gate.get('model')}) needs: {missing}")
                draft = gate.get("draft")
                if draft:
                    click.echo(f"    draft: {draft}")
                for tool in gate.get("tools") or []:
                    bound = ", ".join(tool.get("bound") or []) or "-"
                    click.echo(f"    tool {tool['tool']} (fixed: {bound})")

        epilogue = detail.get("epilogue")
        if epilogue:
            click.echo(f"Epilogue: {epilogue.get('status')}")

    def _workflow_app_ref(ctx: click.Context) -> Any:
        """The booted app, which the projection needs for graph topology.

        `list`/`show` read the store, but the *graph* comes from the discovery
        cache (or the live declaration as a fallback), and both are reached
        through the app. That is the only reason these verbs touch it.
        """
        obj = ctx.find_root().obj
        if obj is None or "app" not in obj:
            click.echo("Error: No app context available.", err=True)
            raise SystemExit(1)
        return obj["app"]

    @workflow_app.command("list")
    @click.option(
        "--workflow", "workflow_name", default=None, help="Only runs of this workflow."
    )
    @click.option(
        "--state",
        "state",
        default=None,
        type=click.Choice(list(WORKFLOW_STATES)),
        help="Only runs in this derived state. Naming one widens the "
        "search to finished runs too.",
    )
    @click.option(
        "--blocked-on",
        "blocked_on",
        default=None,
        help="Only runs waiting at this gate.",
    )
    @click.option(
        "--format",
        "fmt",
        type=click.Choice(["table", "json"]),
        default="table",
        help="Render the workflow scopes as a table or JSON.",
    )
    @click.pass_context
    def workflow_list(
        ctx: click.Context,
        workflow_name: str | None,
        state: str | None,
        blocked_on: str | None,
        fmt: str,
    ) -> None:
        """Survey workflow scopes.

        With no filters, lists the runs that are still running or blocked.
        Naming --state widens the search to finished runs, because asking for
        `completed` and receiving nothing would be a silently empty answer to a
        well-formed question.
        """
        from functualize.app.utils import list_scopes

        app = _workflow_app_ref(ctx)
        store = _workflow_operator_store(ctx)
        with _workflow_refusal():
            items = list_scopes(
                app,
                store,
                workflow_name=workflow_name,
                state=state,
                blocked_on=blocked_on,
            )
        if fmt == "json":
            import json

            click.echo(json.dumps({"workflows": items}, indent=2))
            return
        if not items:
            click.echo("No matching workflows.")
            return
        for it in items:
            # A one-line summary is a *rendering* of the shared projection, not
            # a second projection. The moment it had its own shape, `--format
            # json` and the MCP survey stopped being the same rows.
            gates = ", ".join(g["gate"] for g in it["pending_gates"]) or "-"
            click.echo(
                f"{it['workflow_id']}  {it['workflow']}  {it['state']}  gates: {gates}"
            )

    @workflow_app.command("show")
    @click.argument("workflow_id")
    @click.option(
        "--format",
        "fmt",
        type=click.Choice(["table", "json"]),
        default="table",
        help="Render the scope as a table or JSON.",
    )
    @click.pass_context
    def workflow_show(ctx: click.Context, workflow_id: str, fmt: str) -> None:
        """Show one workflow scope in full.

        Replaces `state`, which emitted five fields — id, workflow, status,
        position and gate names — over records that had held the graph, each
        step's return value and resolved inputs, and every gate's schema all
        along. Same argument, strictly more output, and `--format json` now
        returns exactly what the MCP `get_workflow_state` tool returns.
        """
        from functualize.app.utils import describe_scope

        app = _workflow_app_ref(ctx)
        with _workflow_refusal():
            detail = describe_scope(app, _workflow_operator_store(ctx), workflow_id)
        if detail is None:
            click.echo(f"Error: no workflow scope '{workflow_id}'.", err=True)
            raise SystemExit(1)
        if fmt == "json":
            import json

            click.echo(json.dumps(detail, indent=2))
            return
        _render_scope(detail)

    def _parse_set(pairs: tuple[str, ...]) -> dict[str, Any]:
        """``--set k=v`` pairs into a dict, values JSON-typed.

        JSON rather than strings: a gate model with an ``int`` or a ``bool``
        field would otherwise reject every value the flag could express, and
        quoting is the caller's existing habit from ``--input``. A bare word
        that is not valid JSON is kept as a string, because ``--set env=prod``
        is the common case and demanding ``env='"prod"'`` for it would be a
        tax on the majority to serve the minority.
        """
        import json

        out: dict[str, Any] = {}
        for pair in pairs:
            key, sep, raw = pair.partition("=")
            if not sep:
                click.echo(f"Error: --set expects KEY=VALUE, got '{pair}'.", err=True)
                raise SystemExit(ExitCode.USAGE)
            try:
                out[key] = json.loads(raw)
            except json.JSONDecodeError:
                out[key] = raw
        return out

    @workflow_app.command("answer")
    @click.argument("workflow_id")
    @click.argument("gate")
    @click.option(
        "--input",
        "input_json",
        default=None,
        help="Merge a whole JSON object into the draft.",
    )
    @click.option(
        "--set",
        "set_pairs",
        multiple=True,
        metavar="KEY=VALUE",
        help="Merge one field into the draft (repeatable).",
    )
    @click.option(
        "--unset",
        "unset_keys",
        multiple=True,
        metavar="KEY",
        help="Remove a field from the draft (repeatable).",
    )
    @click.option("--clear", is_flag=True, help="Discard the draft entirely.")
    @click.option(
        "--replace",
        is_flag=True,
        help="With --input: replace the draft rather than merging.",
    )
    @click.option(
        "--show",
        "show_only",
        is_flag=True,
        help="Print the draft and what is still missing; change nothing.",
    )
    @click.option(
        "--commit/--no-commit",
        default=True,
        help="Validate and answer when the draft is complete (default: on).",
    )
    @click.option(
        "--reopen",
        is_flag=True,
        help="Move an answered payload back into the draft to correct it.",
    )
    @click.option(
        "--format",
        "fmt",
        type=click.Choice(["table", "json"]),
        default="table",
        help="Render the result as a table or JSON.",
    )
    @click.pass_context
    def workflow_answer(
        ctx: click.Context,
        workflow_id: str,
        gate: str,
        input_json: str | None,
        set_pairs: tuple[str, ...],
        unset_keys: tuple[str, ...],
        clear: bool,
        replace: bool,
        show_only: bool,
        commit: bool,
        reopen: bool,
        fmt: str,
    ) -> None:
        """Record input for a gate. Never runs anything.

        `answer` records; `resume` advances. One meaning each, on every surface.

        A field at a time, or all at once — the draft accumulates until it
        validates whole, and only then is the gate answered. So two actors can
        fill different fields of the same gate, and neither has to hold the
        whole answer.
        """
        import json

        from functualize.app.utils import answer_gate, gate_draft

        app = _workflow_app_ref(ctx)
        # The selected store: the relational port when one is configured, so
        # the answer lands where the walk that blocked reads it.
        store = _workflow_operator_store(ctx)

        values = _parse_set(set_pairs)
        if input_json is not None:
            try:
                values = {**json.loads(input_json), **values}
            except json.JSONDecodeError as exc:
                click.echo(f"Error: --input is not valid JSON: {exc}", err=True)
                raise SystemExit(ExitCode.USAGE) from exc

        with _workflow_refusal():
            if show_only:
                result = gate_draft(app, store, workflow_id, gate)
            else:
                result = answer_gate(
                    app,
                    store,
                    workflow_id,
                    gate,
                    values,
                    mode="replace" if replace else "merge",
                    unset=list(unset_keys),
                    clear=clear,
                    commit=commit,
                    reopen=reopen,
                    source="cli",
                )

        if fmt == "json":
            click.echo(json.dumps(result, indent=2))
        if "error" in result:
            if fmt != "json":
                click.echo(f"Error: {result['message']}", err=True)
            raise SystemExit(_workflow_exits.get(result["error"], 1))
        if fmt == "json":
            return
        if show_only:
            _render_draft(result)
            return
        click.echo(result["message"])

    def _render_draft(report: dict[str, Any]) -> None:
        """The draft, and — the part that makes it usable — what is missing."""
        click.echo(f"Gate:     {report['gate']} ({report['model']})")
        click.echo(f"Draft:    {report['draft'] or '-'}")
        click.echo(f"Complete: {report['complete']}")
        for entry in report["missing"]:
            detail = f" — {entry['description']}" if entry.get("description") else ""
            click.echo(
                f"  missing: {entry['field']} ({entry.get('type') or '?'}){detail}"
            )
        for entry in report["invalid"]:
            click.echo(f"  invalid: {entry['field']} — {entry['message']}")

    @workflow_app.command("resume")
    @click.argument("workflow_id")
    @click.option(
        "--input",
        "input_json",
        default=None,
        help="Gate input to record before advancing.",
    )
    @click.option(
        "--gate",
        "gate",
        default=None,
        help="Which pending gate --input answers, when several.",
    )
    @click.option(
        "--retry-epilogue",
        is_flag=True,
        help="Clear a stalled epilogue so the body re-runs.",
    )
    @click.option(
        "--format",
        "fmt",
        type=click.Choice(["table", "json"]),
        default="table",
        help="Render the result as a table or JSON.",
    )
    @click.pass_context
    def workflow_resume(
        ctx: click.Context,
        workflow_id: str,
        input_json: str | None,
        gate: str | None,
        retry_epilogue: bool,
        fmt: str,
    ) -> None:
        """Advance a workflow scope, optionally answering a gate first.

        `resume` advances; `answer` records. This verb used to *deposit* — its
        own docstring said "Accepting input does not run the workflow" — so
        nothing on any surface could continue a blocked walk except re-invoking
        the job, which an agent over MCP cannot do.

        The exit code is the walk's, so a run that is still blocked exits 5.
        """
        import json

        from functualize.app.utils import resume_scope

        app = _workflow_app_ref(ctx)
        store = _workflow_operator_store(ctx)

        payload = None
        if input_json is not None:
            try:
                payload = json.loads(input_json)
            except json.JSONDecodeError as exc:
                click.echo(f"Error: --input is not valid JSON: {exc}", err=True)
                raise SystemExit(ExitCode.USAGE) from exc

        with _workflow_refusal():
            result = resume_scope(
                app,
                store,
                workflow_id,
                input=payload,
                gate=gate,
                retry_epilogue=retry_epilogue,
                source="cli",
                # This door is `func builtin workflow resume`. It was labelled
                # `app.execute` by `guarded_execute`'s hardcoded constant, so a
                # CLI resume and a programmatic one were the same run as far as
                # the request could say (rre F9).
                surface="func.builtin",
            )

        if fmt == "json":
            # A walk that ran carries its run's metadata — enums and a start
            # time — which plain `json.dumps` refuses; render them as text.
            click.echo(json.dumps(result, indent=2, default=_json_text))
        if "error" in result:
            if fmt != "json":
                click.echo(f"Error: {result['message']}", err=True)
            raise SystemExit(_workflow_exits.get(result["error"], 1))
        if fmt != "json":
            click.echo(result.get("message") or f"Walk ended: {result['status']}.")
            if (
                result.get("status") == "success"
                and result.get("return_value") is not None
            ):
                click.echo(result["return_value"])
        raise SystemExit(_resume_exit(result))

    def _json_text(value: Any) -> Any:
        """An enum's value, a timestamp's ISO form, anything else's ``str``."""
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return getattr(value, "value", None) or str(value)

    def _resume_exit(result: dict[str, Any]) -> int:
        """The walk's own outcome as an exit code.

        A still-blocked run exits 5, the same code the job itself uses. This is
        a breaking change from the deposit-only verb, which always exited 0 —
        and it is the point: a script that resumes in a loop needs to know
        whether it finished.
        """
        from functualize.app.utils import (
            RunStatus,
            exit_code_for_status,
            status_from_wire,
        )

        raw = str(result.get("status") or "")

        # `resume` reports in **two vocabularies through one field**: the walk's
        # RunStatus when it ran, and the gate-answer state when it did not. The
        # gate states are not run statuses, and the old fallback papered over
        # that by answering 0 for them -- which is how a still-waiting gate came
        # to report success, in direct contradiction of this method's own
        # docstring. Translate the gate vocabulary first, explicitly.
        gate_states = {
            # The input was incomplete, so it was saved and the gate still
            # blocks. That is a blocked run, and a blocked run exits 5.
            "drafted": RunStatus.BLOCKED,
        }
        status = gate_states.get(raw.strip().lower()) or status_from_wire(raw)
        if status is None:
            # The verb reported something that names no RunStatus. The old
            # fallback special-cased two gate-state strings that are not run
            # statuses at all and returned 0 for them, and 1 for everything
            # else. Returning 0 for an unrecognised string is how a resume loop
            # concludes it has finished when it has not. USAGE says what
            # actually happened: the caller and the verb disagree about the
            # vocabulary.
            return int(ExitCode.USAGE)
        return int(exit_code_for_status(status))

    @workflow_app.command("gate-tool")
    @click.argument("workflow_id")
    @click.argument("tool")
    @click.option(
        "--args", "args_json", default="{}", help="Tool arguments as a JSON object."
    )
    @click.option(
        "--format",
        "fmt",
        type=click.Choice(["table", "json"]),
        default="table",
        help="Render the result as a table or JSON.",
    )
    @click.pass_context
    def workflow_gate_tool(
        ctx: click.Context, workflow_id: str, tool: str, args_json: str, fmt: str
    ) -> None:
        """Run a tool a waiting gate offers, inside that gate's scope.

        Arguments the gate fixes cannot be supplied — a bound argument is
        refused, never silently overridden. The call is recorded on the scope
        but never memoized: calling twice runs twice.
        """
        import json

        from functualize.app.utils import GateToolPolicy, call_gate_tool

        app = _workflow_app_ref(ctx)
        store = _workflow_store(ctx)
        try:
            args = json.loads(args_json)
        except json.JSONDecodeError as exc:
            click.echo(f"Error: --args is not valid JSON: {exc}", err=True)
            raise SystemExit(ExitCode.USAGE) from exc

        with _workflow_refusal():
            result = call_gate_tool(
                app,
                store,
                workflow_id,
                tool,
                args,
                policy=GateToolPolicy(app, store=store),
            )

        if fmt == "json":
            click.echo(json.dumps(result, indent=2))
        if "error" in result:
            if fmt != "json":
                click.echo(f"Error: {result['message']}", err=True)
            raise SystemExit(_workflow_exits.get(result["error"], 1))
        if fmt != "json":
            click.echo(
                f"{result['tool']}: {result['status']} -> {result['return_value']!r}"
            )

    @workflow_app.command("watch")
    @click.argument("workflow_id")
    @click.option(
        "--format",
        "fmt",
        type=click.Choice(["text", "json"]),
        default="text",
        help="Render each event as a line, or as newline-delimited JSON.",
    )
    @click.option(
        "--after",
        "after",
        type=int,
        default=0,
        metavar="SEQ",
        help="Resume a watch: only events after this sequence number.",
    )
    @click.option(
        "--timeout",
        "timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Give up after this long with no event. Default: wait while held.",
    )
    @click.pass_context
    def workflow_watch(
        ctx: click.Context,
        workflow_id: str,
        fmt: str,
        after: int,
        timeout: float | None,
    ) -> None:
        """Follow a workflow scope's graph as it advances.

        Renders what the **walker emitted** — never a description reconstructed
        by re-reading the record, which cannot tell a step that ran from one
        that was replayed and misses anything that started and finished between
        two readings.

        Reports the scope **parked** when nobody holds its lease, rather than
        waiting for a walk that is not running (spec AC-12). That is also how it
        terminates on a finished scope: the log drains, the lease is not held,
        and it returns having printed everything that happened.

        `--format json` emits one object per line, so it pipes.
        """
        import json

        from functualize.app.utils import derived_state, walk_is_live, watch_scope

        store = _workflow_store(ctx)
        with _workflow_refusal():
            scope = store.get_scope(workflow_id)
        if scope is None:
            click.echo(f"Error: no workflow scope '{workflow_id}'.", err=True)
            raise SystemExit(1)

        live = walk_is_live(scope)
        state = derived_state(scope)
        if fmt == "json":
            click.echo(
                json.dumps(
                    {
                        "scope": workflow_id,
                        "state": state,
                        "watching": "live" if live else "parked",
                    }
                )
            )
        else:
            click.echo(
                f"{workflow_id}  {state}  "
                f"({'live' if live else 'parked'} — following events)"
            )

        seq = after
        with _workflow_refusal():
            for event in watch_scope(store, workflow_id, after=after, timeout=timeout):
                seq = int(event.get("seq", seq))
                if fmt == "json":
                    click.echo(json.dumps(event))
                else:
                    click.echo(_render_walk_event(event))

        with _workflow_refusal():
            final = store.get_scope(workflow_id)
        state = derived_state(final) if final else "gone"
        if fmt == "json":
            click.echo(json.dumps({"scope": workflow_id, "state": state, "seq": seq}))
        else:
            click.echo(f"{workflow_id}  {state}  (seq {seq})")

    @workflow_app.command("cancel")
    @click.argument("workflow_id")
    @click.pass_context
    def workflow_cancel(ctx: click.Context, workflow_id: str) -> None:
        """Cancel a workflow scope. Terminal — it cannot be resumed."""
        from functualize.app.utils import cancel_scope

        with _workflow_refusal():
            result = cancel_scope(_workflow_operator_store(ctx), workflow_id)
        if "error" in result:
            click.echo(f"Error: {result['message']}", err=True)
            raise SystemExit(_workflow_exits.get(result["error"], 1))
        click.echo(result["message"])

    @workflow_app.command("purge")
    @click.option(
        "--state", "state", default=None, help="Only scopes in this finished state."
    )
    @click.option(
        "--older-than",
        "older_than",
        type=float,
        default=None,
        metavar="DAYS",
        help="Only scopes whose newest recorded result is older.",
    )
    @click.pass_context
    def workflow_purge(
        ctx: click.Context, state: str | None, older_than: float | None
    ) -> None:
        """Delete finished workflow scopes.

        Never touches a running, waiting or ready scope, and --state cannot
        name one: this is a hard delete with no backup, unlike
        `state clear --scopes`, which moves the whole file aside.
        """
        from functualize.app.utils import purge_scopes

        with _workflow_refusal():
            result = purge_scopes(
                _workflow_store(ctx), state=state, older_than_days=older_than
            )
        if "error" in result:
            click.echo(f"Error: {result['message']}", err=True)
            raise SystemExit(_workflow_exits.get(result["error"], 1))
        click.echo(result["message"])
        for scope_id in result["removed"]:
            click.echo(f"  {scope_id}")

    @workflow_app.command("reclaim")
    @click.argument("workflow_id")
    @click.pass_context
    def workflow_reclaim(ctx: click.Context, workflow_id: str) -> None:
        """Take an abandoned scope so it can be resumed.

        An abandoned scope is one whose runner stopped renewing its lease.
        Nothing reclaims automatically: an expired lease means *nothing has
        heard from that runner*, not *that runner is dead*, and a long step on
        a machine with a slow clock looks identical.

        Not destructive. Every step record, gate payload and position stays
        where it is; only the generation moves, which is what stops the
        previous holder writing.
        """
        from functualize.app.utils import reclaim_scope

        store = _workflow_operator_store(ctx)
        with _workflow_refusal():
            result = reclaim_scope(store, workflow_id)
        if "error" in result:
            click.echo(f"Error: {result['message']}", err=True)
            raise SystemExit(_workflow_exits.get(result["error"], 1))
        click.echo(result["message"])

    _mount(builtin_app, workflow_app, "workflow")
