"""Property-based tests for CLI annotation parsing utilities.

# Feature: cli-unix-compatibility, Properties 1, 2, 3
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.annotation_utils import parse_annotation
from functualize._primitives.di import Provide
from functualize.job import (
    Invoke,
    JobConfigView,
    JobContext,
    Log,
    Perf,
    Prompt,
    RunContext,
    State,
)

# =============================================================================
# Constants
# =============================================================================

#: All DI-registered capability types that should be classified as DI params.
DI_TYPES: tuple[type, ...] = (
    RunContext,
    Log,
    Invoke,
    Prompt,
    Perf,
    State,
    JobContext,
    JobConfigView,
)

#: CLI-compatible types that map to CLI options.
CLI_TYPES: tuple[type, ...] = (str, int, float, bool, Path)


# =============================================================================
# Strategies
# =============================================================================

# Strategy: pick one of the CLI-compatible base types
_cli_type = st.sampled_from(CLI_TYPES)

# Strategy: pick one of the DI types
_di_type = st.sampled_from(DI_TYPES)

# Strategy: arbitrary metadata objects (strings, ints, simple objects)
# These simulate random Annotated metadata that isn't a Provide marker or DI type.
_arbitrary_metadata_item = st.one_of(
    st.text(min_size=0, max_size=20),
    st.integers(min_value=-1000, max_value=1000),
    st.floats(allow_nan=False, allow_infinity=False),
    st.booleans(),
    st.none(),
    st.just(object()),
)

# Strategy: a tuple of arbitrary metadata (1-5 items, no Provide markers)
_metadata_tuple = st.lists(
    _arbitrary_metadata_item,
    min_size=1,
    max_size=5,
).map(tuple)


# =============================================================================
# Property 1: Annotated Transparency
# =============================================================================


@pytest.mark.slow
class TestAnnotatedTransparency:
    """Property 1: Annotated Transparency.

    For any CLI-compatible type T and any metadata tuple,
    `parse_annotation(Annotated[T, *meta]).base_type == T`.

    **Validates: Requirements 1.1, 1.3**
    """

    @given(base_type=_cli_type, metadata=_metadata_tuple)
    def test_base_type_preserved_through_annotated(
        self, base_type: type, metadata: tuple[Any, ...]
    ):
        """The base type is always recovered after unwrapping Annotated.

        **Validates: Requirements 1.1, 1.3**
        """
        # Build Annotated[T, *metadata]
        annotated = Annotated[
            tuple(  # type: ignore[misc]
                [base_type, *metadata]
            )
        ]
        result = parse_annotation(annotated)

        assert result.base_type == base_type, (
            f"Expected base_type={base_type.__name__}, "
            f"got {result.base_type} for metadata={metadata}"
        )

    @given(base_type=_cli_type)
    def test_bare_type_base_type_is_itself(self, base_type: type):
        """For a bare (non-Annotated) CLI type, base_type is the type itself.

        **Validates: Requirements 1.1, 1.3**
        """
        result = parse_annotation(base_type)

        assert result.base_type == base_type, (
            f"Expected base_type={base_type.__name__}, got {result.base_type}"
        )


# =============================================================================
# Property 2: DI Classification Stability
# =============================================================================


@pytest.mark.slow
class TestDIClassificationStability:
    """Property 2: DI Classification Stability.

    For any known DI type wrapped in Annotated with arbitrary metadata,
    the result always has `is_di_param=True`.

    **Validates: Requirements 1.5, 1.6**
    """

    @given(di_type=_di_type, metadata=_metadata_tuple)
    def test_di_type_always_classified_as_di_with_metadata(
        self, di_type: type, metadata: tuple[Any, ...]
    ):
        """DI types wrapped in Annotated with arbitrary metadata remain DI params.

        **Validates: Requirements 1.5, 1.6**
        """
        annotated = Annotated[
            tuple(  # type: ignore[misc]
                [di_type, *metadata]
            )
        ]
        result = parse_annotation(annotated)

        assert result.is_di_param is True, (
            f"Expected is_di_param=True for DI type {di_type.__name__} "
            f"with metadata={metadata}, got is_di_param={result.is_di_param}"
        )

    @given(di_type=_di_type)
    def test_bare_di_type_classified_as_di(self, di_type: type):
        """Bare DI types (no Annotated wrapper) are classified as DI params.

        **Validates: Requirements 1.5, 1.6**
        """
        result = parse_annotation(di_type)

        assert result.is_di_param is True, (
            f"Expected is_di_param=True for bare DI type {di_type.__name__}, "
            f"got is_di_param={result.is_di_param}"
        )

    @given(base_type=_cli_type, metadata=_metadata_tuple)
    def test_provide_marker_forces_di_classification(
        self, base_type: type, metadata: tuple[Any, ...]
    ):
        """Any type with a Provide marker in metadata is classified as DI.

        **Validates: Requirements 1.5, 1.6**
        """
        provide = Provide("test-qualifier")
        # Insert Provide marker at a random position in metadata
        full_metadata = (provide, *metadata)
        annotated = Annotated[
            tuple(  # type: ignore[misc]
                [base_type, *full_metadata]
            )
        ]
        result = parse_annotation(annotated)

        assert result.is_di_param is True, (
            f"Expected is_di_param=True for {base_type.__name__} with Provide marker, "
            f"got is_di_param={result.is_di_param}"
        )


# =============================================================================
# Property 3: DI/CLI Mutual Exclusion
# =============================================================================


@pytest.mark.slow
class TestDICLIMutualExclusion:
    """Property 3: DI/CLI Mutual Exclusion.

    For any annotation, `is_di_param` and `is_cli_compatible` are never
    both True simultaneously.

    Note: BaseModel subclasses have both False — that's valid.
    The invariant is "never BOTH True" (mutual exclusion), not "exactly one is True".

    **Validates: Requirements 1.1, 1.5, 1.6**
    """

    @given(base_type=_cli_type, metadata=_metadata_tuple)
    def test_cli_types_never_both_di_and_cli(
        self, base_type: type, metadata: tuple[Any, ...]
    ):
        """CLI-compatible types with arbitrary metadata are never both DI and CLI.

        **Validates: Requirements 1.1, 1.5, 1.6**
        """
        annotated = Annotated[
            tuple(  # type: ignore[misc]
                [base_type, *metadata]
            )
        ]
        result = parse_annotation(annotated)

        assert not (result.is_di_param and result.is_cli_compatible), (
            f"Mutual exclusion violated: is_di_param={result.is_di_param}, "
            f"is_cli_compatible={result.is_cli_compatible} "
            f"for {base_type.__name__} with metadata={metadata}"
        )

    @given(di_type=_di_type, metadata=_metadata_tuple)
    def test_di_types_never_both_di_and_cli(
        self, di_type: type, metadata: tuple[Any, ...]
    ):
        """DI types with arbitrary metadata are never both DI and CLI.

        **Validates: Requirements 1.1, 1.5, 1.6**
        """
        annotated = Annotated[
            tuple(  # type: ignore[misc]
                [di_type, *metadata]
            )
        ]
        result = parse_annotation(annotated)

        assert not (result.is_di_param and result.is_cli_compatible), (
            f"Mutual exclusion violated: is_di_param={result.is_di_param}, "
            f"is_cli_compatible={result.is_cli_compatible} "
            f"for DI type {di_type.__name__} with metadata={metadata}"
        )

    @given(
        base_type=st.one_of(_cli_type, _di_type),
        metadata=_metadata_tuple,
    )
    def test_provide_marker_never_both_di_and_cli(
        self, base_type: type, metadata: tuple[Any, ...]
    ):
        """Types with Provide markers are never both DI and CLI.

        **Validates: Requirements 1.1, 1.5, 1.6**
        """
        provide = Provide("qualifier")
        full_metadata = (provide, *metadata)
        annotated = Annotated[
            tuple(  # type: ignore[misc]
                [base_type, *full_metadata]
            )
        ]
        result = parse_annotation(annotated)

        assert not (result.is_di_param and result.is_cli_compatible), (
            f"Mutual exclusion violated: is_di_param={result.is_di_param}, "
            f"is_cli_compatible={result.is_cli_compatible} "
            f"for {base_type.__name__} with Provide marker"
        )

    @given(base_type=st.one_of(_cli_type, _di_type))
    def test_bare_types_never_both_di_and_cli(self, base_type: type):
        """Bare types (no Annotated wrapper) are never both DI and CLI.

        **Validates: Requirements 1.1, 1.5, 1.6**
        """
        result = parse_annotation(base_type)

        assert not (result.is_di_param and result.is_cli_compatible), (
            f"Mutual exclusion violated: is_di_param={result.is_di_param}, "
            f"is_cli_compatible={result.is_cli_compatible} "
            f"for bare type {base_type.__name__}"
        )
