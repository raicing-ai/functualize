"""Moved builtin command registration for cache."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import (
    _mount,
    sys,
)

if TYPE_CHECKING:
    import click


def register_cache(builtin_app: click.Group) -> None:
    import click

    # --- Cache sub-group ---
    cache_app = click.Group(name="cache", help="Manage the job metadata cache.")

    def _build_provider_for_cwd() -> Any:
        """Build the cached provider over auto-discovered job directories.

        Built from the *resolved* discovery config -- including this
        invocation's own global flags, so `func --exclude '…' builtin cache
        rebuild` rebuilds under that exclusion rather than ignoring it.

        Passing no config made every `func builtin cache` command bare, and a
        bare provider persists `discovery_hash: null`. `cache rebuild` unlinks
        the file and then writes through such a provider, so the next command
        read a null fingerprint, called it a mismatch, and rescanned -- throwing
        away the rebuild it had just been asked for, in every project including
        one with no filters at all. See ADR-011.
        """
        from functualize._cli.config import resolve_cli_config
        from functualize._cli.dispatch import _extract_global_options
        from functualize.app.utils import build_discovery_cache_provider

        _global_opts, cli_flags = _extract_global_options(sys.argv)
        cli_config = resolve_cli_config(cli_flags=cli_flags)

        return build_discovery_cache_provider(discovery_config=cli_config.discovery)

    @cache_app.command("show")
    def cache_show() -> None:
        """Display cache statistics (entry count, stale entries, file size)."""
        stats = _build_provider_for_cwd().stats()

        click.echo(f"Entries: {stats.entry_count}")
        click.echo(f"Stale entries: {stats.stale_count}")
        click.echo(f"File size: {stats.file_size_bytes} bytes")
        if stats.cache_path:
            click.echo(f"Cache path: {stats.cache_path}")
        else:
            click.echo("Cache path: N/A")

    @cache_app.command("clear")
    def cache_clear() -> None:
        """Delete the cache file."""
        import contextlib
        from pathlib import Path

        from functualize.app.utils import resolve_cache_path

        cache_path = resolve_cache_path(Path.cwd())

        if not cache_path.exists():
            raise SystemExit(0)

        with contextlib.suppress(OSError):
            cache_path.unlink()

        click.echo("Cache cleared.")

    @cache_app.command("rebuild")
    def cache_rebuild() -> None:
        """Delete and rebuild the cache from a full re-scan."""
        import contextlib
        from pathlib import Path

        from functualize.app.utils import resolve_cache_path

        cache_path = resolve_cache_path(Path.cwd())
        if cache_path.exists():
            with contextlib.suppress(OSError):
                cache_path.unlink()

        provider = _build_provider_for_cwd()
        jobs = provider.list_jobs()
        click.echo(f"Cache rebuilt with {len(jobs)} entries.")

    @cache_app.command("check")
    def cache_check() -> None:
        """Report stale cache entries without modifying the cache."""
        from pathlib import Path

        from functualize.app.utils import resolve_cache_path

        cache_path = resolve_cache_path(Path.cwd())
        if not cache_path.exists():
            click.echo("No cache file found.")
            return

        stats = _build_provider_for_cwd().stats()

        if stats.entry_count == 0:
            click.echo("Cache is empty.")
            return

        if stats.stale_count == 0:
            click.echo(f"All {stats.entry_count} cache entries are valid.")
        else:
            click.echo(
                f"{stats.stale_count} stale entries out of {stats.entry_count} total."
            )

    _mount(builtin_app, cache_app, "cache")
