"""Manifest/annotation parser for 'provider://reference' source syntax.

Parses declarative source annotations from configuration values, supporting
single providers and ordered fallback chains with pipe separators.

Annotation syntax: "provider://reference"
Fallback syntax:   "vault://secrets/db | aws-sm://prod/db"
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Pattern: provider name must start with lowercase letter, followed by
# lowercase letters, digits, underscores, or hyphens. Reference is everything
# after "://".
ANNOTATION_PATTERN: re.Pattern[str] = re.compile(r"^([a-z][a-z0-9_-]*)://(.+)$")

FALLBACK_SEPARATOR: str = " | "
MAX_FALLBACK_CHAIN: int = 5


@dataclass(frozen=True)
class SourceAnnotation:
    """A parsed source annotation from a config value.

    Attributes:
        provider: The provider identifier (e.g., 'vault', 'aws-sm').
        reference: The resource path/key within the provider.
    """

    provider: str
    reference: str


def parse_annotation(value: str) -> list[SourceAnnotation] | None:
    """Parse a 'provider://reference' string into SourceAnnotations.

    Returns None if the value is a literal (doesn't match annotation pattern).
    Returns a list of SourceAnnotations for fallback chains.

    Fallback syntax: "vault://secrets/db_pass | aws-sm://prod/db_pass"
    Maximum 5 sources in a fallback chain.

    Args:
        value: The string value to parse.

    Returns:
        A list of SourceAnnotation instances if the value is an annotation,
        or None if it's a literal string value.

    Raises:
        ValueError: If the fallback chain exceeds MAX_FALLBACK_CHAIN entries,
            or if any entry in a fallback chain is not a valid annotation.
    """
    # Check if the value contains a fallback chain
    if FALLBACK_SEPARATOR in value:
        parts = value.split(FALLBACK_SEPARATOR)

        if len(parts) > MAX_FALLBACK_CHAIN:
            msg = (
                f"Fallback chain exceeds maximum of {MAX_FALLBACK_CHAIN} entries "
                f"(got {len(parts)})"
            )
            raise ValueError(msg)

        annotations: list[SourceAnnotation] = []
        for part in parts:
            stripped = part.strip()
            match = ANNOTATION_PATTERN.match(stripped)
            if match is None:
                msg = (
                    f"Invalid annotation in fallback chain: {stripped!r} "
                    f"does not match 'provider://reference' pattern"
                )
                raise ValueError(msg)
            annotations.append(
                SourceAnnotation(provider=match.group(1), reference=match.group(2))
            )
        return annotations

    # Single annotation check
    match = ANNOTATION_PATTERN.match(value)
    if match is None:
        return None

    return [SourceAnnotation(provider=match.group(1), reference=match.group(2))]


def is_annotation(value: str) -> bool:
    """Check if a string value is a source annotation (not a literal).

    A value is considered an annotation if it matches the 'provider://reference'
    pattern, either as a single annotation or as part of a fallback chain.

    Args:
        value: The string value to check.

    Returns:
        True if the value is an annotation, False if it's a literal.
    """
    if FALLBACK_SEPARATOR in value:
        parts = value.split(FALLBACK_SEPARATOR)
        return all(ANNOTATION_PATTERN.match(part.strip()) is not None for part in parts)
    return ANNOTATION_PATTERN.match(value) is not None
