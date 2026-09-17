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

from functualize._config.vault import VaultOrigin

if TYPE_CHECKING:
    from datetime import datetime

__all__ = [
    "Readability",
    "ResolvedVaultPath",
    "VaultInitReport",
    "VaultInspectionReport",
    "VaultMutationReport",
    "VaultOrigin",
    "VaultPathError",
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
