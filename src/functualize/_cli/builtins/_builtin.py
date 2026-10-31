"""Moved builtin command registration for builtin."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import (
    OUTPUT_MODES,
    ExitCode,
    _completions_install_path,
    _env_exec,
    _env_print,
    _mount,
    _project_substrate,
    _render_history,
    _report_parallel,
    _resolve_env_vars,
)

if TYPE_CHECKING:
    import click


def register_prefix(builtin_app: click.Group) -> None:
    import click

    from functualize._cli.completions.shell_init import SHELLS

    # --- parallel (T40) ---
    # `Invoke.parallel` has existed since S1 and was reachable only from inside
    # a job, so "run these four jobs at once" required writing a job whose only
    # purpose was to call it. This is the same operation from the command line,
    # over the same code — not a second implementation.
    @builtin_app.command("parallel")
    @click.argument("job_names", nargs=-1, required=True)
    @click.option(
        "--timeout",
        type=float,
        default=None,
        help=(
            "Seconds before unfinished jobs are reported as timed out "
            "(default 300; 0 waits indefinitely)."
        ),
    )
    @click.option(
        "--output",
        "output_mode",
        type=click.Choice(OUTPUT_MODES),
        default="interleaved",
        show_default=True,
        help="How to present the output of jobs that all run at once.",
    )
    @click.pass_context
    def parallel_command(
        ctx: click.Context,
        job_names: tuple[str, ...],
        timeout: float | None,
        output_mode: str,
    ) -> None:
        """Run several jobs concurrently and report on all of them."""
        from functualize._cli.parallel_output import ParallelOutput

        obj = ctx.find_root().obj
        if obj is None or "app" not in obj:
            click.echo("Error: No app context available.", err=True)
            raise SystemExit(ExitCode.USAGE)

        app = obj["app"]
        try:
            with ParallelOutput(output_mode) as router:
                results = app.execute_parallel(
                    job_names,
                    timeout=timeout,
                    observer=router if output_mode != "interleaved" else None,
                )
        except ValueError as exc:
            # The >32 guard, and anything else the capability rejects up front.
            click.echo(f"Error: {exc}", err=True)
            raise SystemExit(ExitCode.USAGE) from exc

        _report_parallel(job_names, results)

    # --- history (T42) ---
    # The engine appends a record per top-level run to the same ring the shell
    # surface writes to, so one command answers "what has run here lately?"
    # across both. `--namespace` narrows to one kind when the mix is noise.
    @builtin_app.command("history")
    @click.option(
        "--namespace",
        default=None,
        help="Show only one namespace (e.g. job, shell).",
    )
    @click.option(
        "--limit",
        type=int,
        default=None,
        help="Show at most this many of the most recent records.",
    )
    @click.pass_context
    def history_command(
        ctx: click.Context, namespace: str | None, limit: int | None
    ) -> None:
        """Show recent runs, newest first.

        **Two sources since `durable-run-layer`/T3b**, where one ring used to
        hold both. Job history is *derived* from the run log — which recorded
        the same runs plus the nested ones plus who invoked them, making the
        ring a poorer copy of a subset. Shell history moved to its own file,
        because a typed command was never a run and the log has nowhere to put
        it.

        Nothing changes for the caller: the same records, the same order, the
        same `--namespace` flag.
        """
        from pathlib import Path

        from functualize.app.utils import RunStore, ShellHistoryStore, job_history

        # Reading must not create anything in a project that has never run
        # anything, which is why these ask rather than write: every read path
        # through a store is a pure read, and `for_project` only resolves where
        # the documents would be.
        substrate = _project_substrate(ctx)
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
        job_records = job_history(runs) if namespace in (None, "job") else []
        shell_records = shell.entries() if namespace in (None, "shell") else []
        if not job_records and not shell_records and not runs.run_ids():
            click.echo("No history recorded yet.", err=True)
            return

        records: list[dict[str, Any]] = [*job_records, *shell_records]
        # Merged newest-first across both sources. Sorted on `at`, which every
        # record now carries — the shell half did not stamp one until T3b, and
        # an unsorted merge would have put every shell line after every job
        # line regardless of when either happened.
        records.sort(key=lambda r: str(r.get("at") or ""), reverse=True)
        if limit is not None:
            records = records[:limit]

        if not records:
            where = f" in namespace '{namespace}'" if namespace else ""
            click.echo(f"No history recorded yet{where}.", err=True)
            return

        for line in _render_history(records):
            click.echo(line)

    # --- env (T43) ---
    # A job's resolved config, as environment variables — so a tool that is not
    # functualize can consume it. Two forms over one resolution: print exports
    # to eval, or exec a command with the vars injected. Secrets are gated:
    # masked in the printed form, omitted from the exec env, unless the caller
    # opts in with --include-secrets. The default output is therefore safe to
    # paste into a bug report; the real secret takes a deliberate flag.
    @builtin_app.command(
        "env",
        context_settings={"ignore_unknown_options": True},
    )
    @click.argument("job_name")
    @click.argument("command", nargs=-1, type=click.UNPROCESSED)
    @click.option(
        "--include-secrets",
        is_flag=True,
        default=False,
        help="Include real secret values (default: masked / omitted).",
    )
    @click.pass_context
    def env_command(
        ctx: click.Context,
        job_name: str,
        command: tuple[str, ...],
        include_secrets: bool,
    ) -> None:
        """Export a job's resolved config as environment variables.

        \b
        Print form:  eval $(func builtin env deploy)
        Exec form:   func builtin env deploy -- kubectl apply -f -
        """
        obj = ctx.find_root().obj
        if obj is None or "app" not in obj:
            click.echo("Error: No app context available.", err=True)
            raise SystemExit(ExitCode.USAGE)

        env_vars = _resolve_env_vars(obj["app"], job_name)

        # `--` is consumed by click; a leading token that is not an option is
        # the command. `ignore_unknown_options` lets `kubectl -f` through.
        exec_command = list(command)

        if exec_command:
            _env_exec(env_vars, exec_command, include_secrets)
        else:
            _env_print(env_vars, include_secrets)

    # --- shell-init (T44b) ---
    # Boot once, bake the word lists into a static shell script, and put zero
    # Python in the TAB path (the direnv model). Warm boot is ~400ms — a
    # completion that ran `func` per keystroke would be unusable.
    @builtin_app.command("shell-init")
    @click.argument("shell", type=click.Choice(SHELLS))
    @click.option(
        "--install",
        is_flag=True,
        default=False,
        help="Write the script under the cache dir instead of printing it.",
    )
    @click.pass_context
    def shell_init_command(ctx: click.Context, shell: str, install: bool) -> None:
        """Emit a static shell completion script (bash, zsh, or fish)."""
        from functualize._cli.completions.data import extract_completion_data
        from functualize._cli.completions.shell_init import render_completion_script

        obj = ctx.find_root().obj
        if obj is None or "app" not in obj:
            click.echo("Error: No app context available.", err=True)
            raise SystemExit(ExitCode.USAGE)

        data = extract_completion_data(obj["app"])
        script = render_completion_script(data, shell)

        if not install:
            click.echo(script, nl=False)
            return

        path = _completions_install_path(shell)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(script, encoding="utf-8")
        # The path and the source line go to stderr so `--install` composes: a
        # user who redirects stdout still gets a clean file, and the hint is
        # advice, not data.
        click.echo(f"Wrote {shell} completion to {path}", err=True)
        click.echo(f"Add to your shell startup:  source {path}", err=True)

    # --- why (explainability, §D.6) ---
    # The renderer shipped at the S3 stage gate with tests and no command to
    # reach it, so "why did this job run?" had no answer on the command line
    # while the code to answer it sat unused.
    @builtin_app.command("why")
    @click.argument("job_name")
    @click.option(
        "--json",
        "as_json",
        is_flag=True,
        default=False,
        help="Emit the verdict as one JSON object instead of prose.",
    )
    @click.pass_context
    def why_command(ctx: click.Context, job_name: str, as_json: bool) -> None:
        """Explain whether a job would run, and why.

        Exits 0 whenever the question is answered about a runnable job — would
        run or would not — so a scripted `func builtin why <job> && …` cannot
        read a healthy job as a failure. The run/not-run distinction is data,
        in the prose headline or the JSON payload's `will_run` and `state`,
        not the exit code. Non-zero is reserved for what the documented
        exit-code table already means: 3 refused or failed precondition, 5
        blocked at a gate, 2 a job that cannot be resolved.
        """
        import json as _json

        obj = ctx.find_root().obj
        if obj is None or "app" not in obj:
            click.echo("Error: No app context available.", err=True)
            raise SystemExit(1)

        app = obj["app"]
        payload = app.explain_data(job_name)
        # Both forms come off one set of verdicts (`explain_verdicts`), so the
        # JSON and the prose cannot disagree about the same job — which is the
        # failure `func builtin why` itself exists to make impossible.
        click.echo(_json.dumps(payload) if as_json else app.explain(job_name))

        code = int(payload.get("exit_code", 0))
        if code:
            raise SystemExit(code)


def register_suffix(builtin_app: click.Group) -> None:
    import click

    # --- Scaffold sub-group ---
    from functualize._cli.scaffold.cli import scaffold_app

    _mount(builtin_app, scaffold_app, "scaffold")

    # --- Top-level version command ---
    @click.command("version")
    def version_command() -> None:
        """Show the functualize version."""
        from functualize import __version__

        click.echo(f"functualize {__version__}")

    _mount(builtin_app, version_command, "version")

    # The vault group lives in `vault_cmd.py` (see its docstring for why).
    from functualize._cli.vault_cmd import vault_app

    _mount(builtin_app, vault_app, "vault")
