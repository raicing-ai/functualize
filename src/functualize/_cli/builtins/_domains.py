"""Moved builtin command registration for domains."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import (
    _mount,
)

if TYPE_CHECKING:
    import click


def register_domains(builtin_app: click.Group) -> None:
    import click

    # --- Domains sub-group ---
    domains_app = click.Group(name="domains", help="Discover and inspect domain SDKs.")

    @domains_app.command("list")
    def domains_list() -> None:
        """Display all discovered domains with providers and active selection."""
        from functualize.plugin import discover_domains, scan_domain_providers

        domains = discover_domains()

        if not domains:
            click.echo("No domains discovered.")
            click.echo("")
            click.echo("Install a domain SDK package to get started:")
            click.echo("  pip install functualize-ai")
            click.echo("  pip install functualize-tasks")
            return

        click.echo("Discovered Domains:")
        click.echo("")

        for meta in sorted(domains, key=lambda d: d.name):
            providers = scan_domain_providers(meta)
            provider_names = sorted(providers.keys()) if providers else []

            # A single installed provider auto-wires at boot; with multiple
            # installed and none configured, none is wired — the honest
            # "installed but not wired" state the signpost below explains.
            active_provider: str | None = None
            if len(provider_names) == 1:
                active_provider = provider_names[0]

            click.echo(f"  {meta.display_name} ({meta.name})")

            if provider_names:
                providers_display = []
                for pname in provider_names:
                    if pname == active_provider:
                        providers_display.append(f"{pname} (active)")
                    else:
                        providers_display.append(pname)
                click.echo(f"    Providers: {', '.join(providers_display)}")
                if active_provider is None:
                    # Installed but not wired — tell the user how to wire one.
                    click.echo(
                        f"    Not wired: multiple providers installed; set "
                        f'provider = "<name>" in the [{meta.config_section}] '
                        f"config section to activate one."
                    )
            else:
                click.echo("    Providers: (none installed)")

            click.echo("")

    _mount(builtin_app, domains_app, "domains")
