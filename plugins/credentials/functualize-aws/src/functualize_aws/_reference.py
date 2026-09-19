"""The ``aws-sm://`` / ``aws-ssm://`` reference grammar.

Core treats everything after ``provider://`` as opaque and hands it to
``fetch()`` whole — including colons, slashes and query strings, pinned by
``TestTheReferenceIsOpaqueToCore``. This module is where that opaque string
acquires meaning, and it is the only place in the plugin that decides what a
reference *is*.

The grammar
-----------

::

    aws-sm://<secret-id>[?<key>=<value>[&...]]
    aws-ssm://<parameter-name>[?<key>=<value>[&...]]

``<secret-id>`` may be a name or a full ARN; ``<parameter-name>`` is an SSM
name, conventionally leading-slash. Both are passed to AWS verbatim.

Why splitting on ``?`` is safe: neither an SSM parameter name
(``[a-zA-Z0-9_.\\-/]``) nor an ARN admits a literal ``?``, so the first ``?``
can only begin the override block.

Four override keys, and why each behaves as it does
---------------------------------------------------

Different secrets in one config file may legitimately need different accounts,
roles or profiles, so the override is per *value*, not per provider.

``profile``
    Selects a named profile from the shared AWS config, replacing the ambient
    credential chain for this value.

``role``
    An IAM role ARN to assume. Composes with ``profile``: the profile (or the
    ambient chain) supplies the *source* identity, and the role is assumed from
    it. The resulting temporary credentials live in memory for the life of the
    process and are **never** persisted — see :mod:`functualize_aws._session`.

``region``
    The region the client is built for.

``account``
    An **assertion**, not a selector. boto3 has no "switch to account N"
    primitive, so a key named ``account`` can only mean one of two things:
    silently ignored, or checked. Checked — the resolved caller identity must
    match, and a mismatch raises. Reading the *wrong account's* secret while
    believing you named the right one is the failure this whole feature exists
    to prevent.

An unknown key is rejected, never ignored. ``?porfile=prod-admin`` silently
resolving under the default identity is the same class of defect as
``remote_first()`` silently behaving as ``classic()``: the caller states an
intent, and the system quietly does something else.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from urllib.parse import unquote

__all__ = [
    "HONOURED_KEYS",
    "AwsReference",
    "InvalidReferenceError",
    "parse_reference",
]

#: The override keys this provider understands. Anything else is an error.
HONOURED_KEYS: tuple[str, ...] = ("account", "profile", "region", "role")

#: 12 digits, the fixed shape of an AWS account id.
_ACCOUNT_RE = re.compile(r"^\d{12}$")

#: `us-east-1`, `eu-west-2`, `ap-southeast-2`, and the partitioned forms
#: `us-gov-west-1` / `cn-north-1`. Deliberately a shape check, not a list:
#: AWS adds regions faster than a pinned list can follow, and the cost of the
#: check is only to turn a typo into a clear error instead of a boto3 one.
_REGION_RE = re.compile(r"^[a-z]{2}(?:-[a-z]+)+-\d+$")

#: An IAM *role* ARN. A bare role name here is the common mistake and fails
#: inside STS with a message that does not mention the annotation.
_ROLE_ARN_RE = re.compile(r"^arn:aws[a-z-]*:iam::\d{12}:role/\S+$")


class InvalidReferenceError(ValueError):
    """A reference this provider cannot make sense of.

    Raised at parse time, before any AWS call, so a typo costs a clear message
    rather than a confusing API error or — worse — a silent resolution under
    the wrong identity.
    """


@dataclass(frozen=True)
class AwsReference:
    """A parsed reference: what to fetch, and whose credentials to fetch it with."""

    name: str
    """The secret id or parameter name, passed to AWS verbatim."""

    profile: str | None = None
    region: str | None = None
    role: str | None = None
    account: str | None = None

    @property
    def identity_key(self) -> tuple[str | None, str | None, str | None]:
        """What distinguishes one credential resolution from another.

        ``name`` is deliberately absent: two secrets fetched with the same
        profile, role and region share a session, which is what makes an
        assume-role cache worth having.
        """
        return (self.profile, self.role, self.region)


def _fail(reference: str, detail: str) -> InvalidReferenceError:
    return InvalidReferenceError(f"{detail}\n  in reference: {reference!r}")


def _suggest(key: str) -> str:
    """Name the intended key when a typo is close enough to guess."""
    close = difflib.get_close_matches(key, HONOURED_KEYS, n=1, cutoff=0.6)
    return f" Did you mean '{close[0]}'?" if close else ""


def _split_pairs(query: str, reference: str) -> list[tuple[str, str]]:
    """Split the override block into key/value pairs.

    Hand-rolled rather than :func:`urllib.parse.parse_qsl` because that decodes
    ``+`` as a space. None of the four values may contain a space, so a role
    ARN or profile name carrying a ``+`` would be silently corrupted into one
    that does — a wrong-identity failure produced by the parser itself.
    """
    pairs: list[tuple[str, str]] = []
    for chunk in query.split("&"):
        if not chunk:
            raise _fail(reference, "Empty entry in the override block.")
        key, sep, value = chunk.partition("=")
        if not sep:
            raise _fail(reference, f"Override {chunk!r} is missing a '=' and a value.")
        pairs.append((unquote(key).strip(), unquote(value).strip()))
    return pairs


def parse_reference(reference: str) -> AwsReference:
    """Parse an ``aws-sm``/``aws-ssm`` reference into its parts.

    Args:
        reference: Everything after ``provider://``, exactly as core passed it.

    Returns:
        The parsed reference.

    Raises:
        InvalidReferenceError: The name is empty, an override key is unknown or
            repeated, or a value does not have the shape its key requires.
    """
    name, _, query = reference.partition("?")
    if not name:
        raise _fail(reference, "No secret id or parameter name before the '?'.")

    values: dict[str, str] = {}
    if query:
        for key, value in _split_pairs(query, reference):
            if key not in HONOURED_KEYS:
                raise _fail(
                    reference,
                    f"Unknown override '{key}'.{_suggest(key)} "
                    f"Honoured keys: {', '.join(HONOURED_KEYS)}.",
                )
            if key in values:
                raise _fail(
                    reference,
                    f"Override '{key}' given more than once; which one wins is "
                    f"not something this grammar should have to guess.",
                )
            if not value:
                raise _fail(reference, f"Override '{key}' has an empty value.")
            values[key] = value

    account = values.get("account")
    if account is not None and not _ACCOUNT_RE.match(account):
        raise _fail(reference, f"'account' must be 12 digits, got {account!r}.")

    region = values.get("region")
    if region is not None and not _REGION_RE.match(region):
        raise _fail(
            reference,
            f"'region' does not look like an AWS region, got {region!r} "
            f"(expected e.g. 'us-east-1', 'eu-west-2', 'us-gov-west-1').",
        )

    role = values.get("role")
    if role is not None and not _ROLE_ARN_RE.match(role):
        raise _fail(
            reference,
            f"'role' must be a full IAM role ARN, got {role!r} "
            f"(expected e.g. 'arn:aws:iam::123456789012:role/Deploy'). "
            f"A bare role name fails inside STS with a message that never "
            f"mentions this annotation.",
        )

    return AwsReference(
        name=name,
        profile=values.get("profile"),
        region=region,
        role=role,
        account=account,
    )
