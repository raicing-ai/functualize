"""Moved builtin command registration for config."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import (
    _CONFIG_TEMPLATE,
    Path,
    _determine_source,
    _emit_config_field,
    _mount,
    _resolve_editor,
    subprocess,
)

if TYPE_CHECKING:
    import click


def register_config(builtin_app: click.Group) -> None:
    import click

    # --- Config sub-group ---
    @click.group(
        name="config",
        help="Inspect and manage CLI tool configuration.",
        invoke_without_command=True,
    )
    @click.pass_context
    def config_app(ctx: click.Context) -> None:
        """Inspect and manage CLI tool configuration."""
        if ctx.invoked_subcommand is None:
            # Show help with subcommand descriptions
            click.echo("Usage: func config <subcommand>\n")
            click.echo("Subcommands:")
            click.echo(
                "  show   Display resolved config in TOML with source annotations"
            )
            click.echo("  path   Show config file paths with status")
            click.echo("  edit   Open global config in your editor")
            click.echo("\nRun 'func config <subcommand> --help' for details.")

    @config_app.command("show")
    def config_show() -> None:
        """Display resolved config in TOML with source annotations."""
        from functualize._cli.config import read_global_config, resolve_cli_config
        from functualize.app.utils import (
            resolve_project_config,
            resolve_user_config_dir,
        )

        cli_config = resolve_cli_config()
        config_dir = resolve_user_config_dir()
        global_config = read_global_config(config_dir)
        _anchor, project_config = resolve_project_config(Path.cwd())

        # Build TOML output with source annotations
        lines: list[str] = []
        lines.append("[discovery]")

        dc = cli_config.discovery
        _emit_config_field(
            lines,
            "exclude_patterns",
            list(dc.exclude_patterns),
            dc.exclude_patterns,
            project_config,
            global_config,
            "discovery",
        )
        _emit_config_field(
            lines,
            "extra_directories",
            list(dc.extra_directories),
            dc.extra_directories,
            project_config,
            global_config,
            "discovery",
        )
        _emit_config_field(
            lines,
            "require_file_prefix",
            dc.require_file_prefix,
            dc.require_file_prefix,
            project_config,
            global_config,
            "discovery",
        )
        _emit_config_field(
            lines,
            "require_file_postfix",
            dc.require_file_postfix,
            dc.require_file_postfix,
            project_config,
            global_config,
            "discovery",
        )
        _emit_config_field(
            lines,
            "require_file_import",
            dc.require_file_import,
            dc.require_file_import,
            project_config,
            global_config,
            "discovery",
        )
        _emit_config_field(
            lines,
            "require_file_marker",
            dc.require_file_marker,
            dc.require_file_marker,
            project_config,
            global_config,
            "discovery",
        )
        _emit_config_field(
            lines,
            "require_job_decorators",
            list(dc.require_job_decorators) if dc.require_job_decorators else None,
            dc.require_job_decorators,
            project_config,
            global_config,
            "discovery",
        )
        _emit_config_field(
            lines,
            "require_job_prefix",
            dc.require_job_prefix,
            dc.require_job_prefix,
            project_config,
            global_config,
            "discovery",
        )
        _emit_config_field(
            lines,
            "require_job_postfix",
            dc.require_job_postfix,
            dc.require_job_postfix,
            project_config,
            global_config,
            "discovery",
        )

        lines.append("")
        lines.append("[cli]")
        _emit_config_field(
            lines,
            "output",
            cli_config.output,
            cli_config.output,
            project_config,
            global_config,
            "cli",
        )
        _emit_config_field(
            lines,
            "show_timing",
            cli_config.show_timing,
            cli_config.show_timing,
            project_config,
            global_config,
            "cli",
        )

        lines.append("")
        lines.append("[aliases]")
        for alias_name, alias_target in sorted(cli_config.aliases.items()):
            source = _determine_source(
                alias_name, alias_target, project_config, global_config, "aliases"
            )
            lines.append(f'{alias_name} = "{alias_target}"  # source: {source}')

        if not cli_config.aliases:
            lines.append("# (none configured)")

        click.echo("\n".join(lines))

    @config_app.command("path")
    def config_path() -> None:
        """Show config file paths with status (✓ used / ○ found / ✗ missing)."""
        from functualize.app.utils import resolve_user_config_dir

        config_dir = resolve_user_config_dir()
        global_path = config_dir / "config.toml"
        cwd = Path.cwd()
        pyproject_path = cwd / "pyproject.toml"
        functualize_toml_path = cwd / ".functualize.toml"

        # Determine global config status
        if global_path.exists():
            try:
                import tomllib as _tomllib

                content = global_path.read_bytes()
                data = _tomllib.loads(content.decode("utf-8"))
                # Check if any section has actual key-value pairs
                has_values = any(
                    (isinstance(v, dict) and v) or (not isinstance(v, dict))
                    for v in data.values()
                )
                if has_values:
                    click.echo(f"  ✓ used    {global_path}")
                else:
                    click.echo(f"  ○ found   {global_path}")
            except Exception:
                click.echo(f"  ○ found   {global_path}")
        else:
            click.echo(f"  ✗ missing {global_path}")

        # Determine project config status
        pyproject_has_functualize = False
        if pyproject_path.exists():
            try:
                import tomllib as _tomllib

                content = pyproject_path.read_bytes()
                data = _tomllib.loads(content.decode("utf-8"))
                tool_section = data.get("tool", {})
                if isinstance(tool_section, dict) and "functualize" in tool_section:
                    pyproject_has_functualize = True
                    click.echo(f"  ✓ used    {pyproject_path} [tool.functualize]")
                else:
                    click.echo(f"  ○ found   {pyproject_path} (no [tool.functualize])")
            except Exception:
                click.echo(f"  ○ found   {pyproject_path}")
        else:
            click.echo(f"  ✗ missing {pyproject_path}")

        # .functualize.toml: only relevant if pyproject doesn't have [tool.functualize]
        if not pyproject_has_functualize:
            if functualize_toml_path.exists():
                click.echo(f"  ✓ used    {functualize_toml_path}")
            else:
                click.echo(f"  ✗ missing {functualize_toml_path}")

    @config_app.command("edit")
    def config_edit() -> None:
        """Open global config in $VISUAL / $EDITOR / platform default."""
        from functualize.app.utils import resolve_user_config_dir

        config_dir = resolve_user_config_dir()
        config_path = config_dir / "config.toml"

        # Resolve editor: $VISUAL → $EDITOR → platform default
        editor = _resolve_editor()
        if not editor:
            click.echo(
                "Error: No editor found. Set $VISUAL or $EDITOR environment variable.",
                err=True,
            )
            raise SystemExit(1)

        # Create parent directory if needed
        config_dir.mkdir(parents=True, exist_ok=True)

        # Create template config if file doesn't exist
        if not config_path.exists():
            config_path.write_text(_CONFIG_TEMPLATE)

        # Open in editor
        try:
            subprocess.run([editor, str(config_path)], check=True)  # noqa: S603
        except FileNotFoundError:
            click.echo(f"Error: Editor '{editor}' not found on PATH.", err=True)
            raise SystemExit(1) from None
        except subprocess.CalledProcessError as exc:
            click.echo(f"Error: Editor exited with code {exc.returncode}.", err=True)
            raise SystemExit(exc.returncode) from None

    _mount(builtin_app, config_app, "config")
