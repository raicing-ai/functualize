"""Property-based tests for used flag filtering.

# Feature: tui-architecture-v2, Property 9: Used flag filtering

Tests filter_used_flags() from functualize._cli.flag_filtering:
- Property 9: Used flag filtering

**Validates: Requirements 13.5, 20.3, 20.4**
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._cli.completions.flag_filtering import (
    FlagDescriptor,
    filter_used_flags,
)

# =============================================================================
# Strategies
# =============================================================================

# Valid flag long names: lowercase alphanumeric + hyphens, 1-20 chars
_flag_name_strategy = st.from_regex(r"[a-z][a-z0-9\-]{0,19}", fullmatch=True)

# Valid short flag names: single lowercase letter
_short_name_strategy = st.one_of(st.none(), st.from_regex(r"[a-z]", fullmatch=True))


@st.composite
def _flag_descriptor_strategy(draw: st.DrawFn) -> FlagDescriptor:
    """Generate a FlagDescriptor with unique long_name."""
    long_name = draw(_flag_name_strategy)
    short_name = draw(_short_name_strategy)
    is_list_type = draw(st.booleans())
    return FlagDescriptor(
        long_name=long_name, short_name=short_name, is_list_type=is_list_type
    )


@st.composite
def _unique_flag_list_strategy(draw: st.DrawFn) -> list[FlagDescriptor]:
    """Generate a list of FlagDescriptors with unique long_names."""
    flags = draw(st.lists(_flag_descriptor_strategy(), min_size=1, max_size=15))
    # Deduplicate by long_name
    seen_long: set[str] = set()
    seen_short: set[str] = set()
    unique_flags: list[FlagDescriptor] = []
    for flag in flags:
        if flag.long_name in seen_long:
            continue
        if flag.short_name and flag.short_name in seen_short:
            # Remove short name conflict by making it None
            flag = FlagDescriptor(
                long_name=flag.long_name,
                short_name=None,
                is_list_type=flag.is_list_type,
            )
        seen_long.add(flag.long_name)
        if flag.short_name:
            seen_short.add(flag.short_name)
        unique_flags.append(flag)
    return (
        unique_flags
        if unique_flags
        else [FlagDescriptor(long_name="fallback", is_list_type=False)]
    )


@st.composite
def _used_tokens_from_flags(draw: st.DrawFn, flags: list[FlagDescriptor]) -> list[str]:
    """Pick a subset of flags and generate used tokens (long or short form)."""
    if not flags:
        return []
    subset_indices = draw(
        st.lists(
            st.integers(min_value=0, max_value=len(flags) - 1),
            min_size=0,
            max_size=len(flags),
            unique=True,
        )
    )
    tokens: list[str] = []
    for idx in subset_indices:
        flag = flags[idx]
        # Choose long or short form
        use_short = flag.short_name is not None and draw(st.booleans())
        if use_short:
            tokens.append(f"-{flag.short_name}")
        else:
            tokens.append(f"--{flag.long_name}")
    return tokens


@st.composite
def _flag_filtering_scenario(draw: st.DrawFn) -> tuple[list[FlagDescriptor], list[str]]:
    """Generate a complete scenario: flags + used tokens from those flags."""
    flags = draw(_unique_flag_list_strategy())
    tokens = draw(_used_tokens_from_flags(flags))
    return flags, tokens


# =============================================================================
# Property 9: Used flag filtering
# =============================================================================


@pytest.mark.slow
class TestUsedFlagFiltering:
    """Property 9: Used flag filtering.

    For any set of job fields (some list-typed, some single-value) and any set
    of flags already used in the command text (in short or long form),
    single-value flags that have been used should be excluded from candidates,
    while list-typed flags should always remain available regardless of prior use.

    **Validates: Requirements 13.5, 20.3, 20.4**
    """

    @given(scenario=_flag_filtering_scenario())
    @settings(max_examples=100)
    def test_list_typed_flags_always_in_result(
        self, scenario: tuple[list[FlagDescriptor], list[str]]
    ) -> None:
        """List-typed flags remain available regardless of usage (Req 20.3)."""
        flags, used_tokens = scenario
        result = filter_used_flags(flags, used_tokens)
        list_flags = [f for f in flags if f.is_list_type]
        for flag in list_flags:
            assert flag in result, (
                f"List-typed flag --{flag.long_name} should always be in result"
            )

    @given(scenario=_flag_filtering_scenario())
    @settings(max_examples=100)
    def test_used_single_value_flags_excluded(
        self, scenario: tuple[list[FlagDescriptor], list[str]]
    ) -> None:
        """Single-value flags that were used are excluded from result (Req 20.4)."""
        flags, used_tokens = scenario
        result = filter_used_flags(flags, used_tokens)

        # Determine which long names are "used"
        short_to_long = {f.short_name: f.long_name for f in flags if f.short_name}
        used_long_names: set[str] = set()
        for token in used_tokens:
            if token.startswith("--"):
                used_long_names.add(token[2:].split("=", 1)[0])
            elif token.startswith("-") and len(token) >= 2:
                short = token[1:].split("=", 1)[0]
                if short in short_to_long:
                    used_long_names.add(short_to_long[short])

        for flag in flags:
            if not flag.is_list_type and flag.long_name in used_long_names:
                assert flag not in result, (
                    f"Single-value flag --{flag.long_name} was used and should be excluded"
                )

    @given(scenario=_flag_filtering_scenario())
    @settings(max_examples=100)
    def test_unused_single_value_flags_in_result(
        self, scenario: tuple[list[FlagDescriptor], list[str]]
    ) -> None:
        """Single-value flags NOT used remain in result (Req 13.5)."""
        flags, used_tokens = scenario
        result = filter_used_flags(flags, used_tokens)

        # Determine which long names are "used"
        short_to_long = {f.short_name: f.long_name for f in flags if f.short_name}
        used_long_names: set[str] = set()
        for token in used_tokens:
            if token.startswith("--"):
                used_long_names.add(token[2:].split("=", 1)[0])
            elif token.startswith("-") and len(token) >= 2:
                short = token[1:].split("=", 1)[0]
                if short in short_to_long:
                    used_long_names.add(short_to_long[short])

        for flag in flags:
            if not flag.is_list_type and flag.long_name not in used_long_names:
                assert flag in result, (
                    f"Unused single-value flag --{flag.long_name} should remain in result"
                )

    @given(scenario=_flag_filtering_scenario())
    @settings(max_examples=100)
    def test_result_is_subset_of_input(
        self, scenario: tuple[list[FlagDescriptor], list[str]]
    ) -> None:
        """Result never contains flags not in the original input list."""
        flags, used_tokens = scenario
        result = filter_used_flags(flags, used_tokens)
        for flag in result:
            assert flag in flags, (
                f"Result flag --{flag.long_name} not in original input"
            )

    @given(flags=_unique_flag_list_strategy())
    @settings(max_examples=100)
    def test_no_used_tokens_returns_all_flags(
        self, flags: list[FlagDescriptor]
    ) -> None:
        """When no tokens are used, all flags remain available."""
        result = filter_used_flags(flags, [])
        assert result == flags
