"""Property-based tests for the manifest/annotation parser.

Property 2: Annotation classification
Validates: Requirements 4.3, 4.7
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from functualize._config.manifest import (
    SourceAnnotation,
    is_annotation,
    parse_annotation,
)

# --- Strategies ---

# Strategy for valid provider names: starts with [a-z], followed by [a-z0-9_-]*
_provider_first_char = st.sampled_from("abcdefghijklmnopqrstuvwxyz")
_provider_rest_chars = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789_-"),
    min_size=0,
    max_size=15,
)
valid_providers = st.builds(
    lambda f, r: f + r, _provider_first_char, _provider_rest_chars
)

# Strategy for non-empty references (anything that doesn't contain the fallback separator)
valid_references = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S"),
        blacklist_characters="\x00",
    ),
    min_size=1,
    max_size=50,
).filter(lambda s: " | " not in s)

# Strategy for valid single annotations: "provider://reference"
valid_annotations = st.builds(
    lambda p, r: f"{p}://{r}",
    valid_providers,
    valid_references,
)

# Strategy for strings that do NOT match the annotation pattern.
# These are literals: no "://" at all, or invalid provider prefix.
literal_strings_no_scheme = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        blacklist_characters="\x00",
    ),
    min_size=0,
    max_size=50,
).filter(lambda s: "://" not in s and " | " not in s)

# Strings with "://" but invalid provider (starts with uppercase, digit, or special)
invalid_provider_starts = st.sampled_from("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-!@#$%")
invalid_provider_annotations = st.builds(
    lambda c, rest, ref: f"{c}{rest}://{ref}",
    invalid_provider_starts,
    st.text(
        alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789"),
        min_size=0,
        max_size=10,
    ),
    st.text(min_size=1, max_size=20).filter(lambda s: " | " not in s),
)

# Empty reference (provider://) — should not match
empty_reference_annotations = st.builds(
    lambda p: f"{p}://",
    valid_providers,
)

# Combined strategy for non-annotation strings (literals)
literal_strings = st.one_of(
    literal_strings_no_scheme,
    invalid_provider_annotations,
    empty_reference_annotations,
)


# --- Property 2: Annotation Classification ---


class TestProperty2AnnotationClassification:
    """Any string matching `provider://reference` pattern (where provider is
    `[a-z][a-z0-9_-]*` and reference is non-empty) is classified as an annotation
    by `is_annotation()`. Any string NOT matching the pattern is classified as a
    literal (is_annotation returns False, parse_annotation returns None).

    **Validates: Requirements 4.3, 4.7**
    """

    @given(annotation=valid_annotations)
    def test_valid_annotation_is_classified_as_annotation(
        self, annotation: str
    ) -> None:
        """Any string matching provider://reference is classified as an annotation."""
        assert is_annotation(annotation) is True

    @given(literal=literal_strings)
    def test_non_matching_string_is_classified_as_literal(self, literal: str) -> None:
        """Any string NOT matching the pattern is classified as a literal."""
        assert is_annotation(literal) is False

    @given(literal=literal_strings)
    def test_parse_annotation_returns_none_for_literals(self, literal: str) -> None:
        """parse_annotation returns None for non-annotation strings."""
        assert parse_annotation(literal) is None

    @given(provider=valid_providers, reference=valid_references)
    def test_parse_annotation_extracts_correct_provider_and_reference(
        self, provider: str, reference: str
    ) -> None:
        """parse_annotation returns the correct provider and reference for valid annotations."""
        annotation = f"{provider}://{reference}"
        result = parse_annotation(annotation)
        assert result is not None
        assert len(result) == 1
        assert result[0] == SourceAnnotation(provider=provider, reference=reference)

    @given(provider=valid_providers, reference=valid_references)
    def test_provider_starts_with_lowercase_letter(
        self, provider: str, reference: str
    ) -> None:
        """The provider name extracted always starts with a lowercase letter."""
        annotation = f"{provider}://{reference}"
        result = parse_annotation(annotation)
        assert result is not None
        assert result[0].provider[0].islower()
        assert result[0].provider[0].isalpha()

    @given(annotation=valid_annotations)
    def test_is_annotation_and_parse_annotation_agree(self, annotation: str) -> None:
        """For valid single annotations, is_annotation() and parse_annotation() is not None always agree."""
        is_ann = is_annotation(annotation)
        parsed = parse_annotation(annotation)
        assert is_ann == (parsed is not None)
