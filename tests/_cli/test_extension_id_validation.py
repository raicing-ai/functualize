"""Property-based tests for extension ID validation (Property 16).

# Feature: tui-architecture-v2, Property 16: Extension ID validation

Tests validate_extension_id from functualize.plugin.protocols:
- Valid IDs: non-empty, lowercase alphanumeric + hyphens + underscores, max 64 chars
- Invalid IDs: empty, uppercase, special chars, too long
"""

from __future__ import annotations

import re
import string

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize.plugin.protocols import validate_extension_id

# =============================================================================
# Strategies
# =============================================================================

# Characters allowed in valid extension IDs
_VALID_CHARS = string.ascii_lowercase + string.digits + "-_"

# Strategy: valid extension IDs (non-empty, valid chars, max 64)
_valid_id_strategy = st.text(
    alphabet=_VALID_CHARS,
    min_size=1,
    max_size=64,
)

# Strategy: IDs that are too long (valid chars but > 64 chars)
_too_long_id_strategy = st.text(
    alphabet=_VALID_CHARS,
    min_size=65,
    max_size=128,
)

# Strategy: IDs containing invalid characters (at least one char outside valid set)
_INVALID_CHAR_ALPHABET = st.characters(
    exclude_characters=_VALID_CHARS,
    categories=("L", "Lu", "N", "P", "S", "Z"),
)


@st.composite
def _id_with_invalid_chars(draw: st.DrawFn) -> str:
    """Generate a non-empty string that contains at least one invalid character."""
    # Build a string with at least one invalid char mixed in
    valid_prefix = draw(st.text(alphabet=_VALID_CHARS, min_size=0, max_size=30))
    invalid_char = draw(_INVALID_CHAR_ALPHABET)
    valid_suffix = draw(st.text(alphabet=_VALID_CHARS, min_size=0, max_size=30))
    result = valid_prefix + invalid_char + valid_suffix
    # Ensure it fits in a reasonable length for testing
    return result[:64] if len(result) > 64 else result


# =============================================================================
# Property 16: Extension ID validation
# =============================================================================

_VALID_PATTERN = re.compile(r"^[a-z0-9_-]+$")


@pytest.mark.slow
class TestExtensionIdValidation:
    """Property 16: Extension ID validation.

    For any string used as an extension id (display_id, panel_id, item_id,
    theme_id), it should be accepted only if it is non-empty, contains only
    lowercase alphanumeric characters, hyphens, and underscores, and has a
    maximum length of 64 characters. All other strings should be rejected.

    **Validates: Requirements 17.12**
    """

    @given(ext_id=_valid_id_strategy)
    def test_valid_ids_are_accepted(self, ext_id: str) -> None:
        """IDs with only valid chars, non-empty, and <= 64 chars are accepted.

        **Validates: Requirements 17.12**
        """
        assert validate_extension_id(ext_id) is True

    @given(ext_id=_too_long_id_strategy)
    def test_too_long_ids_are_rejected(self, ext_id: str) -> None:
        """IDs exceeding 64 characters are rejected even if chars are valid.

        **Validates: Requirements 17.12**
        """
        assert validate_extension_id(ext_id) is False

    @given(ext_id=_id_with_invalid_chars())
    def test_ids_with_invalid_chars_are_rejected(self, ext_id: str) -> None:
        """IDs containing characters outside [a-z0-9_-] are rejected.

        **Validates: Requirements 17.12**
        """
        assert validate_extension_id(ext_id) is False

    def test_empty_string_is_rejected(self) -> None:
        """Empty string is always rejected.

        **Validates: Requirements 17.12**
        """
        assert validate_extension_id("") is False

    @given(ext_id=st.text(min_size=0, max_size=128))
    def test_acceptance_matches_spec_rules(self, ext_id: str) -> None:
        """For any arbitrary string, validate_extension_id returns True iff
        the string is non-empty, <= 64 chars, and matches [a-z0-9_-]+.

        **Validates: Requirements 17.12**
        """
        expected = (
            len(ext_id) > 0
            and len(ext_id) <= 64
            and _VALID_PATTERN.match(ext_id) is not None
        )
        assert validate_extension_id(ext_id) is expected
