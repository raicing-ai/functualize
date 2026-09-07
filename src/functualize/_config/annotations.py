"""Deciding which config values are remote annotations (ADR-016).

A config value like ``aws-sm://prod/db-password`` names *where* a credential
lives without carrying the credential. This module finds those values and turns
them into the ``annotations`` map :class:`~functualize._config.sources.RemoteSource`
consumes. It is the first production caller of
:func:`~functualize._config.manifest.parse_annotation`.

Why the pattern alone is not the test
-------------------------------------

``ANNOTATION_PATTERN`` matches *any* ``scheme://rest``, so on the pattern alone
these are all annotations::

    https://api.example.com      -> provider 'https'
    postgres://user:pw@host/db   -> provider 'postgres'
    s3://bucket/key              -> provider 's3'

A config file full of ordinary URLs would become a config file full of
annotations, and boot would go looking for a provider named ``https``. So the
test is **the scheme matches a registered remote provider**, not the shape.

The failure that decision creates, and how it is handled
--------------------------------------------------------

Keying on registration means ``aws-sm://prod/db`` with the AWS plugin *not
installed* is no longer an annotation — it is a literal, and a job would
receive the string ``"aws-sm://prod/db"`` as its password. Silently. That is
the exact failure class ADR-016 exists to remove, reintroduced one layer down.

So a value that looks like an annotation and names an **unregistered** scheme
is recorded as :class:`UnresolvedAnnotation` rather than passed over in
silence. Common URL schemes are excluded from that report, because a config
file legitimately holds URLs. Note the asymmetry: the exclusion list is used
only to decide whether to *complain*, never to decide what a value *is* — so a
scheme missing from it costs a spurious warning, never a wrong value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from functualize._config.manifest import (
    ANNOTATION_PATTERN,
    FALLBACK_SEPARATOR,
    parse_annotation,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from functualize._config.manifest import SourceAnnotation

__all__ = [
    "AnnotationScan",
    "UnresolvedAnnotation",
    "scan_annotations",
]

#: Schemes that routinely appear as ordinary values in a config file. Used
#: *only* to suppress the "did you mean an annotation?" diagnostic — never to
#: classify a value. A scheme missing here produces a spurious warning; it can
#: never produce a wrong resolution.
_COMMON_URL_SCHEMES = frozenset(
    {
        "amqp",
        "amqps",
        "file",
        "ftp",
        "ftps",
        "git",
        "grpc",
        "http",
        "https",
        "mongodb",
        "mysql",
        "postgres",
        "postgresql",
        "redis",
        "rediss",
        "s3",
        "sftp",
        "smtp",
        "sqlite",
        "ssh",
        "tcp",
        "ws",
        "wss",
    }
)


@dataclass(frozen=True)
class UnresolvedAnnotation:
    """A value shaped like an annotation whose provider is not registered.

    Carries no resolved value — only the shape of the problem — so it is safe
    to render anywhere.
    """

    key: str
    value: str
    providers: tuple[str, ...]
    """Every scheme in the value that is not registered."""


@dataclass(frozen=True)
class AnnotationScan:
    """The result of scanning resolved config for remote annotations."""

    annotations: dict[str, list[SourceAnnotation]] = field(default_factory=dict)
    unresolved: list[UnresolvedAnnotation] = field(default_factory=list)

    def __bool__(self) -> bool:
        """True when anything remote was declared at all."""
        return bool(self.annotations or self.unresolved)


def _schemes(value: str) -> list[str]:
    """Every ``scheme`` in a value, treating a fallback chain as its parts.

    Returns an empty list when any part is not annotation-shaped, because a
    chain is only a chain when every entry is one — the same rule
    ``is_annotation`` applies.
    """
    parts = value.split(FALLBACK_SEPARATOR) if FALLBACK_SEPARATOR in value else [value]
    found: list[str] = []
    for part in parts:
        match = ANNOTATION_PATTERN.match(part.strip())
        if match is None:
            return []
        found.append(match.group(1))
    return found


def scan_annotations(
    values: Mapping[str, str],
    registered_providers: Iterable[str],
) -> AnnotationScan:
    """Find the remote annotations in a mapping of config values.

    Args:
        values: Config keys to their raw string values, located but not yet
            resolved. Scanning after resolution would be too late — the value
            would already have been consumed as a literal.
        registered_providers: Identifiers of the remote providers actually
            registered, e.g. ``{"aws-sm", "aws-ssm"}``. A value is an
            annotation only if its scheme is one of these.

    Returns:
        An :class:`AnnotationScan`. Values whose scheme is unregistered land in
        ``unresolved`` when they are not ordinary URLs, so a missing provider
        plugin is reported rather than silently read as a literal.
    """
    registered = set(registered_providers)
    scan = AnnotationScan()

    for key, value in values.items():
        if not isinstance(value, str):
            continue
        schemes = _schemes(value)
        if not schemes:
            continue

        if any(scheme in registered for scheme in schemes):
            # parse_annotation raises on a malformed chain and on one longer
            # than MAX_FALLBACK_CHAIN; both are the caller's error to see.
            parsed = parse_annotation(value)
            if parsed is not None:
                scan.annotations[key] = parsed
            # A chain may still name providers that are not installed. Those
            # entries simply fail over at resolution time, which is what a
            # fallback chain is for — but say so, rather than let a chain look
            # healthier than it is.
            missing = tuple(s for s in schemes if s not in registered)
            if missing:
                scan.unresolved.append(
                    UnresolvedAnnotation(key=key, value=value, providers=missing)
                )
            continue

        # Nothing in the value is registered. If every scheme is an ordinary
        # URL scheme this is just a URL; otherwise it is very likely a
        # credential reference whose plugin is not installed.
        if all(scheme in _COMMON_URL_SCHEMES for scheme in schemes):
            continue
        scan.unresolved.append(
            UnresolvedAnnotation(key=key, value=value, providers=tuple(schemes))
        )

    return scan
