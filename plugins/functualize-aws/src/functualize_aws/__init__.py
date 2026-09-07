"""AWS remote configuration providers for functualize.

Two providers over one grammar:

* ``aws-sm`` — Secrets Manager (:class:`SecretsManagerProvider`)
* ``aws-ssm`` — SSM Parameter Store, including ``SecureString``
  (:class:`ParameterStoreProvider`)

Both are registered through the ``functualize.remote_providers`` entry-point
group, which is what ``remote_first()`` refuses to boot without. They are
consulted by ``func builtin vault sync``, not during job execution: a run reads
the project's encrypted local vault and never touches the network (ADR-016).

`is_ready` and the protocol's 12-factor clause
----------------------------------------------

``RemoteProvider.is_ready``'s docstring says credentials "MUST be resolved from
environment variables only". This plugin does not honour that, deliberately and
on the maintainer's instruction: a single config file may need different
accounts, roles or profiles for different values, which is exactly what
environment variables cannot express. ``is_ready`` therefore reports whether
boto3 can find credentials *at all*, by any means in its chain. The divergence
is recorded here rather than left to be discovered in the diff.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from functualize_aws._reference import (
    HONOURED_KEYS,
    AwsReference,
    InvalidReferenceError,
    parse_reference,
)
from functualize_aws._session import (
    AccountMismatchError,
    clear_credential_cache,
    client_for,
)

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "HONOURED_KEYS",
    "AccountMismatchError",
    "AwsReference",
    "InvalidReferenceError",
    "ParameterStoreProvider",
    "SecretNotFoundError",
    "SecretsManagerProvider",
    "clear_credential_cache",
    "parse_reference",
]


class SecretNotFoundError(KeyError):
    """The reference parsed and the call succeeded, but nothing is there.

    Distinct from :class:`InvalidReferenceError` (the annotation is wrong) and
    from a connection failure (AWS could not be reached): this one means the
    annotation is right and the secret has not been created.
    """


class _AwsProvider:
    """Shared behaviour: parse, build a client, fetch, never log the value."""

    #: Overridden by each subclass; also the entry-point key.
    _identifier = ""
    #: The boto3 service name this provider talks to.
    _service = ""

    def identifier(self) -> str:
        return self._identifier

    def is_ready(self) -> bool:
        """Whether boto3 can find any credentials.

        Cached per instance: the answer involves the shared config files and,
        as a last resort, instance metadata, and `sync` asks once per value.
        """
        if self._ready is None:
            try:
                import boto3

                self._ready = boto3.Session().get_credentials() is not None
            except Exception:
                self._ready = False
        return self._ready

    def __init__(self) -> None:
        self._ready: bool | None = None

    def fetch(self, reference: str) -> str:
        """Resolve one reference to its value.

        Args:
            reference: Everything after ``aws-sm://`` or ``aws-ssm://``,
                exactly as core passed it — opaque to core, parsed here.

        Returns:
            The value, as a string.

        Raises:
            InvalidReferenceError: The reference is malformed or names an
                unknown override key.
            AccountMismatchError: ``account`` was asserted and does not match.
            SecretNotFoundError: The reference is valid and nothing is stored
                under it.
        """
        ref = parse_reference(reference)
        return self._read(client_for(ref, self._service), ref)

    def _read(self, client: Any, ref: AwsReference) -> str:
        raise NotImplementedError


def _not_found(ref: AwsReference, what: str) -> SecretNotFoundError:
    # The reference is safe to render -- it names where a value lives and
    # carries no value (the same reasoning the vault's fall-through warning
    # rests on). The value itself never appears in an error.
    return SecretNotFoundError(f"No {what} named {ref.name!r} in AWS.")


def _guard_missing(
    client: Any,
    codes: tuple[str, ...],
    call: Callable[[], Any],
    ref: AwsReference,
    what: str,
) -> Any:
    """Run an AWS call, turning its 'not found' codes into one exception.

    Secrets Manager and Parameter Store spell absence differently
    (``ResourceNotFoundException`` vs ``ParameterNotFound``), and botocore
    builds those exception classes dynamically per client, so they are reached
    through ``client.exceptions`` rather than imported.
    """
    known = tuple(
        getattr(client.exceptions, code)
        for code in codes
        if hasattr(client.exceptions, code)
    )
    try:
        return call()
    except known as exc:  # type: ignore[misc]
        raise _not_found(ref, what) from exc


class SecretsManagerProvider(_AwsProvider):
    """``aws-sm://<secret-id>[?...]`` — AWS Secrets Manager."""

    _identifier = "aws-sm"
    _service = "secretsmanager"

    def _read(self, client: Any, ref: AwsReference) -> str:
        response = _guard_missing(
            client,
            ("ResourceNotFoundException",),
            lambda: client.get_secret_value(SecretId=ref.name),
            ref,
            "secret",
        )
        if "SecretString" in response:
            return str(response["SecretString"])
        # A binary secret has no faithful string form, and guessing an encoding
        # would hand a job silently-wrong bytes.
        raise InvalidReferenceError(
            f"Secret {ref.name!r} holds binary data, which has no string form "
            f"a config value can carry."
        )


class ParameterStoreProvider(_AwsProvider):
    """``aws-ssm://<parameter-name>[?...]`` — SSM Parameter Store.

    ``WithDecryption`` is always on. It is ignored for ``String`` and
    ``StringList``, so there is no knob to get wrong, and a ``SecureString``
    read without it returns ciphertext — a value that would round-trip into the
    vault and reach a job looking exactly like a secret while being useless.
    """

    _identifier = "aws-ssm"
    _service = "ssm"

    def _read(self, client: Any, ref: AwsReference) -> str:
        response = _guard_missing(
            client,
            ("ParameterNotFound", "ParameterVersionNotFound"),
            lambda: client.get_parameter(Name=ref.name, WithDecryption=True),
            ref,
            "parameter",
        )
        return str(response["Parameter"]["Value"])
