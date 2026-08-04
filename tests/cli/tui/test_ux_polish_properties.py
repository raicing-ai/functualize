# Feature: tui-v3-ux-polish, Property 4: Readiness re-evaluation after completion
"""Property-based tests for readiness re-evaluation after completion.

Tests SmartBar.evaluate() from functualize._cli.tui.bar:
- Property 4: For any completion insertion that changes SmartBar value,
  the readiness state equals what evaluate() would return for the tokenized
  new content.

**Validates: Requirements 4.1, 4.2**
"""

from __future__ import annotations

import string

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._cli.tui.bar import BarReadiness, SmartBar

# =============================================================================
# Strategies
# =============================================================================

# Job name identifiers: lowercase alpha, reasonable length
_job_name = st.text(
    alphabet=string.ascii_lowercase,
    min_size=1,
    max_size=10,
)

# Field names: lowercase alpha, reasonable length
_field_name = st.text(
    alphabet=string.ascii_lowercase,
    min_size=1,
    max_size=8,
)

# Field values: alphanumeric, non-empty
_field_value = st.text(
    alphabet=string.ascii_lowercase + string.digits,
    min_size=1,
    max_size=12,
)


@st.composite
def job_with_fields(draw: st.DrawFn) -> tuple[str, list[str], list[str]]:
    """Generate a job name, its required fields, and a subset of provided fields.

    Returns:
        Tuple of (job_name, required_fields, provided_fields).
    """
    job_name = draw(_job_name)
    required_fields = draw(st.lists(_field_name, min_size=0, max_size=5, unique=True))
    # Pick a subset of required_fields to provide (could be all, some, or none)
    if required_fields:
        provided_fields = draw(
            st.lists(
                st.sampled_from(required_fields),
                min_size=0,
                max_size=len(required_fields),
                unique=True,
            )
        )
    else:
        provided_fields = []
    return job_name, required_fields, provided_fields


@st.composite
def smartbar_content_after_completion(
    draw: st.DrawFn,
) -> tuple[str, str, list[str], list[str]]:
    """Generate SmartBar content as it would appear after a completion insertion.

    Simulates the content produced by apply_completion(): a recognized job name
    followed by --flag value pairs, with a trailing space (as per Requirement 3.1).

    Returns:
        Tuple of (content_string, job_name, required_fields, provided_fields).
    """
    job_name, required_fields, provided_fields = draw(job_with_fields())

    # Build the content string as if apply_completion inserted it
    parts = [job_name]
    for field in provided_fields:
        value = draw(_field_value)
        parts.append(f"--{field}")
        parts.append(value)

    # apply_completion appends a trailing space
    content = " ".join(parts) + " "
    return content, job_name, required_fields, provided_fields


# =============================================================================
# Property 4: Readiness re-evaluation after completion
# =============================================================================


@pytest.mark.slow
class TestReadinessReEvaluationAfterCompletion:
    """Property 4: Readiness re-evaluation after completion.

    For any completion insertion that changes SmartBar value, verify the
    readiness state equals what evaluate() would return for the tokenized
    new content.

    The test verifies that:
    1. Tokenizing the SmartBar content after completion
    2. Calling evaluate() with those tokens, the job registry, and field resolver
    3. Produces a readiness state consistent with the job's field requirements

    **Validates: Requirements 4.1, 4.2**
    """

    @given(data=smartbar_content_after_completion())
    @settings(max_examples=200)
    def test_evaluate_matches_expected_readiness_for_known_job(
        self,
        data: tuple[str, str, list[str], list[str]],
    ) -> None:
        """After completion of a known job, evaluate() returns correct readiness."""
        content, job_name, required_fields, provided_fields = data

        bar = SmartBar(id="test")
        job_names = [job_name]

        def get_required_fields(name: str) -> list[str]:
            if name == job_name:
                return required_fields
            return []

        # Tokenize the content (same logic as on_input_changed)
        tokens = content.split()

        # Call evaluate — this is what on_input_changed does after
        # apply_completion sets the value
        result = bar.evaluate(tokens, job_names, get_required_fields)

        # Determine expected readiness based on field requirements
        missing = [f for f in required_fields if f not in provided_fields]
        expected = BarReadiness.PENDING if missing else BarReadiness.READY

        assert result is expected, (
            f"Content: '{content}'\n"
            f"Tokens: {tokens}\n"
            f"Job: {job_name}, Required: {required_fields}, "
            f"Provided: {provided_fields}\n"
            f"Missing: {missing}\n"
            f"Expected: {expected}, Got: {result}"
        )

    @given(data=smartbar_content_after_completion())
    @settings(max_examples=200)
    def test_evaluate_readiness_matches_bar_state(
        self,
        data: tuple[str, str, list[str], list[str]],
    ) -> None:
        """After evaluate(), bar.readiness matches the returned value."""
        content, job_name, required_fields, provided_fields = data

        bar = SmartBar(id="test")
        job_names = [job_name]

        def get_required_fields(name: str) -> list[str]:
            if name == job_name:
                return required_fields
            return []

        tokens = content.split()
        result = bar.evaluate(tokens, job_names, get_required_fields)

        # The bar's internal state must match the returned value
        assert bar.readiness is result, (
            f"bar.readiness ({bar.readiness}) != evaluate() return ({result})"
        )

    @given(content_prefix=_job_name)
    @settings(max_examples=100)
    def test_evaluate_unknown_job_returns_grey(
        self,
        content_prefix: str,
    ) -> None:
        """If the completed job name is not in the registry, evaluate returns GREY."""
        bar = SmartBar(id="test")
        # Use a different job name in the registry so content_prefix is unknown
        other_job = content_prefix + "x"
        job_names = [other_job]

        def get_required_fields(name: str) -> list[str]:
            return []

        # Simulate content after completion: unknown job + trailing space
        content = content_prefix + " "
        tokens = content.split()

        result = bar.evaluate(tokens, job_names, get_required_fields)

        assert result is BarReadiness.GREY, (
            f"Expected GREY for unknown job '{content_prefix}', got {result}"
        )

    @given(data=smartbar_content_after_completion())
    @settings(max_examples=200)
    def test_evaluate_is_idempotent_after_completion(
        self,
        data: tuple[str, str, list[str], list[str]],
    ) -> None:
        """Calling evaluate() twice with same content produces same result.

        This validates Requirement 4.2: the same tokenization and evaluation
        logic is used consistently.
        """
        content, job_name, required_fields, provided_fields = data

        bar = SmartBar(id="test")
        job_names = [job_name]

        def get_required_fields(name: str) -> list[str]:
            if name == job_name:
                return required_fields
            return []

        tokens = content.split()

        result1 = bar.evaluate(tokens, job_names, get_required_fields)
        result2 = bar.evaluate(tokens, job_names, get_required_fields)

        assert result1 is result2, (
            f"evaluate() not idempotent: first={result1}, second={result2}"
        )
