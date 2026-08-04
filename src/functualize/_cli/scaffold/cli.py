"""Scaffold sub-command for the unified func/functualize CLI.

Provides project and component scaffolding:
  func scaffold init <project_name> [--template <name>]
  func scaffold add job <name>
  func scaffold add plugin <name>
  func scaffold add plugin --domain D --name N
  func scaffold add domain --name N
  func scaffold add tui-screen <name>
  func scaffold list domains

The scaffold_app click.Group is registered as a built-in sub-command on the
main CLI. Both `func` and `functualize` are aliases for the same entry point.
"""

from pathlib import Path

import click

from functualize._cli.scaffold.context import detect_context
from functualize._cli.scaffold.generator import ScaffoldGenerator
from functualize._cli.scaffold.registry import list_templates, validate_template_name


@click.group(
    name="scaffold",
    help="Create new projects and add components to existing ones.",
)
def scaffold_app() -> None:
    """Create new projects and add components to existing ones."""


@click.group(name="add", help="Add a component to an existing functualize project.")
def add_app() -> None:
    """Add a component to an existing functualize project."""


@click.group(name="list", help="List available scaffold resources.")
def list_app() -> None:
    """List available scaffold resources."""


scaffold_app.add_command(add_app, name="add")
scaffold_app.add_command(list_app, name="list")


# --- init command ---


@scaffold_app.command("init")
@click.argument("project_name")
@click.option(
    "--template",
    "-t",
    default="simple",
    help="Project template to use.",
)
@click.option(
    "--directory",
    "-d",
    default=Path("."),
    type=click.Path(path_type=Path),
    help="Parent directory where the project will be created.",
)
def init(project_name: str, template: str, directory: Path) -> None:
    """Initialize a new functualize project from a template."""
    if not validate_template_name(template):
        available = ", ".join(list_templates())
        click.echo(
            f"Error: Unknown template '{template}'. Available: {available}",
            err=True,
        )
        raise SystemExit(1)

    generator = ScaffoldGenerator()
    target_dir = directory / project_name

    try:
        generator.init_project(project_name, target_dir, template=template)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from e
    except FileExistsError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from e

    click.echo(f"Project '{project_name}' created at {target_dir}")


# --- add job command ---


@add_app.command("job")
@click.argument("job_name")
@click.option(
    "--jobs-dir",
    "-j",
    default=None,
    type=click.Path(path_type=Path),
    help="Path to the jobs directory. If omitted, auto-detected from context.",
)
def job(job_name: str, jobs_dir: Path | None) -> None:
    """Add a new job file."""
    generator = ScaffoldGenerator()

    if jobs_dir is not None:
        # Explicit --jobs-dir: use project job template (R7-AC5)
        target_dir = jobs_dir
        standalone = False
    else:
        # Context-aware detection
        ctx = detect_context()
        if ctx.is_project:
            # Project_Context: create in src/<package>/jobs/ (R1-AC1)
            target_dir = ctx.package_dir / "jobs"  # type: ignore[operator]
            target_dir.mkdir(parents=True, exist_ok=True)
            standalone = False
        else:
            # Bare_Context: create standalone job in CWD (R1-AC2, R1-AC3)
            target_dir = ctx.cwd
            standalone = True

    try:
        generator.add_job(job_name, target_dir, standalone=standalone)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from e
    except FileExistsError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from e

    click.echo(f"Job '{job_name}' added to {target_dir}")


# --- add plugin command ---


@add_app.command("plugin")
@click.argument("plugin_name", required=False, default=None)
@click.option(
    "--target-dir",
    "-t",
    default=None,
    type=click.Path(path_type=Path),
    help="Directory where the plugin file will be created. If omitted, auto-detected.",
)
@click.option(
    "--domain",
    "-d",
    default=None,
    help="Domain to create a plugin for (e.g., 'ai', 'state'). "
    "Generates a full plugin package with pyproject.toml, source module, entry point, and test file.",
)
@click.option(
    "--name",
    "-n",
    default=None,
    help="Plugin name when using --domain (e.g., 'my-provider'). "
    "Used to derive package name and provider name.",
)
@click.option(
    "--output-dir",
    "-o",
    default=Path("plugins"),
    type=click.Path(path_type=Path),
    help="Output directory for domain plugin package. Defaults to 'plugins/'.",
)
def plugin(
    plugin_name: str | None,
    target_dir: Path | None,
    domain: str | None,
    name: str | None,
    output_dir: Path,
) -> None:
    """Add a new plugin file or domain plugin package.

    When --domain is specified, generates a full plugin package targeting
    a specific domain SDK with pyproject.toml, source module, entry point
    configuration, and test file.

    Without --domain, generates a simple plugin file (legacy behavior).
    """
    # Domain-aware plugin package generation
    if domain is not None:
        if name is None:
            click.echo("Error: --name is required when using --domain.", err=True)
            raise SystemExit(1)

        generator = ScaffoldGenerator()
        try:
            generator.add_domain_plugin(
                domain_name=domain, plugin_name=name, output_dir=output_dir
            )
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1) from e
        except FileExistsError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1) from e

        package_dir = output_dir / f"functualize-{domain}-{name}"
        click.echo(f"Domain plugin package created at {package_dir}")
        return

    # Legacy simple plugin file generation
    if plugin_name is None:
        click.echo(
            "Error: Please provide a plugin name or use --domain --name.",
            err=True,
        )
        raise SystemExit(1)

    generator = ScaffoldGenerator()

    if target_dir is not None:
        # Explicit --target-dir: use as-is (R7-AC6)
        file_based = False
    else:
        # Context-aware detection
        ctx = detect_context()
        if ctx.is_project:
            # Project_Context: create in src/<package>/plugins/ (R2-AC1)
            target_dir = ctx.package_dir / "plugins"  # type: ignore[operator]
            target_dir.mkdir(parents=True, exist_ok=True)
            file_based = False
        else:
            # Bare_Context: create in .functualize/plugins/ (R2-AC2)
            target_dir = ctx.cwd / ".functualize" / "plugins"
            target_dir.mkdir(parents=True, exist_ok=True)
            file_based = True

    try:
        generator.add_plugin(plugin_name, target_dir, file_based=file_based)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from e
    except FileExistsError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from e

    click.echo(f"Plugin '{plugin_name}' added to {target_dir}")


# --- add tui-screen command ---


@add_app.command("tui-screen")
@click.argument("screen_name")
@click.option(
    "--target-dir",
    "-t",
    default=None,
    type=click.Path(path_type=Path),
    help="Directory where the screen files will be created.",
)
def tui_screen(screen_name: str, target_dir: Path | None) -> None:
    """Add a new TUI screen (Textual Screen subclass + TCSS)."""
    generator = ScaffoldGenerator()

    if target_dir is not None:
        # Explicit --target-dir: use as-is (R7-AC6)
        pass
    else:
        # Context-aware detection
        ctx = detect_context()
        if ctx.is_project:
            # Project_Context: create in src/<package>/screens/ (R3-AC4)
            target_dir = ctx.package_dir / "screens"  # type: ignore[operator]
            target_dir.mkdir(parents=True, exist_ok=True)
        else:
            # Bare_Context without --target-dir: error (R3-AC6)
            click.echo(
                "Error: Cannot add tui-screen outside a project context without "
                "--target-dir. Use --target-dir to specify the target directory.",
                err=True,
            )
            raise SystemExit(1)

    try:
        generator.add_tui_screen(screen_name, target_dir)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from e
    except FileExistsError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from e

    click.echo(f"TUI screen '{screen_name}' added to {target_dir}")


# --- add domain command ---


@add_app.command("domain")
@click.option(
    "--name",
    "-n",
    required=True,
    help="Name of the domain to create (e.g., 'analytics', 'messaging'). "
    "Used to derive package name 'functualize-<name>'.",
)
@click.option(
    "--output-dir",
    "-o",
    default=Path("plugins"),
    type=click.Path(path_type=Path),
    help="Output directory for the domain SDK package. Defaults to 'plugins/'.",
)
def domain(name: str, output_dir: Path) -> None:
    """Add a new domain SDK package with all standard modules.

    Generates a domain SDK package containing:
    - pyproject.toml with entry point configuration
    - __init__.py with public API re-exports
    - _types.py for shared types
    - _protocols.py for provider protocol
    - _errors.py for domain-specific errors
    - _events.py for event constants
    - _metadata.py for DomainMetadata
    - testing/ directory for testing doubles
    """
    generator = ScaffoldGenerator()

    try:
        generator.add_domain_sdk(domain_name=name, output_dir=output_dir)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from e
    except FileExistsError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from e

    package_dir = output_dir / f"functualize-{name}"
    click.echo(f"Domain SDK package 'functualize-{name}' created at {package_dir}")


# --- list domains command ---


@list_app.command(name="domains")
def list_domains() -> None:
    """List all discovered domains and their available scaffold templates."""
    from functualize.plugin import discover_domains, scan_domain_providers

    domains = discover_domains()

    if not domains:
        click.echo(
            "No domains discovered. Install a domain SDK package to get started."
        )
        click.echo("")
        click.echo("Available domain SDKs:")
        click.echo("  pip install functualize-interactivity")
        click.echo("  pip install functualize-state")
        click.echo("  pip install functualize-ai")
        click.echo("  pip install functualize-tasks")
        return

    click.echo("Discovered Domains:")
    click.echo("")

    for meta in sorted(domains, key=lambda d: d.name):
        providers = scan_domain_providers(meta)
        provider_names = sorted(providers.keys()) if providers else []

        click.echo(f"  {meta.name}")
        click.echo(f"    Display Name: {meta.display_name}")
        click.echo(f"    Description:  {meta.description}")
        click.echo(f"    Entry Point:  {meta.entry_point_group}")

        if provider_names:
            click.echo(f"    Providers:    {', '.join(provider_names)}")
        else:
            click.echo("    Providers:    (none installed)")

        if meta.scaffold_template:
            click.echo(f"    Template:     {meta.scaffold_template}")
        else:
            click.echo("    Template:     domain-plugin (default)")

        click.echo("")

    click.echo("Scaffold commands:")
    click.echo("  func scaffold add plugin --domain <DOMAIN> --name <NAME>")
    click.echo("  func scaffold add domain --name <NAME>")


def run() -> None:
    """Entry point for the 'functualize' console script (alias for 'func')."""
    from functualize._cli.main import main

    main()
