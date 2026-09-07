"""The ``bws://`` reference grammar.

::

    bws://<secret-uuid>[?<key>=<value>[&...]]
    bws://<secret-key>[?<key>=<value>[&...]]

Two addressing forms, told apart structurally
---------------------------------------------

A reference that parses as a UUID is a secret **id** and resolves in one call.
Anything else is a secret **key** — the human-readable name Bitwarden shows in
its UI — and resolves by listing the organization's secrets and matching.

The id form alone would have been less code, and it is what the ``bws`` CLI
leans on. It is also unreadable::

    password = "bws://8a9c2f0e-1b3d-4c5e-9f70-2a1b3c4d5e6f"

A config file is read far more often than it is written, and the sibling AWS
provider addresses secrets by name. Supporting both keeps the two providers
consistent and keeps the annotation legible; the cost is one extra API call and
the ambiguity rule below.

Keys are not unique across projects, so a key that matches more than one secret
is an **error** naming every candidate and its id — not a silent pick. Choosing
one would mean a config file that resolves differently depending on which
project a colleague created a secret in.

Two override keys
-----------------

``project``
    A project **uuid**, narrowing a key-name match. Project *names* are not
    accepted: resolving one costs a second listing call and a second ambiguity
    rule, and the error raised on an ambiguous key already tells the reader
    exactly which id to use.

``organization``
    A uuid, overriding ``$BWS_ORGANIZATION_ID`` for this value. Only the key
    form needs it — resolving by id does not.

Both overrides therefore serve the *key* form only, and pairing either with a
uuid is an error rather than a no-op. An override that sits in a config file
looking load-bearing while doing nothing is the same failure as one that is
silently ignored for being misspelled; being spelled correctly does not make
it better.

An unknown key is rejected, never ignored, for the same reason as in the AWS
provider: a caller who writes ``?porject=`` has stated an intent, and quietly
resolving under a different one is the defect this feature exists to remove.

This duplicates the shape of ``functualize_aws._reference`` rather than sharing
it. Plugins must not depend on each other, and a shared "annotation query
grammar" library would be a third package to version for forty lines that the
two providers are free to diverge on.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from urllib.parse import unquote
from uuid import UUID

__all__ = [
    "HONOURED_KEYS",
    "BwsReference",
    "InvalidReferenceError",
    "parse_reference",
]

#: The override keys this provider understands. Anything else is an error.
HONOURED_KEYS: tuple[str, ...] = ("organization", "project")

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


class InvalidReferenceError(ValueError):
    """A reference this provider cannot make sense of.

    Raised before any network call, so a typo costs a clear message rather
    than an opaque API error or a silent resolution of the wrong secret.
    """


def _is_uuid(value: str) -> bool:
    if not _UUID_RE.match(value):
        return False
    try:
        UUID(value)
    except ValueError:  # pragma: no cover - the regex already rejects these
        return False
    return True


@dataclass(frozen=True)
class BwsReference:
    """A parsed reference: which secret, and where to look for it."""

    secret_id: str | None = None
    """Set when the reference was a uuid. Resolves in one call."""

    key: str | None = None
    """Set when the reference was a name. Needs an organization to resolve."""

    project: str | None = None
    organization: str | None = None

    @property
    def label(self) -> str:
        """How to name this reference in an error. Never a value."""
        return self.secret_id or self.key or "<empty>"


def _fail(reference: str, detail: str) -> InvalidReferenceError:
    return InvalidReferenceError(f"{detail}\n  in reference: {reference!r}")


def _suggest(key: str) -> str:
    close = difflib.get_close_matches(key, HONOURED_KEYS, n=1, cutoff=0.6)
    return f" Did you mean '{close[0]}'?" if close else ""


def _split_pairs(query: str, reference: str) -> list[tuple[str, str]]:
    """Split the override block into key/value pairs.

    Hand-rolled rather than :func:`urllib.parse.parse_qsl`, which decodes ``+``
    as a space. Neither a uuid nor a project id may contain a space, so that
    decoding could only ever corrupt one identifier into another.
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


def parse_reference(reference: str) -> BwsReference:
    """Parse a ``bws://`` reference into its parts.

    Args:
        reference: Everything after ``bws://``, exactly as core passed it.

    Returns:
        The parsed reference, addressed either by id or by key.

    Raises:
        InvalidReferenceError: The target is empty, an override key is unknown
            or repeated, or a uuid-shaped override is not a uuid.
    """
    target, _, query = reference.partition("?")
    if not target:
        raise _fail(reference, "No secret id or key before the '?'.")

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

    for key in ("project", "organization"):
        given = values.get(key)
        if given is not None and not _is_uuid(given):
            raise _fail(
                reference,
                f"'{key}' must be a uuid, got {given!r}. Bitwarden's own "
                f"{key} *names* are not accepted here — an ambiguous key "
                f"reports the ids to choose between.",
            )

    by_id = _is_uuid(target)
    if by_id and values:
        # Both overrides exist to resolve a *name*: `project` narrows the
        # search and `organization` says where to search. A uuid needs
        # neither, so an override here would sit in the config file looking
        # load-bearing while doing nothing -- the same silent no-op the
        # unknown-key rule above exists to prevent, and no more acceptable for
        # being spelled correctly.
        raise _fail(
            reference,
            f"{', '.join(sorted(values))} cannot apply to a secret addressed "
            f"by uuid: the id resolves in one call and consults neither. "
            f"Drop the override, or address the secret by its key name.",
        )

    return BwsReference(
        secret_id=target if by_id else None,
        key=None if by_id else target,
        project=values.get("project"),
        organization=values.get("organization"),
    )
