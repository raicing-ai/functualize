"""Moved builtin command registration for info."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import (
    ExitCode,
    _mount,
    _state_location,
    _state_mode_line,
)

if TYPE_CHECKING:
    import click


def register_info(builtin_app: click.Group) -> None:
    import click

    # --- Info sub-group (resolves app lazily from ctx.obj) ---
    # A group rather than a command, with `invoke_without_command=True`, so
    # bare `func builtin info` keeps printing the overview every doc and skill
    # points at while the subcommands add the structured views.
    def _info_app_and_config(ctx: click.Context) -> tuple[Any, Any]:
        obj = ctx.find_root().obj
        if obj is None or "app" not in obj:
            click.echo("Error: No app context available.", err=True)
            raise SystemExit(ExitCode.USAGE)
        return obj["app"], obj.get("cli_config")

    def _emit_json(payload: Any) -> None:
        import json

        click.echo(json.dumps(payload, indent=2, default=str))

    @click.group(
        name="info",
        invoke_without_command=True,
        help="Display app state, discovered jobs, and config.",
    )
    @click.option(
        "--job",
        default=None,
        help="Show resolved JobConfig values for a specific job.",
    )
    @click.option(
        "--show-env-vars",
        is_flag=True,
        default=False,
        help="Display all current process environment variables.",
    )
    @click.option(
        "--json",
        "json_out",
        is_flag=True,
        default=False,
        help=(
            "Emit the full report as JSON (same as `info all --json`). "
            "Set FUNCTUALIZE_CLI_OUTPUT=json to make it the default, or "
            "=plain for text without box-drawing."
        ),
    )
    @click.pass_context
    def info_group(
        ctx: click.Context, job: str | None, show_env_vars: bool, json_out: bool
    ) -> None:
        """Show current CLI configuration, discovered jobs, and resolved config."""
        if ctx.invoked_subcommand is not None:
            return

        from functualize._cli.info import (
            full_report,
            render_report_text,
            resolve_renderer,
        )

        app, cli_config = _info_app_and_config(ctx)
        renderer = resolve_renderer(json_out, cli_config)

        if renderer == "json":
            _emit_json(full_report(app, cli_config))
            return

        if renderer == "plain":
            for line in render_report_text(full_report(app, cli_config)):
                click.echo(line)
            return

        from functualize.app.adapters.cli import _show_info_impl

        _show_info_impl(app, job=job, show_env_vars=show_env_vars)
        from functualize._cli.info import (
            collision_projection,
            is_strict_collision,
            render_collision_notice,
        )

        collisions_by_name = collision_projection(app)
        for descriptor in app.get_jobs():
            if job is not None and job != descriptor.name:
                continue
            for collision in collisions_by_name.get(descriptor.name, ()):
                # Two shapes share this map. Only the five-key record is what
                # `render_collision_notice` can read; the strict record names
                # every claimant of a name that has no descriptor, so it is
                # rendered by `render_catalog_text` and never here.
                if is_strict_collision(collision):
                    continue
                click.echo(
                    render_collision_notice(str(descriptor.command_path), collision)
                )

        # Display resolution info (import_libs, anchor, convention dirs)
        if cli_config is not None:
            click.echo("")
            click.echo("─── Config Resolution ───")
            anchor = getattr(cli_config, "anchor", None)
            if anchor is not None:
                click.echo(f"  Anchor: {anchor}")

            import_libs = getattr(cli_config, "import_libs", ())
            if import_libs:
                click.echo("  import_libs:")
                for lib_path in import_libs:
                    click.echo(f"    - {lib_path}")
            else:
                click.echo("  import_libs: (none)")

            # Show convention directories detected
            if anchor is not None:
                conv_dirs: list[str] = []
                for subdir in ("jobs", "lib", "plugins"):
                    conv_path = anchor / ".functualize" / subdir
                    if conv_path.is_dir():
                        conv_dirs.append(f".functualize/{subdir}/")
                if conv_dirs:
                    click.echo("  Convention dirs:")
                    for d in conv_dirs:
                        click.echo(f"    - {d}")
                else:
                    click.echo("  Convention dirs: (none detected)")

        # Where freshness is remembered, and which of the two modes that is.
        # `resolve_fresh_path` has always walked upward for a `.functualize/`
        # and fallen back to the home cache, and nothing said which had
        # happened — so a project could spend its whole life in standalone
        # mode and then go looking for a `fresh.json` under a hashed directory
        # it had never seen.
        state_path, state_mode, state_marker = _state_location()
        click.echo("")
        click.echo("─── Runtime State ───")
        # The same label `data show` uses. Two words for one path is the drift
        # that made `state` ambiguous in the first place.
        click.echo(f"  Freshness path: {state_path}")
        # The scope file is reported here for the same reason the mode is: a
        # file whose location nothing prints is a file nobody finds.
        click.echo(f"  Scopes path: {state_path.with_name('scopes.json')}")
        click.echo(f"  Mode:       {_state_mode_line(state_mode, state_marker)}")

        # Agent skills. `info` is where the skills themselves tell an agent to
        # look first, so it is where the answer to "do skills exist, and
        # where?" belongs — the --help epilog only has room for the pointer.
        from functualize._cli.skills import list_skills, resolve_skills_locations

        locations = resolve_skills_locations()
        click.echo("")
        click.echo("─── Agent Skills ───")
        if not locations:
            click.echo("  (none found for this installation)")
        else:
            for location in locations:
                names = (
                    ", ".join(s.name for s in list_skills(location.path)) or "(none)"
                )
                stamp = (
                    f"{location.distribution} {location.version}"
                    if location.version
                    else location.distribution
                )
                click.echo(f"  {stamp} ({location.origin})")
                click.echo(f"    Path: {location.path}")
                click.echo(f"    Skills: {names}")
            click.echo("  Install: func builtin skills install")

        click.echo("")
        click.echo("Machine-readable: func builtin info schema | info jobs --json")

    @info_group.command("jobs")
    @click.argument("name", required=False)
    @click.option(
        "--json",
        "json_out",
        is_flag=True,
        default=False,
        help="Emit JSON. Default it with FUNCTUALIZE_CLI_OUTPUT=json.",
    )
    @click.pass_context
    def info_jobs(ctx: click.Context, name: str | None, json_out: bool) -> None:
        """List discovered jobs, or show one in detail.

        With no NAME this is the catalog — every job with its one-line summary.
        With a NAME it is that job in full, including its input schema.
        """
        from functualize._cli.info import (
            job_catalog,
            job_detail,
            render_catalog_text,
            render_collision_notice,
            resolve_renderer,
        )
        from functualize.types import CommandPath

        app, cli_config = _info_app_and_config(ctx)
        renderer = resolve_renderer(json_out, cli_config)

        if name is not None:
            detail = job_detail(app, name)
            if detail is None:
                click.echo(f"Error: no job named '{name}'.", err=True)
                raise SystemExit(ExitCode.USAGE)
            if renderer == "json":
                _emit_json(detail)
                return
            path = str(CommandPath.of(detail["group"], detail["name"]))
            click.echo(f"{path}  {detail['summary']}".rstrip())
            if detail["group"]:
                click.echo(f"  group: {detail['group']}")
            if detail["source_file"]:
                click.echo(f"  source: {detail['source_file']}")
            for collision in detail.get("collisions", ()):
                click.echo(f"  {render_collision_notice(path, collision)}")
            if detail["requires_tty"]:
                click.echo("  requires a terminal")
            if detail["dependencies"]:
                click.echo(f"  depends on: {', '.join(detail['dependencies'])}")
            click.echo("  parameters:")
            if not detail["parameters"]:
                click.echo("    (none)")
            for param in detail["parameters"]:
                flag = (
                    "required"
                    if param["required"]
                    else f"default={param.get('default')!r}"
                )
                click.echo(f"    {param['name']}: {param.get('type')} ({flag})")
            return

        catalog = job_catalog(app)
        if renderer == "json":
            _emit_json(catalog)
            return
        for line in render_catalog_text(catalog):
            click.echo(line)

    @info_group.command("schema")
    @click.argument("name", required=False)
    @click.option(
        "--kind",
        type=click.Choice(["job", "builtin", "plugin"]),
        default=None,
        help=(
            "Restrict to jobs, builtin commands, or plugin-registered "
            "commands. Default: all three."
        ),
    )
    @click.pass_context
    def info_schema(ctx: click.Context, name: str | None, kind: str | None) -> None:
        """Print every command's input contract as JSON Schema.

        Covers jobs *and* builtins: both are nodes in one command tree, and an
        agent should not have to walk `--help` for the builtin subtree either.
        Address one command by its dotted path — `demo.report`,
        `builtin.skills.materialize`.

        Always JSON — it is a contract, not a display. Built by the same core
        renderer the MCP plugin calls, so a tool definition and this command
        cannot describe a command differently.
        """
        from functualize._cli.info import command_schemas

        app, _ = _info_app_and_config(ctx)
        schemas = command_schemas(app, name, kind=kind)
        if name is not None and not schemas:
            click.echo(f"Error: no command named '{name}'.", err=True)
            raise SystemExit(ExitCode.USAGE)
        _emit_json(schemas[0] if name is not None else schemas)

    @info_group.command("all")
    @click.option(
        "--json",
        "json_out",
        is_flag=True,
        default=False,
        help="Emit JSON. Default it with FUNCTUALIZE_CLI_OUTPUT=json.",
    )
    @click.pass_context
    def info_all(ctx: click.Context, json_out: bool) -> None:
        """Everything info knows, as one document.

        Environment, config resolution, agent skills, and every job with its
        input schema — one fetch instead of four commands and three prose
        formats.
        """
        from functualize._cli.info import (
            full_report,
            render_report_text,
            resolve_renderer,
        )

        app, cli_config = _info_app_and_config(ctx)
        report = full_report(app, cli_config)

        # `all` is a document, not a display: there is no panelled version of
        # it, so `rich` and `plain` render the same text and only `json`
        # differs.
        if resolve_renderer(json_out, cli_config) == "json":
            _emit_json(report)
            return
        for line in render_report_text(report):
            click.echo(line)

    # Mounted from a sibling module rather than defined inline, following
    # `scaffold` and `skills`. `self doctor` is *also* intercepted pre-boot in
    # `_run_cli`; this mount is what makes it visible to `--help`, to the
    # registry mirror, to completion, and to a consumer app's CLI.
    from functualize._cli.plugin_cmd import plugin_app
    from functualize._cli.self_cmd import self_app

    _mount(builtin_app, plugin_app, "plugin")
    _mount(builtin_app, self_app, "self")

    _mount(builtin_app, info_group, "info")
