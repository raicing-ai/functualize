"""Bitwarden Secrets Manager provider for functualize.

One provider, one identifier: ``bws``. Registered through the
``functualize.remote_providers`` entry-point group and consulted by
``func builtin vault sync``, not during job execution — a run reads the
project's encrypted local vault and never touches the network (ADR-016).

::

    [database]
    password = "bws://8a9c2f0e-1b3d-4c5e-9f70-2a1b3c4d5e6f"
    replica  = "bws://DB_REPLICA_PASSWORD"

Not Vaultwarden
---------------

Bitwarden ships two separate products. **Secrets Manager** (the ``bws`` CLI and
this SDK) is what this provider speaks, and it is Bitwarden-licensed rather
than open source. **Password Manager** (the ``bw`` CLI) is the other, and it is
what Vaultwarden reimplements. A self-hosted Vaultwarden therefore cannot serve
this provider at all, however its URL is configured — the endpoints do not
exist there. Recorded here because "self-hosted Bitwarden" naturally reads as
though it should work.

``BWS_API_URL`` and ``BWS_IDENTITY_URL`` do point this at a self-hosted
*Bitwarden* server, which is a different thing from Vaultwarden.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from functualize_bitwarden._client import (
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
from functualize_bitwarden._reference import (
    HONOURED_KEYS,
    BwsReference,
    InvalidReferenceError,
    parse_reference,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "ACCESS_TOKEN_VAR",
    "HONOURED_KEYS",
    "ORGANIZATION_VAR",
    "AmbiguousKeyError",
    "BitwardenAuthError",
    "BitwardenRequestError",
    "BwsReference",
    "InvalidReferenceError",
    "MissingOrganizationError",
    "SecretNotFoundError",
    "SecretsManagerProvider",
    "clear_client_cache",
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
