"""Property-based tests for fallback chain parsing in manifest.py.

**Validates: Requirements 4.5**

Property 3: Fallback chain parsing respects max-5 constraint.
"""

from __future__ import annotations

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from functualize._config.manifest import (
    FALLBACK_SEPARATOR,
    MAX_FALLBACK_CHAIN,
    SourceAnnotation,
    parse_annotation,
)

# --- Strategies ---

# Strategy for valid provider names: starts with lowercase letter, followed by
# lowercase letters, digits, underscores, or hyphens.
valid_providers = st.from_regex(r"[a-z][a-z0-9_\-]{0,14}", fullmatch=True)

# Strategy for valid references: non-empty strings that don't contain the
# fallback separator sequence " | " (to avoid ambiguous splits).
valid_references = st.text(
    alphabet=st.characters(
        whitelist_categories=("Ll", "Lu", "Nd"),
        whitelist_characters="/._-",
    ),
    min_size=1,
    max_size=30,
).filter(lambda s: " | " not in s)

# Strategy for a single valid annotation string
valid_annotation_strings = st.builds(
    lambda p, r: f"{p}://{r}",
    valid_providers,
    valid_references,
)

# Strategy for invalid annotation entries (don't match provider://reference)
invalid_entries = st.one_of(
    st.just("not_an_annotation"),
    st.just("UPPERCASE://ref"),
    st.just("123://ref"),
    st.just("://no_provider"),
    st.just("provider_only"),
    st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")),
        min_size=1,
        max_size=10,
    ).filter(lambda s: "://" not in s),
)


class TestProperty3FallbackChainMaxConstraint:
    """Property 3: Fallback chain parsing respects max-5 constraint.

    **Validates: Requirements 4.5**

    For any fallback chain of annotations:
    1. Chains with 1-5 valid annotations always parse successfully and return
       the correct number of annotations.
    2. Chains with >5 entries always raise ValueError.
    3. The order of annotations in the chain is preserved in the parsed result.
    4. Each annotation in the chain has its provider and reference correctly extracted.
    5. If any single entry in the chain is not a valid annotation, ValueError is raised.
    """

    @given(
        annotations=st.lists(
            st.tuples(valid_providers, valid_references),
            min_size=1,
            max_size=MAX_FALLBACK_CHAIN,
        )
    )
    @settings(max_examples=200)
    def test_valid_chains_parse_with_correct_count(
        self, annotations: list[tuple[str, str]]
    ) -> None:
        """Fallback chains with 1-5 valid annotations always parse successfully
        and return the correct number of annotations."""
        chain_str = FALLBACK_SEPARATOR.join(
            f"{provider}://{ref}" for provider, ref in annotations
        )

        result = parse_annotation(chain_str)

        assert result is not None
        assert len(result) == len(annotations)

    @given(
        annotations=st.lists(
            st.tuples(valid_providers, valid_references),
            min_size=MAX_FALLBACK_CHAIN + 1,
            max_size=MAX_FALLBACK_CHAIN + 5,
        )
    )
    @settings(max_examples=200)
    def test_exceeding_max_chain_raises_value_error(
        self, annotations: list[tuple[str, str]]
    ) -> None:
        """Fallback chains with >5 entries always raise ValueError with
        'exceeds maximum' in the message."""
        chain_str = FALLBACK_SEPARATOR.join(
            f"{provider}://{ref}" for provider, ref in annotations
        )

        with pytest.raises(ValueError, match="exceeds maximum"):
            parse_annotation(chain_str)

    @given(
        annotations=st.lists(
            st.tuples(valid_providers, valid_references),
            min_size=2,
            max_size=MAX_FALLBACK_CHAIN,
        )
    )
    @settings(max_examples=200)
    def test_order_is_preserved(self, annotations: list[tuple[str, str]]) -> None:
        """The order of annotations in the chain is preserved in the parsed result."""
        chain_str = FALLBACK_SEPARATOR.join(
            f"{provider}://{ref}" for provider, ref in annotations
        )

        result = parse_annotation(chain_str)

        assert result is not None
        for i, (provider, ref) in enumerate(annotations):
            assert result[i].provider == provider
            assert result[i].reference == ref

    @given(
        annotations=st.lists(
            st.tuples(valid_providers, valid_references),
            min_size=1,
            max_size=MAX_FALLBACK_CHAIN,
        )
    )
    @settings(max_examples=200)
    def test_provider_and_reference_correctly_extracted(
        self, annotations: list[tuple[str, str]]
    ) -> None:
        """Each annotation in the chain has its provider and reference correctly
        extracted as SourceAnnotation instances."""
        chain_str = FALLBACK_SEPARATOR.join(
            f"{provider}://{ref}" for provider, ref in annotations
        )

        result = parse_annotation(chain_str)

        assert result is not None
        for i, (provider, ref) in enumerate(annotations):
            assert isinstance(result[i], SourceAnnotation)
            assert result[i].provider == provider
            assert result[i].reference == ref

    @given(
        valid_annotations=st.lists(
            st.tuples(valid_providers, valid_references),
            min_size=0,
            max_size=MAX_FALLBACK_CHAIN - 1,
        ),
        invalid_entry=invalid_entries,
        insert_position=st.integers(min_value=0, max_value=100),
    )
    @settings(max_examples=200)
    def test_invalid_entry_in_chain_raises_value_error(
        self,
        valid_annotations: list[tuple[str, str]],
        invalid_entry: str,
        insert_position: int,
    ) -> None:
        """If any single entry in the chain is not a valid annotation,
        ValueError is raised with 'Invalid annotation' in the message."""
        # Build a list of annotation strings with one invalid entry inserted
        parts = [f"{provider}://{ref}" for provider, ref in valid_annotations]

        # Clamp insert position to valid range
        pos = insert_position % (len(parts) + 1)
        parts.insert(pos, invalid_entry)

        # Only test when total size is within max chain length (otherwise
        # we'd get the "exceeds maximum" error instead)
        assume(len(parts) <= MAX_FALLBACK_CHAIN)
        # Must have at least 2 parts to trigger the fallback chain path
        assume(len(parts) >= 2)

        chain_str = FALLBACK_SEPARATOR.join(parts)

        with pytest.raises(ValueError, match="Invalid annotation"):
            parse_annotation(chain_str)
