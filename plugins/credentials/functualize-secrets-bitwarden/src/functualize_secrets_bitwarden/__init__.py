"""Bitwarden providers for functualize — two products, one package.

Registered through the ``functualize.remote_providers`` entry-point group and
consulted by ``func builtin vault sync``, not during job execution — a run
reads the project's encrypted local vault and never touches the network
(ADR-016).

``bws`` — Bitwarden **Secrets Manager**
    The machine-account product, spoken through Bitwarden's own SDK. Addresses
    secrets by uuid or key name::

        [[vault_secret]]
        job = "database"
        field = "password"
        source = "bws://8a9c2f0e-1b3d-4c5e-9f70-2a1b3c4d5e6f"

``bwpm`` — Bitwarden **Password Manager**
    The personal-vault product — the one Vaultwarden reimplements — spoken
    through the user's own ``bw`` CLI as a subprocess, under the session that
    user has already unlocked. It never logs in, never prompts, never
    persists a session; a locked vault is a refusal naming itself, and the
    recovery is a human running ``bw unlock``::

        [[vault_secret]]
        group = "deploy"
        field = "token"
        source = "bwpm://deploy-token/password"

Two products, not one product with modes
----------------------------------------

Bitwarden ships two separate things that share a name and nothing else.
**Secrets Manager** (``bws`` CLI, Bitwarden-licensed SDK) is the machine
account product; **Password Manager** (``bw`` CLI) is the human vault, and it
is what Vaultwarden reimplements. The APIs do not overlap: the ``bws``
endpoints are exactly the ones Vaultwarden lacks, which is why the Secrets
Manager provider cannot serve a self-hosted Vaultwarden at all, however its
URL is configured — and why the second provider in this package is the
project's first self-hosted-friendly secret source.

``BWS_API_URL`` and ``BWS_IDENTITY_URL`` point the SDK at a self-hosted
*Bitwarden* server, which is a different thing from Vaultwarden. The ``bwpm``
provider invents no server variables at all: server selection stays with the
``bw`` CLI's own configuration, per the 12-factor reasoning recorded in
``_client``.

The two schemes are deliberately unconfusable. ``bw://`` would sit one
character from ``bws://`` while naming a different product with different
credentials; a misread scheme silently sends the lookup to the wrong one, and
the error would send the reader debugging the wrong credential system.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from functualize_secrets_bitwarden._client import (
    ACCESS_TOKEN_VAR,
    ORGANIZATION_VAR,
    BitwardenAuthError,
    BitwardenRequestError,
    MissingOrganizationError,
    build_client,
    clear_client_cache,
    organization_for,
    unwrap,
)
from functualize_secrets_bitwarden._pm_client import (
    AmbiguousFieldError,
    AmbiguousItemError,
    BwBinaryMissingError,
    BwCommandError,
    BwNotLoggedInError,
    BwSessionLockedError,
    FieldNotFoundError,
    ItemNotFoundError,
    extract_field,
    fetch_item,
)
from functualize_secrets_bitwarden._pm_reference import (
    CUSTOM_FIELD_PREFIX,
    PM_FIELDS,
    PmReference,
    parse_pm_reference,
)
from functualize_secrets_bitwarden._reference import (
    HONOURED_KEYS,
    BwsReference,
    InvalidReferenceError,
    parse_reference,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "ACCESS_TOKEN_VAR",
    "CUSTOM_FIELD_PREFIX",
    "HONOURED_KEYS",
    "ORGANIZATION_VAR",
    "PM_FIELDS",
    "AmbiguousFieldError",
    "AmbiguousItemError",
    "AmbiguousKeyError",
    "BitwardenAuthError",
    "BitwardenRequestError",
    "BwBinaryMissingError",
    "BwCommandError",
    "BwNotLoggedInError",
    "BwSessionLockedError",
    "BwsReference",
    "FieldNotFoundError",
    "InvalidReferenceError",
    "ItemNotFoundError",
    "MissingOrganizationError",
    "PasswordManagerProvider",
    "PmReference",
    "SecretNotFoundError",
    "SecretsManagerProvider",
    "clear_client_cache",
    "parse_pm_reference",
    "parse_reference",
]


class SecretNotFoundError(KeyError):
    """The reference is well-formed and nothing is stored under it."""


class AmbiguousKeyError(LookupError):
    """A key name matches more than one secret.

    Bitwarden does not require key names to be unique across projects, so this
    is a normal state of the world rather than a corrupt one. Picking a winner
    would make a config file resolve differently depending on which project a
    colleague happened to create a secret in, and the wrong pick is a *working*
    run with the wrong credential — the quietest possible failure.
    """


class SecretsManagerProvider:
    """``bws://<uuid>`` or ``bws://<key>`` — Bitwarden Secrets Manager."""

    def identifier(self) -> str:
        return "bws"

    def is_ready(self) -> bool:
        """Whether an access token is present.

        Genuinely env-only, as ``RemoteProvider.is_ready``'s docstring asks —
        the AWS provider cannot honour that clause, this one can. Deliberately
        does not authenticate: readiness is asked per value, and a network
        round-trip per value to answer "is a token set" is not a readiness
        check, it is a fetch.
        """
        import os

        return bool(os.environ.get(ACCESS_TOKEN_VAR))

    def fetch(self, reference: str) -> str:
        """Resolve one reference to its value.

        Args:
            reference: Everything after ``bws://``, opaque to core, parsed here.

        Returns:
            The secret's value, as a string.

        Raises:
            InvalidReferenceError: Malformed, or an unknown override key.
            BitwardenAuthError: No access token, or it was rejected.
            MissingOrganizationError: A key name with nowhere to search.
            AmbiguousKeyError: A key name matching more than one secret.
            SecretNotFoundError: Well-formed, and nothing is there.
        """
        ref = parse_reference(reference)
        client = build_client()
        secret_id = ref.secret_id or self._resolve_key(client, ref)
        secret = unwrap(client.secrets().get(secret_id), f"secret {ref.label!r}")
        value = getattr(secret, "value", None)
        if value is None:
            raise SecretNotFoundError(f"Secret {ref.label!r} holds no value.")
        return str(value)

    def _resolve_key(self, client: Any, ref: BwsReference) -> str:
        """Turn a key name into a secret id, or explain why it cannot."""
        organization = organization_for(ref)
        listing = unwrap(
            client.secrets().list(organization),
            f"the secret list for organization {organization!r}",
        )
        matches = self._matching(getattr(listing, "data", []) or [], ref)

        if not matches:
            raise SecretNotFoundError(
                f"No secret with key {ref.key!r} in organization "
                f"{organization!r}"
                + (f" and project {ref.project!r}." if ref.project else ".")
            )
        if len(matches) > 1:
            ids = ", ".join(sorted(str(m.id) for m in matches))
            raise AmbiguousKeyError(
                f"Key {ref.key!r} matches {len(matches)} secrets: {ids}.\n"
                f"Bitwarden does not require key names to be unique across "
                f"projects. Address the one you mean by its uuid, or narrow "
                f"with '?project=<uuid>'."
            )
        return str(matches[0].id)

    @staticmethod
    def _matching(identifiers: Sequence[Any], ref: BwsReference) -> list[Any]:
        found = [i for i in identifiers if getattr(i, "key", None) == ref.key]
        if ref.project is None:
            return found
        # `project_ids` is plural on an identifier: a secret can belong to
        # more than one project, so this is a membership test, not equality.
        return [
            i
            for i in found
            if ref.project in {str(p) for p in (getattr(i, "project_ids", None) or [])}
        ]


class PasswordManagerProvider:
    """``bwpm://<item>/<field>`` — the Password Manager vault, via ``bw``.

    The ambient-session principle: sync invents no credential-passing
    mechanism. It detects and consumes the state the user has already put
    the CLI in — signed in, unlocked, ``$BW_SESSION`` exported — and fails
    closed, naming the state it found, when it is absent. The session key,
    master password and item values never enter an error, a log, a command
    line, or the vault; the vault receives only what :meth:`fetch` returns.
    """

    def identifier(self) -> str:
        return "bwpm"

    def is_ready(self) -> bool:
        """Always true — by design, not by carelessness.

        The sync report deliberately does not echo provider exception text
        (it cannot know what a provider's message carries), so a failed fetch
        is reported by its exception **class** name. That is exactly where
        this provider's specificity lives: a missing binary, a signed-out
        vault and a locked session are three distinct exception classes, and
        the report reads ``bwpm: BwSessionLockedError during fetch``. Any
        ``False`` here would flatten every one of those states into the
        generic "not ready" reason before ``fetch`` could ever name what it
        found — and answering honestly would require the very probe
        ``fetch`` performs, once per value. An absent or locked ambient
        session is a normal operating state of this provider, not an
        unconfigured one.
        """
        return True

    def fetch(self, reference: str) -> str:
        """Resolve one reference to its value.

        Args:
            reference: Everything after ``bwpm://``, opaque to core, parsed
                here.

        Returns:
            The field's value, as a string.

        Raises:
            InvalidReferenceError: Malformed, or an unknown field — decided
                before any subprocess spawns.
            BwBinaryMissingError: No ``bw`` executable on ``PATH``.
            BwNotLoggedInError: The vault is not signed in.
            BwSessionLockedError: The session is locked.
            BwCommandError: A ``bw`` invocation failed otherwise.
            ItemNotFoundError: No such item.
            FieldNotFoundError: The item stores no value for the field.
            AmbiguousItemError: An item name matching more than one item.
            AmbiguousFieldError: Duplicate custom-field names in one item.
        """
        ref = parse_pm_reference(reference)
        item = fetch_item(ref)
        return extract_field(item, ref)
