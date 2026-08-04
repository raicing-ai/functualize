"""Property-based tests for CompletionProvenance classifier.

# Feature: tui-foundation, Properties 7-8: CompletionProvenance invariants

Tests validate the core correctness properties of the CompletionProvenanceClassifier:
total classification (every job gets exactly one type) and the recent flag matching
history presence.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._cli.completions.provenance import (
    CompletionProvenanceClassifier,
    ProvenanceInfo,
)
from functualize._cli.data.argument_history import ArgumentHistory
from functualize.types import JobDescriptor

# =============================================================================
# Strategies
# =============================================================================

# Job names: non-empty alphanumeric + hyphens/dots (realistic job names)
_job_name_str = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-._"),
    min_size=1,
    max_size=30,
).filter(lambda s: s[0].isalpha())

# Group names: optional, non-empty when present
_group_str = st.one_of(
    st.none(),
    st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N"), whitelist_characters="-._"
        ),
        min_size=1,
        max_size=20,
    ).filter(lambda s: s[0].isalpha()),
)

# Source file paths: optional, realistic path-like strings
_source_file_str = st.one_of(
    st.just(""),
    st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N"), whitelist_characters="/-_."
        ),
        min_size=1,
        max_size=60,
    ).map(lambda s: f"/project/jobs/{s}.py"),
)

# Metadata: optional dict with various keys
_metadata_st = st.one_of(
    st.just({}),
    st.fixed_dictionaries(
        {},
        optional={
            "plugin_name": st.text(
                alphabet=st.characters(whitelist_categories=("L", "N")),
                min_size=1,
                max_size=15,
            ),
            "child_app": st.text(
                alphabet=st.characters(whitelist_categories=("L", "N")),
                min_size=1,
                max_size=15,
            ),
            "category": st.text(min_size=1, max_size=10),
        },
    ),
)

# Valid source types for classification
_VALID_SOURCE_TYPES = frozenset({"local", "plugin", "child", "builtin"})

# Field names for recording history
_field_name_str = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_"),
    min_size=1,
    max_size=20,
)

# Values for recording history
_value_str = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=30,
)


# =============================================================================
# Helpers
# =============================================================================


def _make_mock_app() -> MagicMock:
    """Create a minimal mock FunctualizeApp for the classifier.

    The mock has:
    - get_jobs() returning empty list
    - No plugin_loader attribute
    - Empty child_projects (no child classification)
    - No _jobs_directories attribute
    """
    app = MagicMock()
    app.get_jobs.return_value = []
    # Remove attributes that would trigger plugin/child classification
    del app.plugin_loader
    app.child_projects = []
    del app._jobs_directories
    return app


def _make_job_descriptor(
    name: str,
    group: str | None = None,
    source_file: str = "",
    metadata: dict[str, Any] | None = None,
) -> JobDescriptor:
    """Create a JobDescriptor with the given fields."""
    return JobDescriptor(
        name=name,
        group=group,
        source_file=source_file,
        metadata=metadata if metadata is not None else {},
    )


# =============================================================================
# Strategy for generating arbitrary JobDescriptors
# =============================================================================

_job_descriptor_st = st.builds(
    _make_job_descriptor,
    name=_job_name_str,
    group=_group_str,
    source_file=_source_file_str,
    metadata=_metadata_st,
)


# =============================================================================
# Property 7: Total classification (every job gets exactly one type)
# =============================================================================


@pytest.mark.slow
class TestTotalClassification:
    """Property 7: Total classification.

    For any valid JobDescriptor (with any combination of source_file, group,
    and metadata), the CompletionProvenanceClassifier SHALL classify it into
    exactly one of "local", "plugin", "child", or "builtin", and the
    classification SHALL be deterministic (same input always produces same
    output).

    **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
    """

    @given(job=_job_descriptor_st)
    @settings(max_examples=200)
    def test_classification_produces_valid_source_type(self, job: JobDescriptor):
        """Every job is classified into exactly one valid source_type.

        **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
        """
        app = _make_mock_app()
        classifier = CompletionProvenanceClassifier(app=app, history=None)

        result = classifier.get_provenance(job)

        assert isinstance(result, ProvenanceInfo), (
            f"Expected ProvenanceInfo, got {type(result).__name__}"
        )
        assert result.source_type in _VALID_SOURCE_TYPES, (
            f"Invalid source_type {result.source_type!r} for job {job.name!r}. "
            f"Must be one of {sorted(_VALID_SOURCE_TYPES)}"
        )

    @given(job=_job_descriptor_st)
    @settings(max_examples=200)
    def test_classification_is_deterministic(self, job: JobDescriptor):
        """Classifying the same job twice produces the same result.

        **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
        """
        app = _make_mock_app()
        classifier = CompletionProvenanceClassifier(app=app, history=None)

        result1 = classifier.get_provenance(job)
        result2 = classifier.get_provenance(job)

        assert result1 == result2, (
            f"Non-deterministic classification for job {job.name!r}: "
            f"first={result1.source_type}, second={result2.source_type}"
        )

    @given(job=_job_descriptor_st)
    @settings(max_examples=200)
    def test_classification_has_display_label_and_badge_style(self, job: JobDescriptor):
        """Every ProvenanceInfo has non-empty display_label and badge_style.

        **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
        """
        app = _make_mock_app()
        classifier = CompletionProvenanceClassifier(app=app, history=None)

        result = classifier.get_provenance(job)

        assert (
            isinstance(result.display_label, str) and len(result.display_label) > 0
        ), (
            f"display_label should be a non-empty string, "
            f"got {result.display_label!r} for job {job.name!r}"
        )
        assert isinstance(result.badge_style, str) and len(result.badge_style) > 0, (
            f"badge_style should be a non-empty string, "
            f"got {result.badge_style!r} for job {job.name!r}"
        )


# =============================================================================
# Property 8: Recent flag matches history presence
# =============================================================================


@pytest.mark.slow
class TestRecentFlagMatchesHistoryPresence:
    """Property 8: Recent flag matches history presence.

    For any job name, is_recent(job_name) SHALL return True if and only if
    the ArgumentHistory contains at least one recorded entry for that job.

    **Validates: Requirements 3.6**
    """

    @given(
        job_name=_job_name_str,
        field_name=_field_name_str,
        values=st.lists(_value_str, min_size=1, max_size=10),
    )
    @settings(max_examples=200)
    def test_is_recent_true_when_history_exists(
        self, job_name: str, field_name: str, values: list[str]
    ):
        """is_recent returns True when history has entries for the job.

        **Validates: Requirements 3.6**
        """
        app = _make_mock_app()
        history = ArgumentHistory(_max_entries=50)

        # Record some history for the job
        for v in values:
            history.record(job_name, field_name, v)

        classifier = CompletionProvenanceClassifier(app=app, history=history)

        assert classifier.is_recent(job_name) is True, (
            f"is_recent({job_name!r}) should be True after recording "
            f"{len(values)} values"
        )

    @given(
        job_name=_job_name_str,
        other_job_name=_job_name_str,
        field_name=_field_name_str,
        values=st.lists(_value_str, min_size=1, max_size=10),
    )
    @settings(max_examples=200)
    def test_is_recent_false_when_no_history(
        self,
        job_name: str,
        other_job_name: str,
        field_name: str,
        values: list[str],
    ):
        """is_recent returns False when history has no entries for the job.

        **Validates: Requirements 3.6**
        """
        # Ensure the job names are different
        from hypothesis import assume

        assume(job_name != other_job_name)

        app = _make_mock_app()
        history = ArgumentHistory(_max_entries=50)

        # Record history for a different job only
        for v in values:
            history.record(other_job_name, field_name, v)

        classifier = CompletionProvenanceClassifier(app=app, history=history)

        assert classifier.is_recent(job_name) is False, (
            f"is_recent({job_name!r}) should be False when only "
            f"{other_job_name!r} has history"
        )

    @given(job_name=_job_name_str)
    @settings(max_examples=200)
    def test_is_recent_false_with_empty_history(self, job_name: str):
        """is_recent returns False when history is empty.

        **Validates: Requirements 3.6**
        """
        app = _make_mock_app()
        history = ArgumentHistory(_max_entries=50)

        classifier = CompletionProvenanceClassifier(app=app, history=history)

        assert classifier.is_recent(job_name) is False, (
            f"is_recent({job_name!r}) should be False with empty history"
        )

    @given(job_name=_job_name_str)
    @settings(max_examples=200)
    def test_is_recent_false_without_history_instance(self, job_name: str):
        """is_recent returns False when no ArgumentHistory is provided.

        **Validates: Requirements 3.6**
        """
        app = _make_mock_app()
        classifier = CompletionProvenanceClassifier(app=app, history=None)

        assert classifier.is_recent(job_name) is False, (
            f"is_recent({job_name!r}) should be False when history is None"
        )

    @given(
        job_name=_job_name_str,
        field_name=_field_name_str,
        values=st.lists(_value_str, min_size=1, max_size=10),
    )
    @settings(max_examples=200)
    def test_is_recent_matches_has_history(
        self, job_name: str, field_name: str, values: list[str]
    ):
        """is_recent(job_name) matches history.has_history(job_name).

        **Validates: Requirements 3.6**
        """
        app = _make_mock_app()
        history = ArgumentHistory(_max_entries=50)

        # Record some history
        for v in values:
            history.record(job_name, field_name, v)

        classifier = CompletionProvenanceClassifier(app=app, history=history)

        assert classifier.is_recent(job_name) == history.has_history(job_name), (
            f"is_recent({job_name!r}) = {classifier.is_recent(job_name)} "
            f"but has_history = {history.has_history(job_name)}"
        )
