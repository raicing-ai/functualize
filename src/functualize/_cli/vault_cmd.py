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


def _vault_app(ctx: click.Context, command: str = "vault sync") -> Any:
    """The booted app, or a usage error naming the command that needed it.

    The message used to say "vault sync" unconditionally, because that was the
    only command here that needed an app. `put` and `inspect` need one too --
    they validate against the job schema -- so a caller of those would have been
    told to check a command they had not run.
    """
    obj = ctx.find_root().obj
    if obj is None or "app" not in obj:
        click.echo(
            f"Error: `{command}` needs the application, and no app context "
            f"is available here.",
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

    Needs no key. `key`, `origin`, `annotation`, `provider` and the
    timestamps are stored in clear on purpose so this command works on a
    machine that cannot open the store; only the value is encrypted.

    **`provider`, `annotation` and `synced_at` can be null.** They describe
    where a value was fetched *from*, and a value typed in by hand was not
    fetched from anywhere. This renderer used to assume all three were
    present — it measured `len(entry.provider)` and called
    `entry.synced_at.isoformat()` — and would raise on the first direct entry.
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
                        "origin": str(e.origin),
                        "annotation": e.annotation,
                        "provider": e.provider,
                        "created_at": e.created_at,
                        "updated_at": e.updated_at,
                        "synced_at": e.synced_at,
                    }
                    for e in entries
                ],
            }
        )
        return

    if not entries:
        click.echo(
            "The vault is empty. Store one with `func builtin vault put "
            "<job>.<field>`, or fill it from a provider with "
            "`func builtin vault sync`."
        )
        return

    def _origin_column(entry: Any) -> str:
        # A direct entry has no provider to name, so the origin is what a
        # reader needs in that column. Printing "None" would be an answer to a
        # question nobody asked.
        return entry.provider if entry.provider else str(entry.origin)

    def _when(entry: Any) -> str:
        stamp = entry.synced_at or entry.updated_at or entry.created_at
        return stamp.isoformat(timespec="seconds") if stamp else "-"

    key_width = max(len(e.key) for e in entries)
    origin_width = max(len(_origin_column(e)) for e in entries)
    for entry in entries:
        click.echo(
            f"{entry.key:<{key_width}}  "
            f"{_origin_column(entry):<{origin_width}}  "
            f"{_when(entry)}  {entry.annotation or ''}".rstrip()
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
                "direct_entries": report.direct_entries,
                "provider_entries": report.provider_entries,
                "key_matches_store": report.key_matches_store,
            }
        )
        return

    from functualize.app.utils import vault_duration

    click.echo(f"Path:         {report.path}")
    click.echo(f"Exists:       {'yes' if report.exists else 'no'}")
    click.echo(
        f"Entries:      {report.entry_count} "
        f"({report.direct_entries} direct, {report.provider_entries} synced)"
    )
    click.echo(f"Key provider: {report.key_provider or '(none available)'}")
    if report.age is not None:
        marker = "  ← stale" if report.stale else ""
        click.echo(f"Last synced:  {vault_duration(report.age)} ago{marker}")
    else:
        click.echo("Last synced:  never")
    click.echo(f"Max age:      {vault_duration(report.max_age)}")
    click.echo("Providers:    " + (", ".join(report.providers) or "(none registered)"))
    if report.key_matches_store is False:
        # The state that explains an otherwise baffling refusal at run time.
        # Nothing could report it before the check value existed.
        click.echo("")
        click.echo(
            "This vault was written with a different key, so its entries "
            "cannot be read.",
            err=True,
        )
        click.echo(
            "Refresh them with `func builtin vault sync`, or drop them with "
            "`func builtin vault remove <path>` / `clear` — neither needs a "
            "key.",
            err=True,
        )
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
@click.option(
    "--json", "json_out", is_flag=True, default=False, help="Emit the report as JSON."
)
def vault_clear_command(assume_yes: bool, json_out: bool) -> None:
    """Delete this project's whole vault. Needs no key.

    The sledgehammer to `remove`'s scalpel, and still the thing to reach for
    when a store cannot be opened at all.

    **The confirmation now says what would be lost, by kind.** A synced value
    comes back on the next `vault sync`; a value typed in through `vault put`
    has no upstream copy and is simply gone. Counting them together would put
    the two behind one number and let someone say yes to the wrong one.
    """
    from functualize.app.utils import vault_clear, vault_entries, vault_location

    path = vault_location()
    if not path.exists():
        if json_out:
            _vault_json(
                {
                    "ok": True,
                    "path": str(path),
                    "cleared": False,
                    "direct_entries": 0,
                    "provider_entries": 0,
                }
            )
        else:
            click.echo(f"No vault to clear at {path}")
        return

    from functualize.app.vault import VaultOrigin

    entries = vault_entries()
    direct = sum(1 for e in entries if e.origin is VaultOrigin.DIRECT)
    synced = len(entries) - direct

    if not assume_yes:
        click.echo(f"{path} holds {len(entries)} entries:")
        click.echo(f"  {synced} synced   — a `vault sync` refills these")
        if direct:
            click.echo(f"  {direct} direct   — typed in here, with no upstream copy")
        if not click.confirm("Delete all of them?", default=False):
            click.echo("Left alone.")
            return

    vault_clear()
    if json_out:
        _vault_json(
            {
                "ok": True,
                "path": str(path),
                "cleared": True,
                "direct_entries": direct,
                "provider_entries": synced,
            }
        )
        return
    click.echo(f"Cleared {path} ({direct} direct, {synced} synced).")


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
    from functualize.app.utils import (
        VaultKeyMismatchError,
        VaultKeyUnavailableError,
        vault_sync,
    )

    app = _vault_app(ctx, "vault sync")
    try:
        report = vault_sync(app)
    except VaultKeyMismatchError as exc:
        # Refused *before* writing, so the store is exactly as it was. The
        # orphan list is what makes this actionable rather than alarming.
        if json_out:
            _vault_json(
                {
                    "ok": False,
                    "reason": "key_mismatch",
                    "message": str(exc),
                    "would_orphan": list(exc.orphans),
                }
            )
        else:
            click.echo(f"Error: {exc}", err=True)
        raise SystemExit(ExitCode.REFUSED) from exc
    except VaultKeyUnavailableError as exc:
        if json_out:
            _vault_json({"ok": False, "reason": "key_unavailable", "message": str(exc)})
        else:
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


# --- The local lifecycle: init -> put -> run (ADR-023) -------------------
#
# These four reach `functualize.app.vault`, the public seam, and hold no
# opinion of their own about eligibility, key selection or provenance. A second
# opinion here is how `func` and an embedding application come to disagree
# about what a path means.


def _fail(
    reason: str,
    message: str,
    *,
    json_out: bool,
    code: ExitCode,
    path: str | None = None,
) -> None:
    """Emit one failure shape and exit.

    JSON mode returns an envelope with a stable `reason`, so a caller
    classifies a failure without parsing prose — `contracts.md` §3. Human mode
    writes the same message to stderr. Neither carries a value: every caller
    below constructs `message` from metadata only.
    """
    if json_out:
        payload: dict[str, Any] = {"ok": False, "reason": reason, "message": message}
        if path is not None:
            payload["path"] = path
        _vault_json(payload)
    else:
        click.echo(f"Error: {message}", err=True)
    raise SystemExit(code)


def _read_secret(
    *, use_stdin: bool, file: str | None, json_out: bool, path: str
) -> str:
    """Obtain the value, or refuse in a way that never hangs.

    The non-TTY refusal is the one that matters. Reading stdin implicitly when
    it is not a terminal would make `func builtin vault put x.y` inside a
    pipeline block forever on input nobody is sending, and an unattended run
    that blocks is worse than one that fails.
    """
    import sys

    if use_stdin and file:
        _fail(
            "conflicting_input_sources",
            "--stdin and --file cannot both be given.",
            json_out=json_out,
            code=ExitCode.USAGE,
            path=path,
        )

    if file:
        from pathlib import Path

        try:
            value = Path(file).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            _fail(
                "invalid_utf8",
                f"{file} is not valid UTF-8. This increment stores text; "
                f"binary values are out of scope.",
                json_out=json_out,
                code=ExitCode.USAGE,
                path=path,
            )
        except OSError as exc:
            _fail(
                "input_source_required",
                f"Could not read {file}: {exc.strerror}.",
                json_out=json_out,
                code=ExitCode.USAGE,
                path=path,
            )
    elif use_stdin:
        raw = sys.stdin.read()
        # Exactly one trailing newline, because `echo` adds one and a secret
        # that silently gained a "\n" authenticates nowhere. Anything else --
        # interior newlines, a deliberate blank last line -- is preserved.
        if raw.endswith("\r\n"):
            value = raw[:-2]
        elif raw.endswith("\n"):
            value = raw[:-1]
        else:
            value = raw
    elif sys.stdin.isatty() and sys.stdout.isatty():
        value = click.prompt("Value", hide_input=True, show_default=False)
    else:
        _fail(
            "input_source_required",
            "Not a terminal, so there is nothing to prompt. Pass --stdin or "
            "--file. Refusing rather than reading stdin implicitly: a pipeline "
            "that blocks on input nobody is sending never reports anything.",
            json_out=json_out,
            code=ExitCode.USAGE,
            path=path,
        )

    if not value:
        _fail(
            "empty_value",
            "An empty value is refused. Use `vault remove` to clear an entry.",
            json_out=json_out,
            code=ExitCode.USAGE,
            path=path,
        )
    return value


@vault_app.command("init")
@click.option(
    "--key-source",
    default=None,
    help="Which key provider to use, e.g. 'env' or 'keychain'.",
)
@click.option("--json", "json_out", is_flag=True, default=False, help="Emit JSON.")
def vault_init_command(key_source: str | None, json_out: bool) -> None:
    """Ensure this machine has a vault key. Never prints it.

    Needs no app and no project: one key opens every project's vault, so this
    is run once per machine. It is a preflight, never a gate — `put` and `sync`
    work without it whenever a key is already resolvable.
    """
    from functualize.app.vault import VaultKeySourceError, vault_init

    try:
        report = vault_init(key_source=key_source)
    except VaultKeySourceError as exc:
        _fail(exc.reason, str(exc), json_out=json_out, code=ExitCode.REFUSED)
        return

    if json_out:
        _vault_json(
            {
                "ok": True,
                "key_scope": report.key_scope,
                "key_provider": report.key_provider,
                "created": report.created,
            }
        )
        return

    # Says which of the two things happened. A generic "initialized" would read
    # as "a key was created" in the `--key-source env` case, where nothing was
    # written anywhere.
    if report.created:
        click.echo(f"Created a vault key in the {report.key_provider!r} key store.")
        click.echo("It opens every project's vault on this machine.")
    else:
        click.echo(f"A vault key is already available from {report.key_provider!r}.")
        click.echo("Nothing was written.")


@vault_app.command("put")
@click.argument("path")
@click.option("--stdin", "use_stdin", is_flag=True, default=False, help="Read stdin.")
@click.option("--file", default=None, help="Read the value from a file.")
@click.option("--replace", is_flag=True, default=False, help="Overwrite an entry.")
@click.option("--json", "json_out", is_flag=True, default=False, help="Emit JSON.")
@click.pass_context
def vault_put_command(
    ctx: click.Context,
    path: str,
    use_stdin: bool,
    file: str | None,
    replace: bool,
    json_out: bool,
) -> None:
    """Store one secret at PATH, e.g. `deploy.api_token`.

    PATH is validated against the job schema **before** the value is read, so a
    typo costs you nothing you have already typed.
    """
    from functualize.app.vault import (
        VaultEntryExistsError,
        VaultKeySourceError,
        VaultOriginConflictError,
        VaultPathError,
        resolve_canonical_path,
        vault_put,
    )

    app = _vault_app(ctx, "vault put")

    try:
        resolved = resolve_canonical_path(app, path)
    except VaultPathError as exc:
        _fail(exc.reason, str(exc), json_out=json_out, code=ExitCode.USAGE, path=path)
        return

    value = _read_secret(
        use_stdin=use_stdin, file=file, json_out=json_out, path=resolved.path
    )

    try:
        report = vault_put(app, resolved.path, value, replace=replace)
    except VaultEntryExistsError as exc:
        _fail(
            "entry_exists",
            str(exc),
            json_out=json_out,
            code=ExitCode.REFUSED,
            path=resolved.path,
        )
        return
    except VaultOriginConflictError as exc:
        _fail(
            "provider_entry_conflict",
            str(exc),
            json_out=json_out,
            code=ExitCode.REFUSED,
            path=resolved.path,
        )
        return
    except VaultKeySourceError as exc:
        _fail(
            exc.reason,
            str(exc),
            json_out=json_out,
            code=ExitCode.REFUSED,
            path=resolved.path,
        )
        return

    if json_out:
        _vault_json(
            {
                "ok": True,
                "path": report.path,
                "origin": str(report.origin) if report.origin else None,
                "created": report.created,
                "replaced": report.replaced,
                "updated_at": report.updated_at,
            }
        )
        return
    click.echo(f"Stored {report.path} ({'replaced' if report.replaced else 'new'}).")


@vault_app.command("inspect")
@click.argument("path")
@click.option("--json", "json_out", is_flag=True, default=False, help="Emit JSON.")
@click.pass_context
def vault_inspect_command(ctx: click.Context, path: str, json_out: bool) -> None:
    """Explain PATH: eligibility, provenance, freshness — never the value.

    Readability comes from the store's key check value, so this reports whether
    a key opens the vault without decrypting anything stored in it.
    """
    from functualize.app.vault import vault_inspect

    report = vault_inspect(_vault_app(ctx, "vault inspect"), path)

    if json_out:
        _vault_json(
            {
                "ok": True,
                "path": report.path,
                "eligible": report.eligible,
                "exists": report.exists,
                "origin": str(report.origin) if report.origin else None,
                "provider": report.provider,
                "reference": report.reference,
                "created_at": report.created_at,
                "updated_at": report.updated_at,
                "synced_at": report.synced_at,
                "key_provider": report.key_provider,
                "readability": str(report.readability),
                "stale": report.stale,
                "winning_source": str(report.winning_source),
            }
        )
        return

    click.echo(f"Path:       {report.path}")
    click.echo(f"Eligible:   {'yes' if report.eligible else 'no'}")
    click.echo(f"Stored:     {'yes' if report.exists else 'no'}")
    if report.exists:
        click.echo(f"Origin:     {report.origin}")
        if report.provider:
            click.echo(f"Provider:   {report.provider}")
        if report.reference:
            click.echo(f"Reference:  {report.reference}")
        click.echo(f"Readable:   {report.readability}")
        click.echo(f"Would win:  {report.winning_source}")


@vault_app.command("remove")
@click.argument("path")
@click.option("--yes", "assume_yes", is_flag=True, default=False, help="No prompt.")
@click.option("--json", "json_out", is_flag=True, default=False, help="Emit JSON.")
@click.pass_context
def vault_remove_command(
    ctx: click.Context, path: str, assume_yes: bool, json_out: bool
) -> None:
    """Remove the entry at PATH. Needs no vault key.

    Works on a store this machine cannot open, which is the situation it exists
    for. A direct value has no upstream copy, so removing one warns.
    """
    import sys

    from functualize.app.vault import vault_remove

    app = _vault_app(ctx, "vault remove")

    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    if not assume_yes:
        if not interactive:
            _fail(
                "confirmation_required",
                "Removing an entry is destructive and this is not a terminal. "
                "Pass --yes.",
                json_out=json_out,
                code=ExitCode.REFUSED,
                path=path,
            )
            return
        if not click.confirm(f"Remove {path}?", default=False):
            click.echo("Left alone.")
            return

    report = vault_remove(app, path)

    if json_out:
        _vault_json(
            {
                "ok": True,
                "path": report.path,
                "origin": str(report.origin) if report.origin else None,
                "removed": report.removed,
                **({"warning": report.warning} if report.warning else {}),
            }
        )
        return

    if not report.removed:
        click.echo(f"Nothing stored at {report.path}.")
        return
    click.echo(f"Removed {report.path} ({report.origin}).")
    if report.warning:
        click.echo(f"Warning: {report.warning}", err=True)
