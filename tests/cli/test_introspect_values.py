"""Property-based tests for InProcessIntrospector value completions.

# Feature: tui-foundation, Properties 9-11: Value completion invariants

Tests validate the correctness properties of get_value_completions_async:
choices inclusion, history recency ordering, and fuzzy filter invariants.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._cli.data.argument_history import ArgumentHistory
from functualize._cli.introspect import InProcessIntrospector
from functualize._types import FieldDescriptor, JobDescriptor

# =============================================================================
# Strategies
# =============================================================================

# Identifiers for job/field names: alphanumeric + hyphens/underscores, non-empty
_identifier = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Pd")),
    min_size=1,
    max_size=20,
)

# Choice values: printable non-empty strings
_choice_value = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=30,
)

# Non-empty list of choices (for Property 9)
_choices_list = st.lists(_choice_value, min_size=1, max_size=10, unique=True)

# History values: distinct printable non-empty strings
_history_value = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=20,
)

# Ordered list of history values (for Property 10) — we want distinct values
# to avoid consecutive duplicate collapsing complexity
_history_values = st.lists(_history_value, min_size=1, max_size=15, unique=True)

# Partial strings for fuzzy filtering (non-empty for Property 11)
_partial_str = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=10,
)


# =============================================================================
# Helpers
# =============================================================================


def _make_job_with_choices(
    job_name: str, field_name: str, choices: list[str]
) -> JobDescriptor:
    """Create a JobDescriptor with a field that has choices."""
    field = FieldDescriptor(
        name=field_name,
        type_annotation="str",
        default=None,
        description="Test field with choices",
        required=False,
        choices=choices,
    )
    return JobDescriptor(
        name=job_name,
        group=None,
        function=lambda: None,
        docstring="Test job",
        parameters=[field],
        source="<test>",
        metadata={},
    )


def _make_job_with_str_field(job_name: str, field_name: str) -> JobDescriptor:
    """Create a JobDescriptor with a plain string field (no choices)."""
    field = FieldDescriptor(
        name=field_name,
        type_annotation="str",
        default=None,
        description="Test string field",
        required=False,
        choices=None,
    )
    return JobDescriptor(
        name=job_name,
        group=None,
        function=lambda: None,
        docstring="Test job",
        parameters=[field],
        source="<test>",
        metadata={},
    )


def _make_app(jobs: list[JobDescriptor]) -> MagicMock:
    """Create a mock FunctualizeApp with get_jobs()."""
    app = MagicMock()
    app.get_jobs.return_value = jobs
    app.name = "test-app"
    return app


def _fuzzy_matches(partial: str, value: str) -> bool:
    """Check if value fuzzy-matches partial (case-insensitive substring or prefix)."""
    partial_lower = partial.lower()
    return partial_lower in value.lower() or value.lower().startswith(partial_lower)


# =============================================================================
# Property 9: Completions include all field choices
# =============================================================================


@pytest.mark.slow
class TestCompletionsIncludeAllFieldChoices:
    """Property 9: Completions include all field choices.

    For any FieldDescriptor with non-empty choices list, calling
    get_value_completions_async with an empty partial SHALL return completions
    containing every value in choices.

    **Validates: Requirements 4.1**
    """

    @given(
        job_name=_identifier,
        field_name=_identifier,
        choices=_choices_list,
    )
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_all_choices_appear_in_completions(
        self, job_name: str, field_name: str, choices: list[str]
    ):
        """Every value in FieldDescriptor.choices appears in completions
        when partial is empty.

        **Validates: Requirements 4.1**
        """
        job = _make_job_with_choices(job_name, field_name, choices)
        app = _make_app([job])
        introspector = InProcessIntrospector(app)

        completions = await introspector.get_value_completions_async(
            job_name, field_name, partial=""
        )

        completion_values = [c.value for c in completions]
        for choice in choices:
            assert choice in completion_values, (
                f"Choice {choice!r} not found in completions. Got: {completion_values}"
            )

    @given(
        job_name=_identifier,
        field_name=_identifier,
        choices=_choices_list,
    )
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_choices_completions_have_correct_source(
        self, job_name: str, field_name: str, choices: list[str]
    ):
        """All choice-sourced completions have source='choices'.

        **Validates: Requirements 4.1**
        """
        job = _make_job_with_choices(job_name, field_name, choices)
        app = _make_app([job])
        introspector = InProcessIntrospector(app)

        completions = await introspector.get_value_completions_async(
            job_name, field_name, partial=""
        )

        choices_completions = [c for c in completions if c.source == "choices"]
        choices_values = [c.value for c in choices_completions]
        for choice in choices:
            assert choice in choices_values, (
                f"Choice {choice!r} not in choices-sourced completions. "
                f"Got: {choices_values}"
            )


# =============================================================================
# Property 10: History completions appear in recency order
# =============================================================================


@pytest.mark.slow
class TestHistoryCompletionsRecencyOrder:
    """Property 10: History completions appear in recency order.

    For any job-field pair with N history entries, calling
    get_value_completions_async with an empty partial SHALL include those
    history values, and the history-sourced completions SHALL appear in
    reverse chronological order.

    **Validates: Requirements 4.2**
    """

    @given(
        job_name=_identifier,
        field_name=_identifier,
        values=_history_values,
    )
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_history_values_included_in_completions(
        self, job_name: str, field_name: str, values: list[str]
    ):
        """All history values appear in completions when partial is empty.

        **Validates: Requirements 4.2**
        """
        # Build history by recording values in order
        history = ArgumentHistory(_max_entries=50)
        for v in values:
            history.record(job_name, field_name, v)

        job = _make_job_with_str_field(job_name, field_name)
        app = _make_app([job])
        introspector = InProcessIntrospector(app, history=history)

        completions = await introspector.get_value_completions_async(
            job_name, field_name, partial=""
        )

        history_completions = [c for c in completions if c.source == "history"]
        history_completion_values = [c.value for c in history_completions]

        for v in values:
            assert v in history_completion_values, (
                f"History value {v!r} not found in completions. "
                f"Got: {history_completion_values}"
            )

    @given(
        job_name=_identifier,
        field_name=_identifier,
        values=_history_values,
    )
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_history_completions_in_reverse_chronological_order(
        self, job_name: str, field_name: str, values: list[str]
    ):
        """History-sourced completions appear in reverse chronological order.

        **Validates: Requirements 4.2**
        """
        # Build history by recording values in order
        history = ArgumentHistory(_max_entries=50)
        for v in values:
            history.record(job_name, field_name, v)

        job = _make_job_with_str_field(job_name, field_name)
        app = _make_app([job])
        introspector = InProcessIntrospector(app, history=history)

        completions = await introspector.get_value_completions_async(
            job_name, field_name, partial=""
        )

        history_completions = [c for c in completions if c.source == "history"]
        history_completion_values = [c.value for c in history_completions]

        # Expected: reverse chronological = most recent first
        expected_order = list(reversed(values))
        assert history_completion_values == expected_order, (
            f"History completions not in reverse chronological order. "
            f"Expected: {expected_order}, Got: {history_completion_values}"
        )


# =============================================================================
# Property 11: Fuzzy filter invariant
# =============================================================================


@pytest.mark.slow
class TestFuzzyFilterInvariant:
    """Property 11: Fuzzy filter invariant.

    For any non-empty partial string and set of candidate completions, all
    returned ValueCompletion items SHALL have a value that fuzzy-matches
    the partial (case-insensitive substring or prefix match).

    **Validates: Requirements 4.6**
    """

    @given(
        job_name=_identifier,
        field_name=_identifier,
        choices=_choices_list,
        partial=_partial_str,
    )
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_all_returned_completions_match_partial(
        self, job_name: str, field_name: str, choices: list[str], partial: str
    ):
        """Every returned completion fuzzy-matches the partial string.

        **Validates: Requirements 4.6**
        """
        job = _make_job_with_choices(job_name, field_name, choices)
        app = _make_app([job])
        introspector = InProcessIntrospector(app)

        completions = await introspector.get_value_completions_async(
            job_name, field_name, partial=partial
        )

        for c in completions:
            assert _fuzzy_matches(partial, c.value), (
                f"Completion {c.value!r} does not fuzzy-match "
                f"partial {partial!r}. Expected case-insensitive "
                f"substring or prefix match."
            )

    @given(
        job_name=_identifier,
        field_name=_identifier,
        choices=_choices_list,
        history_vals=_history_values,
        partial=_partial_str,
    )
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_fuzzy_filter_with_mixed_sources(
        self,
        job_name: str,
        field_name: str,
        choices: list[str],
        history_vals: list[str],
        partial: str,
    ):
        """Fuzzy filter applies uniformly across choices and history sources.

        **Validates: Requirements 4.6**
        """
        # Set up both choices and history
        history = ArgumentHistory(_max_entries=50)
        for v in history_vals:
            history.record(job_name, field_name, v)

        job = _make_job_with_choices(job_name, field_name, choices)
        app = _make_app([job])
        introspector = InProcessIntrospector(app, history=history)

        completions = await introspector.get_value_completions_async(
            job_name, field_name, partial=partial
        )

        for c in completions:
            assert _fuzzy_matches(partial, c.value), (
                f"Completion {c.value!r} (source={c.source!r}) does not "
                f"fuzzy-match partial {partial!r}."
            )
