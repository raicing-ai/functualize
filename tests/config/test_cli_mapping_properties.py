"""Property-based tests for CLI option name to config key path mapping.

Tests Property 14 from the design document.

**Validates: Requirements 6.5**
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from functualize._config.sources import CliSource

# --- Strategies ---

# Strategy for valid CLI key segments (alphanumeric + hyphens, no leading/trailing hyphens)
_key_segment_chars = st.characters(
    whitelist_categories=("Ll", "Nd"), whitelist_characters="-_"
)

# A segment that looks like a CLI option name part (e.g., "my-option", "port")
cli_segment = st.text(
    alphabet=st.characters(whitelist_categories=("Ll",), whitelist_characters="-"),
    min_size=1,
    max_size=15,
).filter(lambda s: s[0].isalpha() and not s.endswith("-") and "--" not in s)

# Leading dash prefixes (as seen in CLI options)
leading_dashes = st.sampled_from(["", "-", "--"])

# Strategy for CLI option names without dots (simple keys)
simple_cli_option = st.builds(
    lambda prefix, segment: prefix + segment,
    leading_dashes,
    cli_segment,
)

# Strategy for dot-namespaced CLI option names (section.key)
namespaced_cli_option = st.builds(
    lambda prefix, section, key: f"{prefix}{section}.{key}",
    leading_dashes,
    cli_segment,
    cli_segment,
)

# Strategy for any CLI option name
any_cli_option = st.one_of(simple_cli_option, namespaced_cli_option)

# Strategy for config values
config_values = st.one_of(
    st.text(min_size=0, max_size=20),
    st.integers(min_value=-1000, max_value=1000),
    st.booleans(),
)


# --- Property 14: CLI option name to key path mapping ---


class TestProperty14CliOptionNameToKeyPathMapping:
    """The adapter SHALL deterministically map CLI option names to configuration
    key paths (underscore-separated, dot-namespaced) such that:
    - Hyphens are converted to underscores
    - Leading dashes are stripped
    - Dot-separated names produce (section, key) tuples
    - The mapping is deterministic
    - No information is lost (original value is retrievable via mapped key)

    **Validates: Requirements 6.5**
    """

    @given(option=simple_cli_option)
    def test_hyphens_always_converted_to_underscores(self, option: str) -> None:
        """Hyphens in option names are always converted to underscores in
        the resulting key."""
        section, key = CliSource._parse_cli_key(option)
        assert "-" not in key
        if section is not None:
            assert "-" not in section

    @given(option=any_cli_option)
    def test_leading_dashes_always_stripped(self, option: str) -> None:
        """Leading dashes (-- or -) are always stripped from the result."""
        section, key = CliSource._parse_cli_key(option)
        assert not key.startswith("-")
        if section is not None:
            assert not section.startswith("-")

    @given(prefix=leading_dashes, section_name=cli_segment, key_name=cli_segment)
    def test_dot_separated_produces_section_key_tuple(
        self, prefix: str, section_name: str, key_name: str
    ) -> None:
        """Dot-separated names always produce (section, key) tuples where
        section is before the dot and key is after."""
        raw = f"{prefix}{section_name}.{key_name}"
        section, key = CliSource._parse_cli_key(raw)

        # A dot-separated input always yields a non-None section
        assert section is not None
        # The section corresponds to the part before the dot (hyphens → underscores)
        assert section == section_name.replace("-", "_")
        # The key corresponds to the part after the dot (hyphens → underscores)
        assert key == key_name.replace("-", "_")

    @given(option=any_cli_option)
    def test_mapping_is_deterministic(self, option: str) -> None:
        """The mapping is deterministic: same input always produces same output."""
        result1 = CliSource._parse_cli_key(option)
        result2 = CliSource._parse_cli_key(option)
        assert result1 == result2

    @given(option=any_cli_option, value=config_values)
    def test_value_retrievable_via_mapped_key(self, option: str, value: object) -> None:
        """No information is lost: the original CLI value is always retrievable
        via the mapped key/section."""
        source = CliSource({option: value})
        section, key = CliSource._parse_cli_key(option)
        retrieved = source.get(key, section=section)
        assert retrieved == value

    @given(prefix=leading_dashes, segment=cli_segment)
    def test_simple_key_has_no_section(self, prefix: str, segment: str) -> None:
        """A simple option name without dots produces section=None."""
        raw = f"{prefix}{segment}"
        section, key = CliSource._parse_cli_key(raw)
        assert section is None
        assert key == segment.replace("-", "_")

    @given(
        option1=any_cli_option,
        option2=any_cli_option,
        val1=config_values,
        val2=config_values,
    )
    def test_multiple_options_independently_retrievable(
        self, option1: str, option2: str, val1: object, val2: object
    ) -> None:
        """Multiple CLI options are independently retrievable via their mapped keys."""
        sec1, key1 = CliSource._parse_cli_key(option1)
        sec2, key2 = CliSource._parse_cli_key(option2)

        # Only test when keys don't collide (different mapped paths)
        if (sec1, key1) == (sec2, key2):
            # Same mapped path — last write wins (dict behavior), still retrievable
            source = CliSource({option1: val1, option2: val2})
            result = source.get(key2, section=sec2)
            assert result == val2
        else:
            source = CliSource({option1: val1, option2: val2})
            assert source.get(key1, section=sec1) == val1
            assert source.get(key2, section=sec2) == val2

    @given(prefix=leading_dashes, segment=cli_segment)
    def test_underscore_conversion_preserves_length(
        self, prefix: str, segment: str
    ) -> None:
        """After stripping dashes and converting hyphens, the key length equals
        the cleaned segment length (hyphen→underscore is 1:1)."""
        raw = f"{prefix}{segment}"
        section, key = CliSource._parse_cli_key(raw)
        # segment with hyphens replaced should equal key
        assert len(key) == len(segment)
