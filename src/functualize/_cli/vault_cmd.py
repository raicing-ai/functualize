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

import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, NoReturn

import click

from functualize.app.utils import ExitCode

if TYPE_CHECKING:
    from functualize.app.vault_handoff import ImportRow

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
    help="Sync and inspect this project's vault; share and redeem through the FuncCloud Vault.",
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
    """List what the vault holds — scope, target, field and freshness, never values.

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
    from functualize.app.vault import VaultFormatError

    try:
        entries = vault_entries()
    except VaultFormatError as exc:
        _refuse_legacy(exc, json_out=json_out)

    if json_out:
        _vault_json(
            {
                "path": str(vault_location()),
                "entries": [
                    {
                        "key": e.key,
                        **_entry_identity(e.key),
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
            "--group <path> --field <name>` (or `--job <path>`), or fill it "
            "from a provider with `func builtin vault sync`."
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

    rows = [
        (*_identity_columns(e.key), _origin_column(e), _when(e), e.annotation or "")
        for e in entries
    ]
    widths = [max(len(row[i]) for row in rows) for i in range(5)]
    for row in rows:
        cells = [cell.ljust(width) for cell, width in zip(row[:5], widths, strict=True)]
        click.echo("  ".join([*cells, row[5], row[6]]).rstrip())


def _entry_identity(key: str) -> dict[str, str | None]:
    """A stored key's scope, target and field, or nulls if it has none.

    Every entry a scoped writer stores decodes. A row that does not is shown
    under its raw key rather than guessed into a scope.
    """
    from functualize.app.vault import VaultIdentity

    try:
        identity = VaultIdentity.decode(key)
    except ValueError:
        return {"scope": None, "target": None, "field": None, "environment": None}
    return {**_identity_fields(identity)}


def _identity_columns(key: str) -> tuple[str, str, str, str]:
    decoded = _entry_identity(key)
    if decoded["scope"] is None:
        return ("-", key, "-", "-")
    return (
        str(decoded["scope"]),
        str(decoded["target"]),
        str(decoded["field"]),
        str(decoded["environment"]),
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
    asking. The key is resolved silently, so this never raises a keychain
    prompt and never waits on one: a locked keyring is reported as
    ``locked``, not opened.
    """
    from functualize.app.utils import vault_status
    from functualize.app.vault import VaultFormatError

    obj = ctx.find_root().obj
    app = obj.get("app") if isinstance(obj, dict) else None
    try:
        report = vault_status(app)
    except VaultFormatError as exc:
        _refuse_legacy(exc, json_out=json_out)

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
                "key_state": report.key_state,
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
    click.echo(f"Key state:    {report.key_state or '(no vault)'}")
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
        # The recoveries that keep the secrets come first. `remove`/`clear`
        # come last, with what they cost: they destroy the entry, and a direct
        # one has no upstream copy for `sync` to restore.
        click.echo(
            "Supply the key it was written with — export "
            "$FUNCTUALIZE_VAULT_KEY, or restore it to the OS keyring.",
            err=True,
        )
        if report.provider_entries:
            click.echo(
                "Entries a provider wrote can be refetched with "
                "`func builtin vault sync`.",
                err=True,
            )
        only_copy = (
            f"; the {report.direct_entries} typed in by hand have no other copy"
            if report.direct_entries
            else ""
        )
        click.echo(
            "Last resort: `func builtin vault remove --group|--job <path> "
            "--field <name>` / `clear` need no key, but they destroy the "
            f"stored values{only_copy}.",
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

    from functualize.app.vault import VaultFormatError, VaultOrigin

    # An old-format store cannot be listed — that is why it is being cleared —
    # so its counts are unknown rather than zero.
    direct: int | None
    synced: int | None
    try:
        entries = vault_entries()
    except VaultFormatError:
        direct = synced = None
    else:
        direct = sum(1 for e in entries if e.origin is VaultOrigin.DIRECT)
        synced = len(entries) - direct

    if not assume_yes:
        if direct is None or synced is None:
            click.echo(
                f"{path} uses the old format, from before scoped secrets; its "
                f"entries cannot be listed or migrated."
            )
            click.echo("  Direct values in it have no upstream copy.")
        else:
            click.echo(f"{path} holds {direct + synced} entries:")
            click.echo(f"  {synced} synced   — a `vault sync` refills these")
            if direct:
                click.echo(
                    f"  {direct} direct   — typed in here, with no upstream copy"
                )
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
    if direct is None:
        click.echo(f"Cleared {path} (old format).")
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
    """Fetch explicit scoped declarations from their providers and store them.

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
    from functualize.app.vault import VaultFormatError, VaultIdentity

    def fields(key: str) -> dict[str, str]:
        identity = VaultIdentity.decode(key)
        return _identity_fields(identity)

    def label(key: str) -> str:
        identity = VaultIdentity.decode(key)
        return f"{_describe(identity)} ({identity.environment or 'base'})"

    app = _vault_app(ctx, "vault sync")
    try:
        report = vault_sync(app)
    except ValueError as exc:
        if json_out:
            _vault_json(
                {"ok": False, "reason": "invalid_declaration", "message": str(exc)}
            )
        else:
            click.echo(f"Error: {exc}", err=True)
        raise SystemExit(ExitCode.REFUSED) from exc
    except VaultFormatError as exc:
        _refuse_legacy(exc, json_out=json_out)
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
            _vault_json({"ok": False, "reason": exc.reason, "message": str(exc)})
        else:
            click.echo(f"Error: {exc}", err=True)
        raise SystemExit(ExitCode.REFUSED) from exc

    if json_out:
        _vault_json(
            {
                "path": str(report.path),
                "scanned": report.scanned,
                "synced": [{**fields(k), "provider": p} for k, p in report.synced],
                "failed": [{**fields(k), "reason": r} for k, r in report.failed],
                "unresolved": [
                    {
                        **fields(u.key),
                        "providers": list(u.providers),
                    }
                    for u in report.unresolved
                ],
                "ok": report.ok,
            }
        )
    else:
        for key, provider in report.synced:
            click.echo(f"  synced   {label(key)}  ({provider})")
        for key, reason in report.failed:
            click.echo(f"  FAILED   {label(key)}  — {reason}", err=True)
        for item in report.unresolved:
            click.echo(
                f"  MISSING  {label(item.key)}  — no plugin registers "
                f"{', '.join(item.providers)}",
                err=True,
            )
        if not report.synced and not report.failed and not report.unresolved:
            click.echo(
                f"Nothing declared in {report.scanned} vault secret "
                f"blocks. Nothing to sync."
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
# about what an identity means.
#
# An entry is named by group, leaf job and field flags, never by one dotted
# job value. A group and a job sharing a name stay two entries.


def _fail(
    reason: str,
    message: str,
    *,
    json_out: bool,
    code: ExitCode,
    identity: Any = None,
) -> NoReturn:
    """Emit one failure shape and exit.

    JSON mode returns an envelope with a stable `reason`, so a caller
    classifies a failure without parsing prose — `contracts.md` §3. Human mode
    writes the same message to stderr. Neither carries a value: every caller
    below constructs `message` from metadata only.
    """
    if json_out:
        payload: dict[str, Any] = {"ok": False, "reason": reason, "message": message}
        if identity is not None:
            payload.update(_identity_fields(identity))
        _vault_json(payload)
    else:
        click.echo(f"Error: {message}", err=True)
    raise SystemExit(code)


def _identity_fields(identity: Any) -> dict[str, str]:
    """The decomposed identity a report carries. Callers never parse a key."""
    return {
        "scope": identity.scope,
        "target": identity.target,
        "field": identity.field,
        "environment": identity.environment or "base",
    }


def _environment_fields(app: Any) -> dict[str, str]:
    """Name the selected or defaulted slot without exposing a value."""
    return {
        "active_environment": app.configuration.active_environment().casefold(),
        "environment_source": app.configuration.environment_source().value,
    }


def _describe(identity: Any) -> str:
    """One readable line naming an identity, in the flags that address it."""
    if identity.scope == "job" and "." in identity.target:
        group, job = identity.target.rsplit(".", 1)
        return f"--group {group} --job {job} --field {identity.field}"
    return f"--{identity.scope} {identity.target} --field {identity.field}"


def _refuse_legacy(exc: Exception, *, json_out: bool) -> NoReturn:
    """The store predates scoped identities. Nothing was read or changed."""
    _fail(
        "vault_format_unsupported", str(exc), json_out=json_out, code=ExitCode.REFUSED
    )


def _scoped(command: Any) -> Any:
    """Add the three flags every single-entry command shares."""
    command = click.option(
        "--field",
        "field",
        required=True,
        metavar="NAME",
        help="The secret field on that target, e.g. `api_token`.",
    )(command)
    command = click.option(
        "--job",
        "job",
        default=None,
        metavar="NAME",
        help="A leaf job name, e.g. `web`; pair with --group for grouped jobs.",
    )(command)
    return click.option(
        "--group",
        "group",
        default=None,
        metavar="PATH",
        help="A command group's path, e.g. `deploy`, for a group option.",
    )(command)


def _identity(group: str | None, job: str | None, field: str, *, json_out: bool) -> Any:
    """The identity as typed, accepting a group and leaf job together.

    `inspect` and `remove` use this rather than validating against the live
    schema: `inspect` exists to explain an ineligible identity, and `remove`
    must reach an orphan whose job or group has been deleted.
    """
    from functualize.app.vault import VaultIdentity

    if group is None and job is None:
        _fail(
            "scope_required",
            "Supply --group, --job, or both --group and --job.",
            json_out=json_out,
            code=ExitCode.USAGE,
        )
    if job is not None and "." in job:
        _fail(
            "dotted_job",
            "--job must be a leaf name; use --group deploy --job web.",
            json_out=json_out,
            code=ExitCode.USAGE,
        )
    scope: Literal["group", "job"]
    if job is not None:
        scope = "job"
        target = f"{group}.{job}" if group is not None else job
    else:
        scope, target = "group", group or ""
    try:
        return VaultIdentity(scope, target or "", field)
    except ValueError:
        _fail(
            "scope_required",
            f"--{scope} and --field each need a non-empty value.",
            json_out=json_out,
            code=ExitCode.USAGE,
        )


def _read_secret(
    *, use_stdin: bool, file: str | None, json_out: bool, identity: Any
) -> str:
    """Obtain the value, or refuse in a way that never hangs.

    The non-TTY refusal is the one that matters. Reading stdin implicitly when
    it is not a terminal would make `func builtin vault put --job x --field y`
    inside a pipeline block forever on input nobody is sending, and an
    unattended run that blocks is worse than one that fails.
    """
    import sys

    if use_stdin and file:
        _fail(
            "conflicting_input_sources",
            "--stdin and --file cannot both be given.",
            json_out=json_out,
            code=ExitCode.USAGE,
            identity=identity,
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
                identity=identity,
            )
        except OSError as exc:
            _fail(
                "input_source_required",
                f"Could not read {file}: {exc.strerror}.",
                json_out=json_out,
                code=ExitCode.USAGE,
                identity=identity,
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
            identity=identity,
        )

    if not value:
        _fail(
            "empty_value",
            "An empty value is refused. Use `vault remove` to clear an entry.",
            json_out=json_out,
            code=ExitCode.USAGE,
            identity=identity,
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


@vault_app.command("unlock")
@click.option("--json", "json_out", is_flag=True, default=False, help="Emit JSON.")
@click.pass_context
def vault_unlock_command(ctx: click.Context, json_out: bool) -> None:
    """Unlock the keyring for the vault key, waiting as long as it takes.

    For a run that was refused because the keyring is locked: run this in a
    terminal, answer the keyring's own unlock dialog, and every later run —
    piped, from an agent, over stdio MCP — reads the key silently for as long
    as the keyring stays unlocked. The keyring decides how long that is;
    functualize keeps no copy and runs no timer.

    This is the only command that asks the keyring to unlock. It waits for the
    dialog to be answered or cancelled there; interrupt once and it keeps
    waiting, interrupt twice to stop. Never prints the key.
    """
    from functualize.app.vault import (
        UnlockAbandonedError,
        VaultKeySourceError,
        vault_unlock,
    )

    obj = ctx.find_root().obj
    app = obj.get("app") if isinstance(obj, dict) else None
    try:
        lookup = vault_unlock(app)
    except UnlockAbandonedError as exc:
        _fail(exc.reason, str(exc), json_out=json_out, code=ExitCode.REFUSED)
        return
    except VaultKeySourceError as exc:
        _fail(exc.reason, str(exc), json_out=json_out, code=ExitCode.REFUSED)
        return

    # `unlock_how` is an internal enum; its value is the documented reason.
    how = getattr(lookup.unlock_how, "value", None)
    from_env = lookup.provider_id == "env"
    reason = (
        "already_unlocked" if from_env or how in (None, "already_unlocked") else how
    )
    if json_out:
        _vault_json({"ok": True, "reason": reason, "provider": lookup.provider_id})
        return
    if from_env:
        click.echo(
            "The vault key is available from $FUNCTUALIZE_VAULT_KEY; there is "
            "nothing to unlock."
        )
    elif reason == "unlocked":
        click.echo(
            "Unlocked. The vault key is available from the system keyring, and "
            "runs read it silently while the keyring stays unlocked."
        )
    elif reason == "nothing_to_unlock":
        click.echo(
            "Nothing to unlock: this system's keyring has no locked state. The "
            "vault key is available from it."
        )
    else:
        click.echo(
            "The keyring is already unlocked; the vault key is available from it."
        )


@vault_app.command("put")
@_scoped
@click.option("--stdin", "use_stdin", is_flag=True, default=False, help="Read stdin.")
@click.option("--file", default=None, help="Read the value from a file.")
@click.option("--replace", is_flag=True, default=False, help="Overwrite an entry.")
@click.option("--json", "json_out", is_flag=True, default=False, help="Emit JSON.")
@click.pass_context
def vault_put_command(
    ctx: click.Context,
    group: str | None,
    job: str | None,
    field: str,
    use_stdin: bool,
    file: str | None,
    replace: bool,
    json_out: bool,
) -> None:
    """Store one secret group option or job config field.

    \b
      func builtin vault put --group deploy --field token
      func builtin vault put --group deploy --job service --field iam_key --stdin

    The target and field are validated against the live schema **before** the
    value is read, so a typo costs you nothing you have already typed.
    """
    from functualize.app.utils import vault_entries
    from functualize.app.vault import (
        VaultEntryExistsError,
        VaultFormatError,
        VaultIdentity,
        VaultKeySourceError,
        VaultOriginConflictError,
        VaultPathError,
        resolve_vault_identity,
        vault_put,
    )

    app = _vault_app(ctx, "vault put")

    try:
        identity = resolve_vault_identity(app, group=group, job=job, field=field)
    except VaultPathError as exc:
        _fail(exc.reason, str(exc), json_out=json_out, code=ExitCode.USAGE)
    identity = VaultIdentity(
        identity.scope,
        identity.target,
        identity.field,
        app.configuration.active_environment(),
    )

    # Also before the value is read: a store this version cannot write would
    # otherwise cost the operator a secret they had just typed.
    try:
        vault_entries()
    except VaultFormatError as exc:
        _refuse_legacy(exc, json_out=json_out)

    value = _read_secret(
        use_stdin=use_stdin, file=file, json_out=json_out, identity=identity
    )

    try:
        report = vault_put(app, identity, value, replace=replace)
    except VaultEntryExistsError as exc:
        _fail(
            "entry_exists",
            str(exc),
            json_out=json_out,
            code=ExitCode.REFUSED,
            identity=identity,
        )
    except VaultOriginConflictError as exc:
        _fail(
            "provider_entry_conflict",
            str(exc),
            json_out=json_out,
            code=ExitCode.REFUSED,
            identity=identity,
        )
    except VaultKeySourceError as exc:
        _fail(
            exc.reason,
            str(exc),
            json_out=json_out,
            code=ExitCode.REFUSED,
            identity=identity,
        )
    except VaultFormatError as exc:
        _refuse_legacy(exc, json_out=json_out)

    if json_out:
        _vault_json(
            {
                "ok": True,
                **_identity_fields(report.identity),
                **_environment_fields(app),
                "origin": str(report.origin) if report.origin else None,
                "created": report.created,
                "replaced": report.replaced,
                "updated_at": report.updated_at,
            }
        )
        return
    state = "replaced" if report.replaced else "new"
    click.echo(
        f"Stored {_describe(report.identity)} "
        f"({report.identity.environment or 'base'}, {state}; "
        f"{_environment_fields(app)['environment_source']})."
    )


@vault_app.command("inspect")
@_scoped
@click.option("--json", "json_out", is_flag=True, default=False, help="Emit JSON.")
@click.pass_context
def vault_inspect_command(
    ctx: click.Context,
    group: str | None,
    job: str | None,
    field: str,
    json_out: bool,
) -> None:
    """Explain one entry: eligibility, provenance, freshness — never the value.

    \b
      func builtin vault inspect --group deploy --field token

    Readability comes from the store's key check value, so this reports whether
    a key opens the vault without decrypting anything stored in it.
    """
    from functualize.app.vault import VaultFormatError, vault_inspect

    identity = _identity(group, job, field, json_out=json_out)
    app = _vault_app(ctx, "vault inspect")
    try:
        report = vault_inspect(app, identity)
    except VaultFormatError as exc:
        _refuse_legacy(exc, json_out=json_out)

    if json_out:
        _vault_json(
            {
                "ok": True,
                **_identity_fields(report.identity),
                **_environment_fields(app),
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

    click.echo(f"Scope:      {report.identity.scope}")
    click.echo(f"Target:     {report.identity.target}")
    click.echo(f"Field:      {report.identity.field}")
    click.echo(f"Environment:{' ':<2}{report.identity.environment or 'base'}")
    click.echo(
        f"Selected:   {_environment_fields(app)['active_environment']} "
        f"({_environment_fields(app)['environment_source']})"
    )
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
@_scoped
@click.option("--yes", "assume_yes", is_flag=True, default=False, help="No prompt.")
@click.option("--json", "json_out", is_flag=True, default=False, help="Emit JSON.")
@click.pass_context
def vault_remove_command(
    ctx: click.Context,
    group: str | None,
    job: str | None,
    field: str,
    assume_yes: bool,
    json_out: bool,
) -> None:
    """Remove one entry. Needs no vault key.

    \b
      func builtin vault remove --group deploy --job service --field iam_key --yes

    Works on a store this machine cannot open, and on an entry whose job or
    group no longer exists, which are the situations it exists for. A direct
    value has no upstream copy, so removing one warns.
    """
    import sys

    from functualize.app.vault import VaultFormatError, vault_remove

    app = _vault_app(ctx, "vault remove")
    typed = _identity(group, job, field, json_out=json_out)
    from functualize.app.vault import VaultIdentity

    identity = VaultIdentity(
        typed.scope,
        typed.target,
        typed.field,
        app.configuration.active_environment(),
    )

    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    if not assume_yes:
        if not interactive:
            _fail(
                "confirmation_required",
                "Removing an entry is destructive and this is not a terminal. "
                "Pass --yes.",
                json_out=json_out,
                code=ExitCode.REFUSED,
                identity=identity,
            )
        if not click.confirm(f"Remove {_describe(identity)}?", default=False):
            click.echo("Left alone.")
            return

    try:
        report = vault_remove(app, identity)
    except VaultFormatError as exc:
        _refuse_legacy(exc, json_out=json_out)

    if json_out:
        _vault_json(
            {
                "ok": True,
                **_identity_fields(report.identity),
                **_environment_fields(app),
                "origin": str(report.origin) if report.origin else None,
                "removed": report.removed,
                **({"warning": report.warning} if report.warning else {}),
            }
        )
        return

    if not report.removed:
        click.echo(f"Nothing stored at {_describe(report.identity)}.")
        return
    click.echo(f"Removed {_describe(report.identity)} ({report.origin}).")
    if report.warning:
        click.echo(f"Warning: {report.warning}", err=True)


# --- Remote sharing: `func builtin vault share` / `redeem` / `show` -------
#
# Thin by design (spec A3): every decision lives in
# `functualize.app.vault_handoff`, every wire call in
# `functualize.app.vault_remote`. What stays here is flags, the checklist
# prompt, and rendering.
#
# Values appear only where the design says they may: in `redeem --print-only`
# export lines on the receiver's own terminal, and in a `--dotenv` file. Never
# in `--json`, in `share`'s output, or in any error message.


def _remote_fail(
    exc: Exception, json_out: bool, *, after_burn: bool = False
) -> NoReturn:
    """One failure shape for every remote-vault refusal.

    Selector and usage mistakes exit ``USAGE``; everything else ``REFUSED``.
    A failure after the redemption was consumed says so, because the link
    the user is holding no longer works.
    """
    from functualize.app.vault import VaultPathError

    reason = getattr(exc, "reason", "vault_error")
    usage = isinstance(exc, VaultPathError) or reason in _USAGE_REASONS
    message = str(exc)
    if after_burn:
        message += " The link's redemption was already used."
    _fail(
        reason,
        message,
        json_out=json_out,
        code=ExitCode.USAGE if usage else ExitCode.REFUSED,
    )


_USAGE_REASONS = frozenset(
    {
        "bad_expiry",
        "bad_label",
        "bad_link",
        "conflicting_options",
        "no_project",
        "no_selection",
        "no_tty_confirmation",
    }
)


def _interactive(json_out: bool) -> bool:
    """A person is at a terminal and output is not machine-read."""
    return not json_out and sys.stdin.isatty() and sys.stdout.isatty()


def _maybe_warn_origin(origin: str) -> None:
    """Threat T5.1: a link to a different origin than the configured one.

    Warns, never blocks — the fragment is what protects the values, and the
    receiver may be intentionally redeeming from a self-hosted vault. The
    share id does travel to the link's origin either way; the warning says
    so.
    """
    from functualize.app.vault_remote import resolve_origin

    configured = resolve_origin()
    if origin != configured:
        click.echo(
            f"Note: this link points at {origin}, not the configured "
            f"{configured}. Only the share id is sent there; the values "
            f"decrypt locally.",
            err=True,
        )


@dataclass
class _CheckRow:
    """One line of the checklist: a header (covers several entries) or an entry."""

    text: str
    covers: list[int]
    selectable: bool = True
    note: str | None = None
    header: bool = False


def _checklist_rows(
    entries: list[tuple[str | None, str | None, str, bool, str | None]],
) -> list[_CheckRow]:
    """Group entries under group and job headers.

    ``entries`` are ``(group, job, text, selectable, note)``. A group header
    covers its whole subtree (spec A4: "a group or job header row toggles
    everything under it"); a job header covers that job's fields.
    """

    def _in(group: str | None, root: str) -> bool:
        return group is not None and (group == root or group.startswith(root + "."))

    rows: list[_CheckRow] = []
    seen_groups: set[str] = set()
    seen_jobs: set[tuple[str | None, str]] = set()
    order = sorted(
        range(len(entries)),
        key=lambda i: (entries[i][0] or "", entries[i][1] or "", entries[i][2]),
    )
    for i in order:
        group, job, text, selectable, note = entries[i]
        if group is not None and group not in seen_groups:
            seen_groups.add(group)
            covered = [j for j, e in enumerate(entries) if _in(e[0], group) and e[3]]
            rows.append(
                _CheckRow(f"group {group}", covered, bool(covered), header=True)
            )
        if job is not None and (group, job) not in seen_jobs:
            seen_jobs.add((group, job))
            covered = [
                j
                for j, e in enumerate(entries)
                if e[0] == group and e[1] == job and e[3]
            ]
            rows.append(_CheckRow(f"  job {job}", covered, bool(covered), header=True))
        indent = "    " if job is not None else ("  " if group is not None else "")
        rows.append(_CheckRow(f"{indent}{text}", [i], selectable, note))
    return rows


def _parse_picks(text: str, count: int) -> list[int] | None:
    """``1,3,5-7`` → zero-based row positions, or ``None`` if malformed."""
    picks: list[int] = []
    for part in text.replace(" ", "").split(","):
        if not part:
            continue
        low, sep, high = part.partition("-")
        if not low.isdigit() or (sep and not high.isdigit()):
            return None
        start, end = int(low), int(high) if sep else int(low)
        if not 1 <= start <= end <= count:
            return None
        picks.extend(range(start - 1, end))
    return picks


def _checklist(
    title: str, rows: list[_CheckRow], preselected: set[int]
) -> list[int] | None:
    """A terminal multi-select. Returns entry indices, or ``None`` if cancelled.

    Numbers and ranges toggle rows; a header toggles everything it covers;
    ``a`` ticks all, ``n`` none; Enter finishes; ``q`` cancels. The job
    prompt's multi-select lives in `_engine`, which `_cli` may not import, and
    has neither pre-ticked rows nor headers — hence this one.
    """
    selectable = {i for row in rows if row.selectable for i in row.covers}
    chosen = set(preselected) & selectable
    while True:
        click.echo(title, err=True)
        for number, row in enumerate(rows, 1):
            if not row.selectable:
                mark = "[-]"
            elif row.covers and all(i in chosen for i in row.covers):
                mark = "[x]"
            elif any(i in chosen for i in row.covers):
                mark = "[~]"
            else:
                mark = "[ ]"
            note = f"  — {row.note}" if row.note else ""
            click.echo(f"  {mark} {number:>2}  {row.text}{note}", err=True)
        answer = (
            click.prompt(
                "Toggle (e.g. 1,3,5-7) · a = all · n = none · Enter = done · q = cancel",
                default="",
                show_default=False,
                err=True,
            )
            .strip()
            .lower()
        )
        if answer == "":
            return sorted(chosen)
        if answer == "q":
            return None
        if answer == "a":
            chosen = set(selectable)
            continue
        if answer == "n":
            chosen = set()
            continue
        picks = _parse_picks(answer, len(rows))
        if picks is None:
            click.echo(f"  {answer!r} is not a list of row numbers.", err=True)
            continue
        for position in picks:
            row = rows[position]
            if not row.selectable:
                continue
            if all(i in chosen for i in row.covers):
                chosen -= set(row.covers)
            else:
                chosen |= set(row.covers)


@vault_app.command("share")
@click.option(
    "--entry",
    "entries",
    multiple=True,
    metavar="SELECTOR",
    help="What to share, e.g. group=deploy,field=token or group=deploy (its "
    "whole subtree). Repeatable.",
)
@click.option(
    "--all",
    "share_all",
    is_flag=True,
    default=False,
    help="Share every shareable entry.",
)
@click.option("--labels", default=None, help="Comma-separated labels, ≤7 × 64 chars.")
@click.option(
    "--expires",
    default="24h",
    help="Validity window, e.g. '1h', '90m', '2d' (1..168 whole hours).",
)
@click.option(
    "--redemptions",
    type=int,
    default=1,
    help="How many times the link may be redeemed (1..10).",
)
@click.option(
    "--origin", default=None, help="Vault origin; default $FUNC_VAULT_ORIGIN."
)
@click.option("--json", "json_out", is_flag=True, default=False, help="Emit JSON.")
@click.pass_context
def vault_share_command(
    ctx: click.Context,
    entries: tuple[str, ...],
    share_all: bool,
    labels: str | None,
    expires: str,
    redemptions: int,
    origin: str | None,
    json_out: bool,
) -> None:
    """Seal entries of this project's vault into one redeemable link.

    \b
      FUNCTUALIZE_ENV=prod func builtin vault share --entry group=deploy
      func builtin vault share --entry group=deploy.infra,job=app,field=api_token
      func builtin vault share --all
      func builtin vault share                      # pick in a checklist

    Only entries stored for the active environment are offered, and the link
    can only be redeemed into that same environment. Values are encrypted
    locally under a fresh key; the printed link carries that key — anyone
    holding the complete link can redeem.
    """
    from functualize.app.vault import VaultKeySourceError, VaultPathError
    from functualize.app.vault_handoff import (
        ALL,
        ShareSelection,
        parse_selector,
        select_for_share,
        share,
        shareable_entries,
    )
    from functualize.app.vault_remote import VaultRedeemError, parse_expiry

    app = _vault_app(ctx, "vault share")
    if entries and share_all:
        _fail(
            "conflicting_options",
            "--entry and --all choose entries two different ways; use one.",
            json_out=json_out,
            code=ExitCode.USAGE,
        )
    try:
        hours = parse_expiry(expires)
        if entries or share_all:
            selection = select_for_share(
                app, ALL if share_all else [parse_selector(e) for e in entries]
            )
            interactive = False
        elif _interactive(json_out):
            candidates = shareable_entries(app)
            rows = _checklist_rows(
                [
                    (
                        c.group,
                        c.job,
                        c.label,
                        c.shareable,
                        c.reason
                        or (f"synced from {c.synced_from}" if c.synced_from else None),
                    )
                    for c in candidates
                ]
            )
            env = app.configuration.active_environment()
            picked = _checklist(f"Share from {env} (nothing selected):", rows, set())
            if not picked:
                _fail(
                    "no_selection",
                    "Nothing was selected, so nothing was shared.",
                    json_out=json_out,
                    code=ExitCode.USAGE,
                )
            selection = ShareSelection(tuple(candidates[i] for i in picked))
            interactive = True
        else:
            _fail(
                "no_selection",
                "Choose what to share with --entry SELECTOR (repeatable) or "
                "--all; with no terminal there is no checklist to pick from.",
                json_out=json_out,
                code=ExitCode.USAGE,
            )
        if not interactive and not json_out:
            click.echo(
                f"Sharing {len(selection.chosen)} entr"
                f"{'y' if len(selection.chosen) == 1 else 'ies'}:",
                err=True,
            )
            for c in selection.chosen:
                click.echo(f"  {c.label}", err=True)
            for c in selection.skipped:
                click.echo(f"  skipped {c.label} — {c.reason}", err=True)
        label_list = [x.strip() for x in (labels or "").split(",") if x.strip()]
        report = share(
            app,
            selection,
            labels=label_list,
            redemptions=redemptions,
            expires_in_hours=hours,
            origin=origin,
        )
    except (VaultRedeemError, VaultPathError, VaultKeySourceError) as exc:
        _remote_fail(exc, json_out)

    if json_out:
        _vault_json(
            {
                "ok": True,
                "link": report.link,
                "share_id": report.share_id,
                "origin": report.origin,
                "labels": report.labels,
                "entries": [c.label for c in selection.chosen],
                "redemptions_allowed": report.redemptions_allowed,
                "expires_at": report.expires_at,
            }
        )
        return

    click.echo(report.link)
    click.echo(
        f"Labels: {', '.join(report.labels) or '(none)'} · "
        f"redemptions: {report.redemptions_allowed} · "
        f"expires: {report.expires_at}",
        err=True,
    )
    click.echo(
        "Anyone with this complete link can redeem it. Send it over a "
        "channel you trust as much as the values inside.",
        err=True,
    )


def _write_dotenv(path: str, lines: list[str], json_out: bool) -> None:
    import os

    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        os.chmod(path, 0o600)
    except OSError as exc:
        _fail(
            "dotenv_unwritable",
            f"Could not write {path}: {exc.strerror}. The link's redemption "
            f"was already used.",
            json_out=json_out,
            code=ExitCode.REFUSED,
        )


@vault_app.command("redeem")
@click.argument("link")
@click.option(
    "-y",
    "--yes",
    "yes",
    is_flag=True,
    default=False,
    help="Store every storable entry without asking.",
)
@click.option(
    "--only",
    "only",
    multiple=True,
    metavar="SELECTOR",
    help="Store only entries under this selector (as share --entry). Repeatable.",
)
@click.option(
    "--replace",
    is_flag=True,
    default=False,
    help="Also replace entries that already exist or were synced.",
)
@click.option(
    "--print-only",
    "print_only",
    is_flag=True,
    default=False,
    help="Print export lines; store nothing.",
)
@click.option(
    "--dotenv",
    "dotenv_path",
    default=None,
    metavar="PATH",
    help="Write a 0600 env file; store nothing in the vault.",
)
@click.option("--json", "json_out", is_flag=True, default=False, help="Emit JSON.")
@click.pass_context
def vault_redeem_command(
    ctx: click.Context,
    link: str,
    yes: bool,
    only: tuple[str, ...],
    replace: bool,
    print_only: bool,
    dotenv_path: str | None,
    json_out: bool,
) -> None:
    """Redeem a share link into this project's vault.

    \b
      FUNCTUALIZE_ENV=prod func builtin vault redeem <link>
      func builtin vault redeem <link> -y
      func builtin vault redeem <link> --only group=deploy --replace
      func builtin vault redeem <link> --print-only

    Everything that can be checked without spending the link is checked
    first: a project here, a way to confirm, the share still live, the same
    environment it was made for, and a vault key. Only then is one
    redemption consumed. Entries already stored, or written by `vault sync`,
    are listed unticked and replaced only when chosen.
    """
    from functualize.app.vault import VaultKeySourceError, VaultPathError
    from functualize.app.vault_handoff import (
        Materialize,
        RowStatus,
        apply_import,
        check_before_redeem,
        export_name,
        parse_selector,
        plan_import,
    )
    from functualize.app.vault_remote import (
        VaultRedeemError,
        parse_link,
        redeem_link,
    )

    if print_only and dotenv_path:
        _fail(
            "conflicting_options",
            "--print-only and --dotenv are two outputs; use one.",
            json_out=json_out,
            code=ExitCode.USAGE,
        )
    if (print_only or dotenv_path) and (yes or only or replace):
        _fail(
            "conflicting_options",
            "-y, --only and --replace choose what to store; --print-only and "
            "--dotenv store nothing.",
            json_out=json_out,
            code=ExitCode.USAGE,
        )
    if yes and only:
        _fail(
            "conflicting_options",
            "-y stores everything storable and --only a subset; use one.",
            json_out=json_out,
            code=ExitCode.USAGE,
        )

    materialize = (
        Materialize.PRINT
        if print_only
        else Materialize.DOTENV
        if dotenv_path
        else Materialize.STORE
    )
    app = _vault_app(ctx, "vault redeem")
    interactive = _interactive(json_out)

    try:
        selectors = [parse_selector(s) for s in only]
        origin, _share_id, _key = parse_link(link)
        if not json_out:
            _maybe_warn_origin(origin)
        meta = check_before_redeem(
            app,
            link,
            materialize=materialize,
            interactive=interactive,
            confirmed_without_prompt=yes or bool(only),
            only=selectors,
        )
    except (VaultRedeemError, VaultPathError, VaultKeySourceError) as exc:
        _remote_fail(exc, json_out)

    try:
        bundle = redeem_link(link)
    except VaultRedeemError as exc:
        _remote_fail(exc, json_out)

    used = meta.redemptions_total - meta.redemptions_left + 1
    summary = (
        f"Redeemed {len(bundle.items)} item(s) · redemption {used} of "
        f"{meta.redemptions_total} · expires {bundle.expires_at}"
    )

    if materialize is not Materialize.STORE:
        from functualize.app.vault import VaultIdentity

        lines: list[str] = []
        unnamed = 0
        for item in bundle.items:
            try:
                name = export_name(VaultIdentity.decode(str(item["name"])))
            except ValueError:
                unnamed += 1
                continue
            lines.append(f"{name}={item['value']}")
        if json_out:
            payload: dict[str, Any] = {
                "ok": True,
                "share_id": bundle.share_id,
                "labels": bundle.labels,
                "materialized": materialize.value,
                "names": [line.split("=", 1)[0] for line in lines],
                "unreadable": unnamed,
            }
            if dotenv_path:
                _write_dotenv(dotenv_path, lines, json_out)
                payload["dotenv"] = dotenv_path
            _vault_json(payload)
            return
        click.echo(summary, err=True)
        if unnamed:
            click.echo(
                f"  {unnamed} item(s) had unreadable names and were left out.", err=True
            )
        if dotenv_path:
            _write_dotenv(dotenv_path, lines, json_out)
            click.echo(
                f"Wrote {dotenv_path} (0600). Nothing was stored in the vault.",
                err=True,
            )
        else:
            for line in lines:
                click.echo(f"export {line}")
        return

    plan = plan_import(bundle, app)
    try:
        if selectors:
            chosen = plan.select(selectors, replace=replace)
            consent = replace
        elif yes:
            chosen = [
                row.index
                for row in plan.rows
                if row.status is RowStatus.STORABLE
                or (replace and row.status in (RowStatus.EXISTS, RowStatus.SYNCED))
            ]
            consent = replace
        else:
            preselected = {row.index for row in plan.rows if row.default_ticked}
            if replace:
                preselected |= {
                    row.index
                    for row in plan.rows
                    if row.status in (RowStatus.EXISTS, RowStatus.SYNCED)
                }
            rows = _checklist_rows(
                [
                    (
                        row.group,
                        row.job,
                        row.label,
                        row.status.selectable,
                        _row_note(row),
                    )
                    for row in plan.rows
                ]
            )
            click.echo(summary, err=True)
            picked = _checklist("Store into this project's vault:", rows, preselected)
            if not picked:
                click.echo(
                    "Nothing was stored. The link's redemption was already used.",
                    err=True,
                )
                return
            chosen = picked
            consent = True  # ticking an existing or synced row is the consent
        report = apply_import(app, plan, bundle, chosen, replace=consent)
    except (VaultRedeemError, VaultPathError, VaultKeySourceError) as exc:
        _remote_fail(exc, json_out, after_burn=True)

    skipped = [
        {"entry": row.label, "reason": _row_note(row) or "not selected"}
        for row in plan.rows
        if row.index not in set(chosen)
    ]
    if json_out:
        _vault_json(
            {
                "ok": True,
                "share_id": bundle.share_id,
                "labels": bundle.labels,
                "materialized": "vault",
                "stored": list(report.stored),
                "replaced": list(report.replaced),
                "superseded": list(report.superseded),
                "skipped": skipped,
                "redemptions_left_after": meta.redemptions_left - 1,
            }
        )
        return
    if selectors or yes:
        click.echo(summary, err=True)
    for label in report.stored:
        click.echo(f"  stored     {label}")
    for label in report.replaced:
        click.echo(f"  replaced   {label}")
    for label in report.superseded:
        click.echo(
            f"  replaced   {label} (was synced; vault sync will report it until removed)"
        )
    for item in skipped:
        click.echo(f"  skipped    {item['entry']} — {item['reason']}", err=True)


def _row_note(row: ImportRow) -> str | None:
    from functualize.app.vault_handoff import RowStatus

    if row.status is RowStatus.SYNCED:
        return f"synced from {row.synced_from}; {row.reason}"
    return row.reason


@vault_app.command("show")
@click.argument("link")
@click.option("--json", "json_out", is_flag=True, default=False, help="Emit JSON.")
def vault_show_command(link: str, json_out: bool) -> None:
    """Preview a share — labels, redemptions, expiry. Never redeems.

    Reads the meta endpoint only: the same thing a link-unfurler would
    hit, and guaranteed by the contract to spend nothing.
    """
    from functualize.app.vault_remote import (
        VaultRedeemError,
        fetch_share_meta,
        parse_link,
    )

    try:
        origin, share_id, _ = parse_link(link)
        if not json_out:
            _maybe_warn_origin(origin)
        meta = fetch_share_meta(origin, share_id)
    except VaultRedeemError as exc:
        _remote_fail(exc, json_out)
        return

    if json_out:
        _vault_json(
            {
                "ok": True,
                "labels": meta.labels,
                "redemptions_left": meta.redemptions_left,
                "redemptions_total": meta.redemptions_total,
                "expires_at": meta.expires_at,
                "created_at": meta.created_at,
            }
        )
        return

    def _when(raw: str) -> str:
        # The wire's meta timestamps are epoch seconds; a human reading
        # "Expires" should not have to do that arithmetic.
        from datetime import UTC, datetime

        try:
            return datetime.fromtimestamp(int(raw), tz=UTC).strftime(
                "%Y-%m-%d %H:%M UTC"
            )
        except ValueError:
            return raw

    click.echo(f"Labels:      {', '.join(meta.labels) or '(none)'}")
    click.echo(f"Redemptions: {meta.redemptions_left} of {meta.redemptions_total} left")
    click.echo(f"Expires:     {_when(meta.expires_at)}")
    click.echo(f"Created:     {_when(meta.created_at)}")
