"""Moved builtin command registration for data."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import (
    ExitCode,
    _mount,
    _project_substrate,
    _state_location,
    _state_mode_line,
)

if TYPE_CHECKING:
    import click


def register_data(builtin_app: click.Group) -> None:
    import click

    # --- data (everything this project keeps on disk) ---
    #
    # **Named `data`, not for any one file** (`durable-run-layer`/T3b). It was
    # `state`, after `state.json`, and by the time it covered five files that
    # name was a lie in two directions: it under-described the group, and the
    # word "state" already meant something else to a job author —
    # `rc.state.set(...)` writes a scope's state, so `func builtin state clear`
    # cleared the one thing the user did *not* mean.
    #
    # Renaming the file to `fresh.json` fixes half of that. Naming the group
    # after the directory rather than any file in it fixes the other half, and
    # turns `--scopes` from an exception bolted onto a one-file command into an
    # ordinary target among several.
    #
    # Deliberately separate from `cache`: the discovery cache answers "what jobs
    # exist" and is rebuilt on any source change; this answers "what ran last,
    # against which inputs". Clearing one never clears the other (§D.3 Fix 2) —
    # a shared command would recreate exactly the spurious-rebuild bug
    # up-to-date checking exists to prevent.
    data_app = click.Group(
        name="data",
        help=(
            "Inspect and clear what this project keeps on disk — freshness "
            "verdicts, workflow scopes, the run log and shell history."
        ),
    )

    @data_app.command("show")
    @click.pass_context
    def data_show(ctx: click.Context) -> None:
        """Show runtime state statistics."""
        from pathlib import Path

        from functualize.app.utils import (
            SCOPES_LIMIT,
            SCOPES_VERSION,
            FreshStore,
            RunStore,
            ScopeStoreUnreadableError,
            ShellHistoryStore,
        )

        path, mode, marker = _state_location()
        substrate = _project_substrate(ctx)
        store = (
            FreshStore(substrate)
            if substrate is not None
            else FreshStore.for_project(Path.cwd())
        )
        click.echo(f"Fingerprints: {len(store.fingerprint_keys())}")

        # `show` is the command someone runs to find out what is wrong, so it
        # reports an unreadable scope store as a line rather than dying on it —
        # every other statistic is still worth having. The exit code is still
        # 2: nothing here is fine.
        fault: ScopeStoreUnreadableError | None = None
        try:
            # Count, cap and **size** together. The count alone was already
            # here and it is not what a user needs: the defect this reports on
            # was 2,188 records costing 58 ms per state write, and nobody
            # noticed until an external review measured the file. A number with
            # no ceiling beside it does not read as "getting full".
            click.echo(
                f"Scopes: {len(store.scopes.scope_ids())} of {SCOPES_LIMIT} "
                f"— {store.scopes.describe()}"
            )
            # Scope state is reported separately because T3 moved job state
            # out of the record document. Reporting only the records after that
            # move would say "small" about the half that no longer grows while
            # the half that does stayed invisible — the exact failure AC-4
            # exists to prevent, one document over.
            click.echo(f"Scope state: {store.scopes.describe_state()}")
        except ScopeStoreUnreadableError as exc:
            fault = exc
            found = exc.found_version
            detail = (
                f"found version {found}, expected {exc.expected_version}"
                if found is not None
                else "contents could not be parsed"
            )
            count = "" if exc.scope_count is None else f"{exc.scope_count} scopes, "
            click.echo(f"Scopes:       unreadable — {count}{detail}")

        # History left this file in `durable-run-layer`/T3b, so this stops
        # reporting it: what remains here is freshness verdicts, and a count of
        # something the file no longer holds would be a lie in the one command
        # a user runs to find out what is wrong. `func builtin history` is
        # where history is answered now.

        # The other two stores the `data` group covers. Reporting three of five
        # and calling the command `data` would be the same under-description
        # the group was renamed to escape.
        runs = (
            RunStore(substrate)
            if substrate is not None
            else RunStore.for_project(Path.cwd())
        )
        shell = (
            ShellHistoryStore(substrate)
            if substrate is not None
            else ShellHistoryStore.for_project(Path.cwd())
        )
        click.echo(f"Runs: {len(runs.run_ids())} — {runs.describe()}")
        click.echo(f"Shell history: {shell.count()} — {shell.describe()}")

        click.echo(f"Freshness path: {store.describe()}")
        click.echo(f"Scopes format: v{SCOPES_VERSION}")
        click.echo(f"Mode:       {_state_mode_line(mode, marker)}")

        if fault is not None:
            click.echo("")
            click.echo(
                "Error: run `func builtin data clear --scopes` to move the "
                "scope file aside and start fresh.",
                err=True,
            )
            raise SystemExit(ExitCode.USAGE)

    @data_app.command("clear")
    @click.option(
        "--scopes",
        "clear_scopes",
        is_flag=True,
        help="Also discard persisted workflow scopes, including in-flight runs.",
    )
    @click.option(
        "--runs",
        "clear_runs",
        is_flag=True,
        help="Also delete the run log — what ran here, and how each run ended.",
    )
    @click.option(
        "--all",
        "clear_all",
        is_flag=True,
        help="Every target: freshness, scopes, the run log and shell history.",
    )
    @click.pass_context
    def data_clear(
        ctx: click.Context, clear_scopes: bool, clear_runs: bool, clear_all: bool
    ) -> None:
        """Reset derived data — freshness verdicts and the session cache.

        Workflow scopes are kept unless --scopes is passed: a scope is a run
        somebody is waiting on, not a cache. Never touches the discovery cache.

        **Derived data is deleted; records are moved aside.** That asymmetry is
        the whole reason `--scopes` is a separate flag rather than the default:
        a scope holds gate payloads a human deposited, so clearing it renames
        the file and says where it went — which is also the escape hatch from a
        scope file that cannot be parsed, and why it never reads it first.
        """
        from pathlib import Path

        from functualize.app.utils import (
            FreshStore,
            RunStore,
            ScopeStoreUnreadableError,
            ShellHistoryStore,
        )

        if clear_all:
            clear_scopes = clear_runs = True

        substrate = _project_substrate(ctx)
        store = (
            FreshStore(substrate)
            if substrate is not None
            else FreshStore.for_project(Path.cwd())
        )
        if store.is_empty() and store.scopes.is_empty():
            raise SystemExit(0)

        # Counted before clearing, and best-effort: an unreadable scope store
        # is exactly when --scopes matters most, so it must not block the one
        # command that resolves it.
        kept = None
        try:
            kept = len(store.scopes.scope_ids())
        except ScopeStoreUnreadableError:
            kept = None

        store.clear()
        moved = store.scopes.clear() if clear_scopes else None
        click.echo("Cleared freshness verdicts and session state.")

        # Derived, like the freshness ledger — deleted rather than moved aside.
        # The run log is an observation of what happened, not a record anyone
        # is waiting on, so losing it costs history and nothing in flight.
        if clear_runs:
            for cleared, label in (
                (
                    (
                        RunStore(substrate)
                        if substrate is not None
                        else RunStore.for_project(Path.cwd())
                    ).discard(),
                    "run log",
                ),
                (
                    (
                        ShellHistoryStore(substrate)
                        if substrate is not None
                        else ShellHistoryStore.for_project(Path.cwd())
                    ).clear(),
                    "shell history",
                ),
            ):
                if cleared:
                    click.echo(f"Cleared the {label}.")

        if clear_scopes:
            if moved is None:
                return
            noun = "scope" if kept == 1 else "scopes"
            count = "" if kept is None else f"{kept} workflow {noun}"
            click.echo(f"Cleared {count or 'the workflow scope file'}.")
            click.echo(f"  Moved aside to: {moved}")
        elif kept:
            noun = "scope" if kept == 1 else "scopes"
            click.echo(
                f"Kept {kept} workflow {noun} — pass --scopes to clear those too."
            )
        elif kept is None:
            click.echo(
                "Kept the workflow scope file, which could not be read — "
                "pass --scopes to move it aside."
            )

    _mount(builtin_app, data_app, "data")
