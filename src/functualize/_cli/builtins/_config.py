"""Moved builtin command registration for config."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import (
    _CONFIG_TEMPLATE,
    Path,
    _mount,
    _resolve_editor,
    _toml_value,
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
        from functualize.app.config import CliConfig, resolve_app_settings
        from functualize.app.utils import resolve_user_config_dir

        snapshot = resolve_app_settings(
            Path.cwd(), global_dir=resolve_user_config_dir()
        )
        cli_config = CliConfig.from_settings(snapshot)
        layer_kinds = {str(layer.path): layer.kind for layer in snapshot.layers}

        def emit(lines: list[str], section: str, key: str, value: object) -> None:
            if value is None:
                lines.append(f"# {key} = (not set)")
                return
            source = snapshot.provenance.get(f"{section}.{key}", "default")
            lines.append(
                f"{key} = {_toml_value(value)}  # source: {layer_kinds.get(source, source)}"
            )

        # Build TOML output with source annotations
        lines: list[str] = []
        lines.append("[discovery]")

        dc = cli_config.discovery
        emit(lines, "discovery", "exclude_patterns", list(dc.exclude_patterns))
        emit(lines, "discovery", "extra_directories", list(dc.extra_directories))
        emit(lines, "discovery", "require_file_prefix", dc.require_file_prefix)
        emit(lines, "discovery", "require_file_postfix", dc.require_file_postfix)
        emit(lines, "discovery", "require_file_import", dc.require_file_import)
        emit(lines, "discovery", "require_file_marker", dc.require_file_marker)
        emit(
            lines,
            "discovery",
            "require_job_decorators",
            list(dc.require_job_decorators) if dc.require_job_decorators else None,
        )
        emit(lines, "discovery", "require_job_prefix", dc.require_job_prefix)
        emit(lines, "discovery", "require_job_postfix", dc.require_job_postfix)

        lines.append("")
        lines.append("[cli]")
        emit(lines, "cli", "output", cli_config.output)
        emit(lines, "cli", "show_timing", cli_config.show_timing)

        lines.append("")
        lines.append("[aliases]")
        for alias_name, alias_target in sorted(cli_config.aliases.items()):
            source = next(
                (
                    layer.kind
                    for layer in snapshot.layers
                    if isinstance(layer.values.get("aliases"), dict)
                    and alias_name in layer.values["aliases"]
                ),
                "default",
            )
            lines.append(f'{alias_name} = "{alias_target}"  # source: {source}')

        if not cli_config.aliases:
            lines.append("# (none configured)")

        click.echo("\n".join(lines))

    @config_app.command("path")
    def config_path() -> None:
        """Show config file paths with status (✓ used / ○ found / ✗ missing)."""
        from functualize._cli.data.config_vocabulary import (
            describe,
            unknown_keys_in_layers,
        )
        from functualize.app.config import resolve_app_settings
        from functualize.app.utils import resolve_user_config_dir
        from functualize.plugin import FUNCTUALIZE_SETTINGS

        snapshot = resolve_app_settings(
            Path.cwd(), global_dir=resolve_user_config_dir()
        )
        findings = unknown_keys_in_layers(snapshot.layers, FUNCTUALIZE_SETTINGS)
        for layer in snapshot.layers:
            if not layer.exists:
                status = "✗ missing"
            elif snapshot.contributes.get(layer.path):
                status = "✓ used   "
            else:
                status = "○ found  "
            section = f" [{layer.section_prefix}]" if layer.section_prefix else ""
            annotation = describe(tuple(f for f in findings if f.file == layer.path))
            click.echo(f"  {status} {layer.path}{section}{annotation}")

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
