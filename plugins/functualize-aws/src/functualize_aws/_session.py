"""Turning a parsed reference into a boto3 client.

Three things happen here, in this order, and the order is the contract:

1. **Source identity.** ``profile`` selects a named profile; without it, the
   ambient boto3 chain applies unchanged.
2. **Role assumption.** ``role`` is assumed *from* whatever step 1 produced, so
   the two compose rather than conflict.
3. **Account assertion.** ``account`` is checked against the identity that
   actually resulted, after any assumption. Checking before step 2 would
   assert the wrong thing.

Where the temporary credentials live
------------------------------------

In memory, in :data:`_ASSUMED`, for the life of the process. They are never
written to disk and they never enter the vault: the vault holds resolved
*values*, and a credential is not one. Structurally this is guaranteed by the
seam rather than by care — the vault is filled from what ``fetch()`` returns,
and ``fetch()`` returns the secret string.

The cache is keyed by ``(profile, role, region)`` and honoured until five
minutes before expiry, so a sync fetching thirty secrets under one role calls
STS once rather than thirty times.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import boto3

if TYPE_CHECKING:
    from functualize_aws._reference import AwsReference

__all__ = [
    "AccountMismatchError",
    "client_for",
    "clear_credential_cache",
    "resolve_session",
]

#: Re-assume this long before the credentials actually expire, so a long sync
#: cannot start a fetch with credentials that die mid-call.
_EXPIRY_MARGIN = timedelta(minutes=5)

_SESSION_NAME = "functualize-config-sync"


class AccountMismatchError(RuntimeError):
    """The resolved identity is not in the account the reference asserted.

    Loud by design. The alternative — carrying on — means reading some *other*
    account's secret while the config file says which account was meant.
    """


@dataclass(frozen=True)
class _Assumed:
    credentials: dict[str, Any]
    expires_at: datetime

    @property
    def usable(self) -> bool:
        return datetime.now(UTC) + _EXPIRY_MARGIN < self.expires_at


_ASSUMED: dict[tuple[str | None, str | None, str | None], _Assumed] = {}
_LOCK = threading.Lock()


def clear_credential_cache() -> None:
    """Drop every cached assumption. For tests, and for a long-lived process
    that has just been told its role changed."""
    with _LOCK:
        _ASSUMED.clear()


def _base_session(ref: AwsReference) -> boto3.Session:
    """Step 1: the source identity, before any role is assumed."""
    kwargs: dict[str, Any] = {}
    if ref.profile is not None:
        kwargs["profile_name"] = ref.profile
    if ref.region is not None:
        kwargs["region_name"] = ref.region
    return boto3.Session(**kwargs)


def _assume(ref: AwsReference, base: boto3.Session) -> _Assumed:
    sts = base.client("sts")
    response = sts.assume_role(RoleArn=ref.role, RoleSessionName=_SESSION_NAME)
    creds = response["Credentials"]
    return _Assumed(
        credentials={
            "aws_access_key_id": creds["AccessKeyId"],
            "aws_secret_access_key": creds["SecretAccessKey"],
            "aws_session_token": creds["SessionToken"],
        },
        expires_at=creds["Expiration"],
    )


def resolve_session(ref: AwsReference) -> boto3.Session:
    """Build the session this reference's credentials describe.

    Args:
        ref: The parsed reference.

    Returns:
        A session carrying the source identity, or the assumed role's
        temporary credentials when ``role`` is set.

    Raises:
        AccountMismatchError: ``account`` was asserted and does not match.
    """
    base = _base_session(ref)
    session = base

    if ref.role is not None:
        key = ref.identity_key
        with _LOCK:
            cached = _ASSUMED.get(key)
            if cached is None or not cached.usable:
                cached = _assume(ref, base)
                _ASSUMED[key] = cached
        session = boto3.Session(
            region_name=ref.region or base.region_name, **cached.credentials
        )

    if ref.account is not None:
        _assert_account(session, ref)

    return session


def _assert_account(session: boto3.Session, ref: AwsReference) -> None:
    identity = session.client("sts").get_caller_identity()
    actual = identity.get("Account")
    if actual != ref.account:
        raise AccountMismatchError(
            f"Reference asserts account {ref.account}, but the resolved "
            f"identity is in account {actual} "
            f"(arn: {identity.get('Arn')}).\n"
            f"  reference: {ref.name!r}\n"
            f"Refusing rather than reading a different account's value."
        )


def client_for(ref: AwsReference, service: str) -> Any:
    """A client for ``service``, built for this reference's identity.

    ``AWS_ENDPOINT_URL`` is honoured by botocore itself, which is what lets the
    integration tests point at a local emulator without this plugin knowing
    anything about one.
    """
    return resolve_session(ref).client(service)
