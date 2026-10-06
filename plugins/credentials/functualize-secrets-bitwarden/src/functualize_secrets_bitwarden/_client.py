"""Building and authenticating the Bitwarden Secrets Manager client.

Configuration, all from the environment
---------------------------------------

Unlike the AWS provider — whose per-value overrides deliberately break the
``RemoteProvider`` protocol's 12-factor clause — everything here really does
come from environment variables, as that clause asks:

``BWS_ACCESS_TOKEN``
    The machine-account access token. Canonical: this is the variable the real
    ``bws`` CLI reads.

``BWS_ORGANIZATION_ID``
    Needed only to resolve a secret by key name. The uuid form does not use it.

``BWS_API_URL`` / ``BWS_IDENTITY_URL``
    **This plugin's own names**, defaulting to Bitwarden's cloud. The ``bws``
    CLI has no environment variable for these — it uses ``bws config`` and a
    ``--server-url`` flag — so there was no canonical name to adopt. Stated
    plainly because inventing a ``BWS_``-prefixed variable that Bitwarden does
    not define is exactly the kind of thing a reader will otherwise assume is
    official.

The state file is off
---------------------

``login_access_token`` accepts a path where the SDK persists auth state. It is
left at ``None``, so authentication happens once per process and nothing
touches the disk. Same reasoning as the AWS provider's in-memory STS cache: the
vault holds resolved values, and a credential is not one.

The trap this module exists to close
------------------------------------

The SDK does not raise on failure. Every call returns a wrapper::

    ResponseForSecretResponse(success=False, data=None, error_message="...")

so an unchecked ``response.data.value`` is an ``AttributeError`` at best, and a
``None`` written into the vault at worst — a job receiving nothing where it
expected a secret, with no error anywhere. :func:`unwrap` is the single place
that turns that wrapper into either a value or an exception.
"""

from __future__ import annotations

import os
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize_bitwarden._reference import BwsReference

__all__ = [
    "BitwardenAuthError",
    "BitwardenRequestError",
    "MissingOrganizationError",
    "build_client",
    "clear_client_cache",
    "organization_for",
    "unwrap",
]

ACCESS_TOKEN_VAR = "BWS_ACCESS_TOKEN"
ORGANIZATION_VAR = "BWS_ORGANIZATION_ID"

_DEFAULT_API_URL = "https://api.bitwarden.com"
_DEFAULT_IDENTITY_URL = "https://identity.bitwarden.com"

_CLIENT: Any = None
_LOCK = threading.Lock()


class BitwardenAuthError(RuntimeError):
    """No access token, or the token was rejected."""


class BitwardenRequestError(RuntimeError):
    """The SDK reported a failed call.

    Carries the SDK's own ``error_message``, which describes the request and
    never the secret.
    """


class MissingOrganizationError(RuntimeError):
    """A key-name reference was used with no organization to search."""


def clear_client_cache() -> None:
    """Drop the authenticated client. For tests, and for a token change."""
    global _CLIENT
    with _LOCK:
        _CLIENT = None


def _settings() -> dict[str, str]:
    from bitwarden_sdk import DeviceType

    return {
        "apiUrl": os.environ.get("BWS_API_URL", _DEFAULT_API_URL),
        "identityUrl": os.environ.get("BWS_IDENTITY_URL", _DEFAULT_IDENTITY_URL),
        "deviceType": DeviceType.SDK,
        "userAgent": "functualize",
    }


def build_client() -> Any:
    """Return an authenticated client, building one on first use.

    Cached for the process: a sync fetching thirty secrets authenticates once.

    Raises:
        BitwardenAuthError: ``$BWS_ACCESS_TOKEN`` is unset, or login failed.
    """
    global _CLIENT
    with _LOCK:
        if _CLIENT is not None:
            return _CLIENT

        token = os.environ.get(ACCESS_TOKEN_VAR)
        if not token:
            raise BitwardenAuthError(
                f"${ACCESS_TOKEN_VAR} is not set. Create a machine account "
                f"access token in Bitwarden Secrets Manager and export it."
            )

        from bitwarden_sdk import BitwardenClient, client_settings_from_dict

        client = BitwardenClient(client_settings_from_dict(_settings()))
        # state_file stays None: nothing this plugin holds should outlive the
        # process, and an auth-state file on disk is a credential at rest.
        response = client.auth().login_access_token(token, None)
        if not getattr(response, "success", False):
            raise BitwardenAuthError(
                f"Bitwarden rejected ${ACCESS_TOKEN_VAR}: "
                f"{getattr(response, 'error_message', None) or 'no reason given'}"
            )

        _CLIENT = client
        return _CLIENT


def organization_for(ref: BwsReference) -> str:
    """The organization to search for a key-name reference.

    Raises:
        MissingOrganizationError: Neither the annotation nor the environment
            says which organization to search.
    """
    organization = ref.organization or os.environ.get(ORGANIZATION_VAR)
    if not organization:
        raise MissingOrganizationError(
            f"Resolving {ref.label!r} by key name needs an organization. "
            f"Set ${ORGANIZATION_VAR}, add '?organization=<uuid>' to the "
            f"annotation, or address the secret by its uuid instead."
        )
    return organization


def unwrap(response: Any, what: str) -> Any:
    """Return a successful response's payload, or raise.

    The SDK signals failure in the return value rather than by raising, so
    every call must pass through here. Skipping it once puts a ``None`` in the
    vault and a job reads nothing where it expected a secret.

    Args:
        response: A ``ResponseFor…`` wrapper.
        what: What was being fetched, for the error message.

    Returns:
        ``response.data``.

    Raises:
        BitwardenRequestError: The call failed, or succeeded with no payload.
    """
    if not getattr(response, "success", False):
        raise BitwardenRequestError(
            f"Bitwarden could not return {what}: "
            f"{getattr(response, 'error_message', None) or 'no reason given'}"
        )
    data = getattr(response, "data", None)
    if data is None:
        # `success=True, data=None` should not happen. If it ever does, the
        # alternative to raising is writing None into the vault.
        raise BitwardenRequestError(
            f"Bitwarden reported success but returned nothing for {what}."
        )
    return data
