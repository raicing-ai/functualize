"""``func builtin vault`` — the project's encrypted secrets vault.

Extracted verbatim from ``builtins.py``, which had grown to 3182 lines with
every builtin group inline except the three already pulled out
(``plugin_cmd``, ``self_cmd``, ``info``). This follows that precedent rather
than inventing one: the module exports ``vault_app`` and ``builtins.py`` mounts
it in two lines.

Moved *before* the local-vault commands were added, deliberately, so that the
move stays reviewable as a pure no-op diff and the commands that follow land in
one file instead of racing the largest module in the package.

This module is in the ``_cli/`` layer — stdlib + public API only. Everything
here reaches the store through ``app.utils``, never ``_config``.
"""

from __future__ import annotations

from typing import Any

import click

from functualize.app.utils import ExitCode

__all__ = ["vault_app"]

# --- Vault sub-group (ADR-016) ---
# Everything here reaches the store through `app.utils`, never `_config`:
# `_cli` may import only the public API, and more to the point the CLI must
# not grow its own opinion about which key wins or what an annotation is.
#
# Only `sync` needs an app. `list`, `status`, `clear` and `keygen` answer
# from the filesystem, which is deliberate -- the moment you most want to
# ask "what is in my vault?" is when the app will not boot.
vault_app = click.Group(
    name="vault",
    help="Sync and inspect this project's encrypted secrets vault.",
)


def _vault_app(ctx: click.Context) -> Any:
    obj = ctx.find_root().obj
    if obj is None or "app" not in obj:
        click.echo(
            "Error: `vault sync` needs the application, and no app context "
            "is available here.",
            err=True,
        )
        raise SystemExit(ExitCode.USAGE)
    return obj["app"]


def _vault_json(payload: Any) -> None:
    import json

    click.echo(json.dumps(payload, indent=2, default=str))


@vault_app.command("keygen")
def vault_keygen() -> None:
    """Print a fresh 32-byte vault key, hex-encoded.

    Written to stdout alone so it can be piped or captured. Nothing is
    stored: where the key lives is the operator's decision, and a command
    that quietly wrote one into a dotfile would be making it for them.
    """
    from functualize.app.utils import generate_vault_key

    click.echo(generate_vault_key())


@vault_app.command("list")
@click.option(
    "--json",
    "json_out",
    is_flag=True,
    default=False,
    help="Emit the entry list as JSON.",
)
def vault_list(json_out: bool) -> None:
    """List what the vault holds — names and freshness, never values.

    Needs no key. `key`, `annotation`, `provider` and `synced_at` are
    stored in clear on purpose so this command works on a machine that
    cannot open the store; only the value is encrypted.
    """
    from functualize.app.utils import vault_entries, vault_location

    entries = vault_entries()
    if json_out:
        _vault_json(
            {
                "path": str(vault_location()),
                "entries": [
                    {
                        "key": e.key,
                        "annotation": e.annotation,
                        "provider": e.provider,
                        "synced_at": e.synced_at.isoformat(),
                    }
                    for e in entries
                ],
            }
        )
        return

    if not entries:
        click.echo("The vault is empty. Run `func builtin vault sync` to fill it.")
        return

    key_width = max(len(e.key) for e in entries)
    provider_width = max(len(e.provider) for e in entries)
    for entry in entries:
        click.echo(
            f"{entry.key:<{key_width}}  "
            f"{entry.provider:<{provider_width}}  "
            f"{entry.synced_at.isoformat(timespec='seconds')}  {entry.annotation}"
        )


@vault_app.command("status")
@click.option(
    "--json",
    "json_out",
    is_flag=True,
    default=False,
    help="Emit the status report as JSON.",
)
@click.pass_context
def vault_status_command(ctx: click.Context, json_out: bool) -> None:
    """Show the key provider in use, the vault's age, and what it holds.

    Answers even when the app cannot boot — that is when it is worth
    asking. The key is resolved non-interactively, so this never raises a
    keychain prompt.
    """
    from functualize.app.utils import vault_status

    obj = ctx.find_root().obj
    app = obj.get("app") if isinstance(obj, dict) else None
    report = vault_status(app)

    if json_out:
        _vault_json(
            {
                "path": str(report.path),
                "exists": report.exists,
                "entries": report.entry_count,
                "key_provider": report.key_provider,
                "oldest_sync": (
                    report.oldest_sync.isoformat() if report.oldest_sync else None
                ),
                "age_seconds": (
                    int(report.age.total_seconds()) if report.age else None
                ),
                "max_age_seconds": int(report.max_age.total_seconds()),
                "stale": report.stale,
                "providers": list(report.providers),
            }
        )
        return

    from functualize.app.utils import vault_duration

    click.echo(f"Path:         {report.path}")
    click.echo(f"Exists:       {'yes' if report.exists else 'no'}")
    click.echo(f"Entries:      {report.entry_count}")
    click.echo(f"Key provider: {report.key_provider or '(none available)'}")
    if report.age is not None:
        marker = "  ← stale" if report.stale else ""
        click.echo(f"Last synced:  {vault_duration(report.age)} ago{marker}")
    else:
        click.echo("Last synced:  never")
    click.echo(f"Max age:      {vault_duration(report.max_age)}")
    click.echo("Providers:    " + (", ".join(report.providers) or "(none registered)"))
    if report.stale:
        click.echo("")
        click.echo("Run `func builtin vault sync` to refresh it.")


@vault_app.command("clear")
@click.option(
    "--yes",
    "assume_yes",
    is_flag=True,
    default=False,
    help="Do not ask for confirmation.",
)
def vault_clear_command(assume_yes: bool) -> None:
    """Delete this project's vault.

    Confirms first. The values live authoritatively in the remote store and
    a sync refills the vault, but a secret whose remote entry has since
    been deleted is gone -- and this command cannot tell the two apart.
    """
    from functualize.app.utils import vault_clear, vault_location

    path = vault_location()
    if not path.exists():
        click.echo(f"No vault to clear at {path}")
        return
    if not assume_yes and not click.confirm(f"Delete {path}?", default=False):
        click.echo("Left alone.")
        return
    vault_clear()
    click.echo(f"Cleared {path}")


@vault_app.command("sync")
@click.option(
    "--json",
    "json_out",
    is_flag=True,
    default=False,
    help="Emit the sync report as JSON.",
)
@click.pass_context
def vault_sync_command(ctx: click.Context, json_out: bool) -> None:
    """Fetch every declared annotation from its provider and store it.

    The only command that contacts a remote configuration provider. A job
    run reads the vault and never the network (ADR-016), so the network
    cost and the credentials live here and nowhere else.

    Individual failures are reported and the rest still sync: one
    unreachable provider must not abandon the twelve secrets that would
    have worked. The exit code is non-zero when anything was declared and
    did not land, so a pipeline still notices.
    """
    from functualize.app.utils import VaultKeyUnavailableError, vault_sync

    app = _vault_app(ctx)
    try:
        report = vault_sync(app)
    except VaultKeyUnavailableError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(ExitCode.REFUSED) from exc

    if json_out:
        _vault_json(
            {
                "path": str(report.path),
                "scanned": report.scanned,
                "synced": [{"key": k, "provider": p} for k, p in report.synced],
                "failed": [{"key": k, "reason": r} for k, r in report.failed],
                "unresolved": [
                    {
                        "key": u.key,
                        "value": u.value,
                        "providers": list(u.providers),
                    }
                    for u in report.unresolved
                ],
                "ok": report.ok,
            }
        )
    else:
        for key, provider in report.synced:
            click.echo(f"  synced   {key}  ({provider})")
        for key, reason in report.failed:
            click.echo(f"  FAILED   {key}  — {reason}", err=True)
        for item in report.unresolved:
            click.echo(
                f"  MISSING  {item.key}  — no plugin registers "
                f"{', '.join(item.providers)}",
                err=True,
            )
        if not report.synced and not report.failed and not report.unresolved:
            click.echo(
                f"Nothing declared remotely in {report.scanned} config "
                f"values. Nothing to sync."
            )
        else:
            click.echo("")
            click.echo(
                f"{len(report.synced)} synced, {len(report.failed)} failed, "
                f"{len(report.unresolved)} unresolvable → {report.path}"
            )

    if not report.ok:
        raise SystemExit(ExitCode.REFUSED)
