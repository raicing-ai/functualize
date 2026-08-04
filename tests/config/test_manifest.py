"""Unit tests for the manifest/annotation parser."""

import pytest

from functualize._config.manifest import (
    ANNOTATION_PATTERN,
    FALLBACK_SEPARATOR,
    MAX_FALLBACK_CHAIN,
    SourceAnnotation,
    is_annotation,
    parse_annotation,
)


class TestAnnotationPattern:
    """Tests for the ANNOTATION_PATTERN regex."""

    def test_matches_simple_provider(self) -> None:
        match = ANNOTATION_PATTERN.match("vault://secrets/db_pass")
        assert match is not None
        assert match.group(1) == "vault"
        assert match.group(2) == "secrets/db_pass"

    def test_matches_provider_with_hyphens(self) -> None:
        match = ANNOTATION_PATTERN.match("aws-sm://prod/db_pass")
        assert match is not None
        assert match.group(1) == "aws-sm"
        assert match.group(2) == "prod/db_pass"

    def test_matches_provider_with_underscores(self) -> None:
        match = ANNOTATION_PATTERN.match("my_provider://ref")
        assert match is not None
        assert match.group(1) == "my_provider"

    def test_matches_provider_with_digits(self) -> None:
        match = ANNOTATION_PATTERN.match("vault2://path")
        assert match is not None
        assert match.group(1) == "vault2"

    def test_rejects_uppercase_provider(self) -> None:
        assert ANNOTATION_PATTERN.match("Vault://path") is None

    def test_rejects_digit_start_provider(self) -> None:
        assert ANNOTATION_PATTERN.match("1vault://path") is None

    def test_rejects_no_reference(self) -> None:
        assert ANNOTATION_PATTERN.match("vault://") is None

    def test_rejects_plain_string(self) -> None:
        assert ANNOTATION_PATTERN.match("just a value") is None

    def test_rejects_url_like_without_valid_provider(self) -> None:
        assert ANNOTATION_PATTERN.match("://something") is None

    def test_reference_can_contain_special_chars(self) -> None:
        match = ANNOTATION_PATTERN.match("vault://path/to/secret?version=2")
        assert match is not None
        assert match.group(2) == "path/to/secret?version=2"


class TestParseAnnotation:
    """Tests for parse_annotation function."""

    def test_returns_none_for_literal(self) -> None:
        assert parse_annotation("just a plain value") is None

    def test_returns_none_for_empty_string(self) -> None:
        assert parse_annotation("") is None

    def test_returns_none_for_number_string(self) -> None:
        assert parse_annotation("12345") is None

    def test_parses_single_annotation(self) -> None:
        result = parse_annotation("vault://secrets/db_pass")
        assert result is not None
        assert len(result) == 1
        assert result[0] == SourceAnnotation(
            provider="vault", reference="secrets/db_pass"
        )

    def test_parses_fallback_chain(self) -> None:
        result = parse_annotation("vault://secrets/db_pass | aws-sm://prod/db_pass")
        assert result is not None
        assert len(result) == 2
        assert result[0] == SourceAnnotation(
            provider="vault", reference="secrets/db_pass"
        )
        assert result[1] == SourceAnnotation(
            provider="aws-sm", reference="prod/db_pass"
        )

    def test_parses_max_fallback_chain(self) -> None:
        annotations = " | ".join(f"p{i}://ref{i}" for i in range(5))
        result = parse_annotation(annotations)
        assert result is not None
        assert len(result) == 5

    def test_raises_on_exceeding_max_chain(self) -> None:
        annotations = " | ".join(f"p{i}://ref{i}" for i in range(6))
        with pytest.raises(ValueError, match="exceeds maximum"):
            parse_annotation(annotations)

    def test_raises_on_invalid_entry_in_chain(self) -> None:
        with pytest.raises(ValueError, match="Invalid annotation"):
            parse_annotation("vault://secret | not_valid")

    def test_provider_and_reference_extracted_correctly(self) -> None:
        result = parse_annotation("infisical://projects/myapp/secrets/API_KEY")
        assert result is not None
        assert result[0].provider == "infisical"
        assert result[0].reference == "projects/myapp/secrets/API_KEY"

    def test_returns_none_for_url_without_valid_provider(self) -> None:
        # Uppercase doesn't match
        assert parse_annotation("HTTP://example.com") is None

    def test_reference_preserves_spaces(self) -> None:
        # A reference with spaces (no pipe separator) is valid
        result = parse_annotation("vault://path with spaces")
        assert result is not None
        assert result[0].reference == "path with spaces"


class TestIsAnnotation:
    """Tests for is_annotation function."""

    def test_true_for_valid_annotation(self) -> None:
        assert is_annotation("vault://secrets/key") is True

    def test_false_for_literal(self) -> None:
        assert is_annotation("just a string") is False

    def test_false_for_empty_string(self) -> None:
        assert is_annotation("") is False

    def test_true_for_fallback_chain(self) -> None:
        assert is_annotation("vault://a | aws-sm://b") is True

    def test_false_for_partial_chain(self) -> None:
        # One valid, one invalid in chain
        assert is_annotation("vault://a | not_valid") is False

    def test_true_for_url_like_with_valid_provider_name(self) -> None:
        # "https" matches [a-z][a-z0-9_-]* pattern, so it's treated as a provider
        assert is_annotation("https://example.com") is True

    def test_false_for_uppercase_scheme(self) -> None:
        # Uppercase doesn't match provider pattern
        assert is_annotation("HTTPS://example.com") is False

    def test_true_for_hyphenated_provider(self) -> None:
        assert is_annotation("aws-sm://prod/secret") is True


class TestConstants:
    """Tests for module-level constants."""

    def test_fallback_separator(self) -> None:
        assert FALLBACK_SEPARATOR == " | "

    def test_max_fallback_chain(self) -> None:
        assert MAX_FALLBACK_CHAIN == 5

    def test_annotation_pattern_is_compiled(self) -> None:
        import re

        assert isinstance(ANNOTATION_PATTERN, re.Pattern)
