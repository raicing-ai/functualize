"""The public, delivery-neutral seam for the local secrets vault.

Everything ``func builtin vault`` does, available to a ``FunctualizeApp``
directly. The CLI is one caller of this module, not the place the behavior
lives — which is the difference between a feature about *the program* and one
about *how you reach the program* (``contributor/architecture/surface-boundary.md``).

Why this is a new module rather than more of ``app/utils.py``
-------------------------------------------------------------

``app/utils.py`` already exports 130 names across job schemas, packaging, group
tries, run views and the existing vault helpers. It is the repository's clearest
case of **divergent change**, and adding a feature's worth of lifecycle to it
would deepen exactly that. The existing ``vault_*`` names stay where they are —
they are public and nothing is renamed — and the new ones start somewhere they
can be read as a unit.

Why it must be here and not in ``_config``
------------------------------------------

Deciding whether ``deploy.api_token`` is a real, eligible path needs the **job
schema**; storing the value needs ``_config.vault``. Those live in different
peer layers, and the import-linter contract *Peer layers are independent* means
no module in ``_config`` may reach the schema. A public module may reach both,
so this is where the two meet — and it reaches the schema *through the app
object* rather than by importing ``_engine`` or ``_discovery``, so no new edge
appears in the dependency graph at all.

No value ever leaves here
-------------------------

Every report type below carries metadata only. That is enforced by a test that
reflects over the dataclass fields, so a later field cannot reintroduce
plaintext by being added carelessly.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

# Re-exported, not re-defined. `_cli` may import only public API, so the
# delivery layer needs these names from somewhere public -- and there must
# be exactly one set of them, or a CLI `except` clause would silently stop
# catching what the store actually raises.
from functualize._config.vault import (
    VaultEntryExistsError,
    VaultEntryUnreadableError,
    VaultError,
    VaultOrigin,
    VaultOriginConflictError,
)

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from functualize._config.vault import SecretsVault
    from functualize._config.vault_keys import KeyResolution

__all__ = [
    "Readability",
    "ResolvedVaultPath",
    "VaultInitReport",
    "VaultInspectionReport",
    "VaultMutationReport",
    "VaultEntryExistsError",
    "VaultEntryUnreadableError",
    "VaultError",
    "VaultOrigin",
    "VaultOriginConflictError",
    "VaultKeySourceError",
    "VaultPathError",
    "vault_init",
    "vault_inspect",
    "vault_put",
    "vault_remove",
    "WinningSource",
    "resolve_canonical_path",
]


class Readability(StrEnum):
    """Whether a stored entry can be opened, and why not when it cannot.

    ``WRONG_KEY`` rather than "decryption failed": the answer comes from the
    store's key check value, so what is actually known is that *this key does
    not open this store* — no stored secret was decrypted to find out.
    """

    READABLE = "readable"
    KEY_UNAVAILABLE = "key_unavailable"
    WRONG_KEY = "wrong_key"
    ABSENT = "absent"


class WinningSource(StrEnum):
    """Which layer of the resolution chain would supply this field today."""

    OVERRIDE = "override"
    CLI = "cli"
    VAULT = "vault"
    ENV = "env"
    FILE = "file"
    DEFAULT = "default"
    MISSING = "missing"


class VaultPathError(ValueError):
    """A path does not name a field the vault could ever supply.

    Carries a stable ``reason`` so a delivery surface can classify the failure
    without parsing prose. The message is safe to print: it names the path and
    what is wrong with it, never a candidate value.
    """

    def __init__(self, reason: str, message: str, *, path: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.path = path


@dataclass(frozen=True)
class ResolvedVaultPath:
    """A canonical path that has been checked against the live job schema."""

    path: str
    """The canonical spelling, echoed back so a caller sees what was accepted."""

    job_name: str
    field_name: str

    @property
    def config_key(self) -> str:
        """The exact string the resolution chain is keyed on at run time.

        This identity is the feature. A job's config section prefix is its full
        dotted canonical name, so ``VaultSource`` is asked for
        ``"{job_name}.{field_name}"`` — and if what ``put`` stores is not
        byte-identical to that, the value is simply never found. It is a
        property with a test rather than a comment for that reason.
        """
        return f"{self.job_name}.{self.field_name}"


@dataclass(frozen=True)
class VaultInitReport:
    """What ``vault_init`` did. Never the key."""

    key_provider: str
    created: bool
    """``False`` means an existing key was found or validated, and **nothing
    was written anywhere** — the ``--key-source env`` case. Surfaces must say
    which of the two happened rather than a generic "initialized"."""

    key_scope: str = "user"
    """One key opens every project's vault (ADR-023 §4). Stated in the report
    because "initialized" otherwise reads as per-project."""


@dataclass(frozen=True)
class VaultMutationReport:
    """The outcome of a write or a removal. Carries no value."""

    path: str
    origin: VaultOrigin | None
    created: bool = False
    replaced: bool = False
    removed: bool = False
    updated_at: datetime | None = None
    warning: str | None = None
    """Set only when a *direct* entry was removed, because that is the only
    kind with no upstream copy. A provider entry comes back on the next sync,
    so warning about it would be noise that teaches people to ignore it."""


@dataclass(frozen=True)
class VaultInspectionReport:
    """Everything known about a path without holding its value."""

    path: str
    eligible: bool
    exists: bool
    origin: VaultOrigin | None = None
    provider: str | None = None
    reference: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    synced_at: datetime | None = None
    key_provider: str | None = None
    readability: Readability = Readability.ABSENT
    stale: bool | None = None
    winning_source: WinningSource = WinningSource.MISSING


def resolve_canonical_path(app: Any, path: str) -> ResolvedVaultPath:
    """Check a path against the live job schema, before any input is read.

    Args:
        app: A booted :class:`~functualize.app.FunctualizeApp`.
        path: ``<job path>.<field>``, e.g. ``infra.deploy.api_token``.

    Returns:
        The resolved path, whose :attr:`~ResolvedVaultPath.config_key` is what
        the resolution chain will ask for at run time.

    Raises:
        VaultPathError: With a stable ``reason``. Every rejection happens here,
            which is why callers can validate before prompting: a typo must not
            cost you the secret you already typed.
    """
    job_part, _, field_part = path.rpartition(".")
    if not job_part or not field_part:
        raise VaultPathError(
            "unknown_field",
            f"{path!r} is not a vault path. Expected <job>.<field>, "
            f"e.g. 'deploy.api_token'.",
            path=path,
        )

    descriptor = _resolve_job(app, job_part, path)
    field = _resolve_field(descriptor, field_part, path)
    return ResolvedVaultPath(
        path=f"{_descriptor_name(descriptor)}.{field.name}",
        job_name=_descriptor_name(descriptor),
        field_name=field.name,
    )


def _descriptor_name(descriptor: Any) -> str:
    return str(getattr(descriptor, "name", ""))


def _resolve_job(app: Any, job_part: str, path: str) -> Any:
    """Find the one job a path's leading segments name.

    Uses the app's own lookup and then the repository's single naming policy,
    so ``build_wheel`` reaches the registered ``build-wheel`` exactly as it does
    everywhere else. A second resolver here would be a fourth spelling of the
    same question.
    """
    from functualize.app.utils import resolve_name

    descriptor = app.get_job(job_part)
    if descriptor is not None:
        return descriptor

    known = [str(d.name) for d in app.get_jobs()]
    try:
        resolved = resolve_name(job_part, known)
    except Exception as exc:
        raise VaultPathError(
            "unknown_job",
            f"No job named {job_part!r} (from path {path!r}). "
            f"Run `func builtin info jobs` to see what is available.",
            path=path,
        ) from exc

    descriptor = app.get_job(resolved)
    if descriptor is None:  # pragma: no cover - resolve_name just found it
        raise VaultPathError(
            "unknown_job",
            f"No job named {job_part!r} (from path {path!r}).",
            path=path,
        )
    return descriptor


def _resolve_field(descriptor: Any, field_part: str, path: str) -> Any:
    """Find an eligible config field, or explain precisely why there is none.

    Three refusals, deliberately distinct, because they send the reader
    somewhere different: the field does not exist, it exists but is not
    sensitive, or it is sensitive but lives somewhere the vault could never
    reach it.
    """
    config_fields = list(getattr(descriptor, "config_fields", None) or [])
    parameters = list(getattr(descriptor, "parameters", None) or [])

    # The published schema is `config_fields or parameters`, so a job with no
    # config model publishes its signature. Those fields are bound from the
    # invocation, never from the resolution chain, so a secret one is
    # addressable and undeliverable -- the distinction this check exists for.
    from_model = [f for f in config_fields if getattr(f, "from_config_model", False)]

    match = _match_field(from_model, field_part)
    if match is not None:
        if not getattr(match, "secret", False):
            raise VaultPathError(
                "field_not_secret",
                f"{path!r} is not a secret field. The vault stores only fields "
                f"declared Secret[str] (or marked secret), so that a value can "
                f"never be stored somewhere it would later be printed.",
                path=path,
            )
        return match

    stray = _match_field(parameters, field_part) or _match_field(
        config_fields, field_part
    )
    if stray is not None:
        raise VaultPathError(
            "field_not_config_model",
            f"{path!r} names a job *parameter*, not a config field. Parameters "
            f"are supplied per invocation and never read from the resolution "
            f"chain, so a value stored here could never reach the job. Move it "
            f"to the job's config model to make it vault-backed.",
            path=path,
        )

    if "." in field_part:  # pragma: no cover - rpartition leaves no dots
        raise VaultPathError(
            "nested_field_not_supported",
            f"{path!r} names a nested field. This increment stores top-level "
            f"fields only.",
            path=path,
        )

    raise VaultPathError(
        "unknown_field",
        f"{_descriptor_name(descriptor)!r} has no field {field_part!r}. "
        f"Run `func builtin info jobs` to see its inputs.",
        path=path,
    )


def _match_field(fields: list[Any], wanted: str) -> Any | None:
    """Match a field name, accepting the CLI's spelling of it.

    The chain is keyed on the *model* field name (``api_token``) while the flag
    a user types is ``--api-token``. Accepting both and reporting the canonical
    one costs a normalization and saves a class of "I typed exactly what the
    help said" confusion.
    """
    normalized = wanted.replace("-", "_")
    for field in fields:
        name = str(getattr(field, "name", ""))
        if name in (wanted, normalized):
            return field
    return None


class VaultKeySourceError(RuntimeError):
    """No key source could do what was asked, and why.

    Carries a stable ``reason`` so a delivery surface classifies without
    parsing prose, and a message that teaches: on a stock install this is the
    first thing a user meets, so it names *both* routes forward rather than
    only the one that happens to be unavailable.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def vault_init(
    *, key_source: str | None = None, cwd: str | Path | None = None
) -> VaultInitReport:
    """Ensure a vault key exists, without ever showing it.

    Takes **no app**: the shipped providers are user-scoped (ADR-023 §4), so
    there is no discovery to run and this is done once per machine rather than
    once per project.

    It does still resolve a ``project_id``, cheaply and without booting, and
    hands it to the provider. Both shipped providers ignore it — but key scope
    is a *provider's* choice, and a third-party KMS may legitimately hold one
    key per project. Passing a placeholder would quietly break exactly those.

    Args:
        key_source: A provider identifier such as ``"env"`` or ``"keychain"``.
            ``None`` picks the first available one, non-interactive first —
            the ordering ADR-016 §5 made part of the contract, because
            reversed, an unattended run blocks on a prompt nobody can answer.
        cwd: Where to resolve the project from. Defaults to the working
            directory.

    Returns:
        A report naming the provider and whether a key was **created**.
        ``created=False`` means one already existed or was merely validated —
        the ``--key-source env`` case, where nothing is written anywhere.

    Raises:
        VaultKeySourceError: No usable source. Never falls back to printing a
            key: ``keygen`` exists for that and is explicitly the operator's to
            place.

    Writes nothing to the vault file. The key check value is written by the
    first *store* write, so ``vault_init(key_source="env")`` is genuinely
    read-only and the vault file still appears on first write.
    """
    from functualize._config.vault_keys import default_providers

    project_id = _project_id(cwd)
    providers = list(default_providers())

    if key_source is not None:
        chosen = next((p for p in providers if p.identifier() == key_source), None)
        if chosen is None:
            known = ", ".join(sorted(p.identifier() for p in providers))
            raise VaultKeySourceError(
                "unknown_key_source",
                f"No key source named {key_source!r}. Available: {known}.",
            )
        return _init_with(chosen, project_id)

    for provider in _non_interactive_first(providers):
        if not provider.is_available():
            continue
        return _init_with(provider, project_id)

    raise VaultKeySourceError("key_source_unavailable", _NO_KEY_STORE_MESSAGE)


def _non_interactive_first(providers: list[Any]) -> list[Any]:
    """Two passes rather than a sort, matching `resolve_vault_key`.

    An interactive provider must not be consulted merely because it sorted
    first; the split is the contract, not a tiebreak.
    """
    return [p for p in providers if not p.interactive()] + [
        p for p in providers if p.interactive()
    ]


def _project_id(cwd: str | Path | None) -> str:
    """This project's identity, without booting anything."""
    from functualize._config.vault_paths import project_root_for
    from functualize._primitives.locator import compute_project_id

    return compute_project_id(str(project_root_for(cwd)))


#: What a stock install meets first, so it teaches both routes rather than
#: naming only the one that is missing. `keyring` is an optional extra, and the
#: environment route needs no install at all.
_NO_KEY_STORE_MESSAGE = (
    "No key store is available on this machine.\n\n"
    "Two ways forward:\n\n"
    "  pip install 'functualize[keychain]'\n"
    "     then re-run this command\n\n"
    "  func builtin vault keygen\n"
    "     export FUNCTUALIZE_VAULT_KEY=<it>\n"
    "     func builtin vault init --key-source env"
)


def _init_with(provider: Any, project_id: str) -> VaultInitReport:
    """Create or validate through one provider, reporting which happened."""
    from functualize.plugin import VaultKeyInitializer

    identifier = provider.identifier()

    if provider.get_key(project_id) is not None:
        # Idempotent, and honest about it: nothing was written, so the report
        # must not say "created". `--key-source env` always lands here, which
        # is what makes it a pure preflight.
        return VaultInitReport(key_provider=identifier, created=False)

    if not isinstance(provider, VaultKeyInitializer):
        detail = (
            "Run `func builtin vault keygen` and export $FUNCTUALIZE_VAULT_KEY."
            if identifier == "env"
            else _NO_KEY_STORE_MESSAGE
        )
        raise VaultKeySourceError(
            "key_source_not_initializable",
            f"The {identifier!r} key source can only read a key, not create "
            f"one — only you can set it. {detail}",
        )

    if not provider.is_available():
        raise VaultKeySourceError(
            "key_source_unavailable",
            f"The {identifier!r} key source is not available here.\n\n"
            f"{_NO_KEY_STORE_MESSAGE}",
        )

    provider.initialize_key(project_id)
    return VaultInitReport(key_provider=identifier, created=True)


def _open_store(cwd: str | Path | None = None) -> SecretsVault:
    """This project's store.

    Annotated concretely rather than as ``Any``. The verify phase's orphan scan
    resolves call targets through return types, and an ``Any`` here made
    ``SecretsVault.delete`` look like it had no production caller at all — the
    scan is a repo discipline, so blinding it has a real cost.
    """
    from functualize._config.vault import SecretsVault
    from functualize._config.vault_paths import vault_path_for_project

    return SecretsVault(vault_path_for_project(cwd))


def _resolve_key(cwd: str | Path | None = None) -> KeyResolution:
    """The vault key, or a refusal that names how to supply one."""
    from functualize._config.vault_keys import resolve_vault_key

    resolution = resolve_vault_key(_project_id(cwd))
    if resolution is None:
        raise VaultKeySourceError(
            "key_unavailable",
            "No vault key is available, so nothing can be encrypted or read.\n\n"
            + _NO_KEY_STORE_MESSAGE,
        )
    return resolution


def vault_put(
    app: Any,
    path: str,
    value: str,
    *,
    replace: bool = False,
    cwd: str | Path | None = None,
) -> VaultMutationReport:
    """Store one value against a canonical path.

    Args:
        app: A booted app, for the job schema the path is checked against.
        path: ``<job>.<field>``. Validated *before* anything else happens.
        value: The plaintext. Never logged, never returned, never in a report.
        replace: Permit overwriting an existing direct entry.
        cwd: Project directory. Defaults to the working directory.

    Raises:
        VaultPathError: The path names nothing the vault could supply.
        VaultKeySourceError: No key is available to encrypt with.
        VaultEntryExistsError: An entry exists and ``replace`` is False.
        VaultOriginConflictError: A provider entry holds this path. Changing
            what wrote an entry is never a side effect of writing it.

    The caller is expected to have validated the path with
    :func:`resolve_canonical_path` before collecting ``value`` — a typo must
    not cost someone the secret they already typed. This re-validates anyway,
    because a public function cannot assume its caller did.
    """
    resolved = resolve_canonical_path(app, path)
    resolution = _resolve_key(cwd)
    store = _open_store(cwd)

    existed = any(e.key == resolved.config_key for e in store.list_entries())
    store.put(
        resolved.config_key,
        value,
        encryption_key=resolution.key,
        origin=VaultOrigin.DIRECT,
        replace=replace,
    )
    entry = next(e for e in store.list_entries() if e.key == resolved.config_key)
    return VaultMutationReport(
        path=resolved.path,
        origin=entry.origin,
        created=not existed,
        replaced=existed,
        updated_at=entry.updated_at,
    )


def vault_remove(
    app: Any, path: str, *, cwd: str | Path | None = None
) -> VaultMutationReport:
    """Remove one entry of either origin. Needs no vault key.

    Args:
        app: Used only to canonicalize ``path``. A path that does **not**
            resolve is still attempted literally — see below.
        path: The canonical path, or the stored key itself.
        cwd: Project directory.

    Returns:
        What was removed. ``removed=False`` with ``origin=None`` when nothing
        was there, which is success: asking for something gone to be gone has
        been satisfied.

    **An unresolvable path is not refused.** This is the recovery command, and
    the entries most needing removal are the ones whose job has since been
    renamed or deleted — validating against the current schema would make the
    orphans it exists to clear unreachable. A path that resolves is
    canonicalized so flag spelling works; one that does not is used verbatim
    and simply matches nothing if it was a typo.
    """
    try:
        target = resolve_canonical_path(app, path).config_key
    except VaultPathError:
        target = path

    removed = _open_store(cwd).delete(target)
    if removed is None:
        return VaultMutationReport(path=target, origin=None, removed=False)

    return VaultMutationReport(
        path=target,
        origin=removed.origin,
        removed=True,
        updated_at=removed.updated_at,
        warning=(
            "no upstream copy; this value is gone"
            if removed.origin is VaultOrigin.DIRECT
            else None
        ),
    )


def vault_inspect(
    app: Any, path: str, *, cwd: str | Path | None = None
) -> VaultInspectionReport:
    """Describe a path without holding its value.

    Answers eligibility, existence, provenance and readability. Readability
    comes from the store's key check value, so **no stored secret is decrypted
    to produce this report** — which is what makes the security claim about
    this command true rather than aspirational.

    An ineligible path is reported as ``eligible=False`` rather than raised,
    because "why can I not store this here?" is the question the command exists
    to answer.
    """
    from functualize._config.vault_keys import resolve_vault_key

    try:
        resolved = resolve_canonical_path(app, path)
        key = resolved.config_key
        eligible = True
        display = resolved.path
    except VaultPathError:
        key, eligible, display = path, False, path

    store = _open_store(cwd)
    entry = next((e for e in store.list_entries() if e.key == key), None)
    if entry is None:
        return VaultInspectionReport(
            path=display,
            eligible=eligible,
            exists=False,
            readability=Readability.ABSENT,
            winning_source=WinningSource.MISSING,
        )

    resolution = resolve_vault_key(_project_id(cwd))
    if resolution is None:
        readability = Readability.KEY_UNAVAILABLE
    else:
        opens = store.opens_with(resolution.key)
        # `None` means the store predates the check row. Reporting that as
        # readable would be a guess; reporting it as wrong would libel every
        # vault written before this feature. Unknown is neither, so it maps to
        # the state that says "a key is present but unverified".
        readability = (
            Readability.READABLE if opens is not False else Readability.WRONG_KEY
        )

    return VaultInspectionReport(
        path=display,
        eligible=eligible,
        exists=True,
        origin=entry.origin,
        provider=entry.provider,
        reference=entry.annotation,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
        synced_at=entry.synced_at,
        key_provider=entry.key_provider,
        readability=readability,
        winning_source=(
            WinningSource.VAULT
            if readability is Readability.READABLE
            else WinningSource.MISSING
        ),
    )
