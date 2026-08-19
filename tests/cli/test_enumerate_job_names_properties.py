"""Property-based tests for enumerate_job_names.

# Feature: eliminate-fallback-group, Property 4: Enumeration Superset Guarantee
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize.app.utils import enumerate_job_names

# =============================================================================
# Strategies for Property 4
# =============================================================================

# Valid Python identifier characters for file stems (alphanumeric + underscores)
_stem_chars = st.sampled_from(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
)

# Non-underscore-prefixed stems: first character is NOT an underscore
_non_underscore_first_char = st.sampled_from(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
)

_valid_job_stem = st.builds(
    lambda first, rest: first + rest,
    _non_underscore_first_char,
    st.text(_stem_chars, min_size=0, max_size=20),
)

# Underscore-prefixed stems: always start with _
_underscore_stem = st.builds(
    lambda rest: "_" + rest,
    st.text(_stem_chars, min_size=1, max_size=20),
)

# Lists of valid job stems (at least 1 to ensure something is written)
_valid_stems_list = st.lists(_valid_job_stem, min_size=1, max_size=15)

# Lists of underscore-prefixed stems
_underscore_stems_list = st.lists(_underscore_stem, min_size=0, max_size=10)


# =============================================================================
# Property 4: Enumeration Superset Guarantee
# =============================================================================


@pytest.mark.slow
class TestEnumerationSupersetGuarantee:
    """Property 4: Enumeration Superset Guarantee.

    For any directory containing .py files that do not start with an underscore,
    enumerate_job_names SHALL include all such filename stems in its result set.
    The result is a superset of actual filename-derived job names — false
    positives are acceptable, false negatives are not.

    **Validates: Requirements 2.1, 2.2, 2.5**
    """

    @given(valid_stems=_valid_stems_list)
    def test_all_non_underscore_py_stems_appear_in_result(
        self, valid_stems: list[str]
    ) -> None:
        """Every .py file not starting with _ has its stem in the result.

        **Validates: Requirements 2.1, 2.2, 2.5**
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            jobs_dir = tmp_path / "jobs"
            jobs_dir.mkdir()

            for stem in valid_stems:
                (jobs_dir / f"{stem}.py").write_text("", encoding="utf-8")

            result = enumerate_job_names([str(jobs_dir)])

            # Every generated stem must appear in the result (superset guarantee)
            for stem in valid_stems:
                assert stem in result, (
                    f"Stem {stem!r} not found in result {result}. "
                    f"enumerate_job_names must never produce false negatives."
                )

    @given(underscore_stems=_underscore_stems_list)
    def test_underscore_prefixed_files_excluded(
        self, underscore_stems: list[str]
    ) -> None:
        """Files starting with _ are excluded from the result.

        **Validates: Requirements 2.1, 2.5**
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            jobs_dir = tmp_path / "jobs"
            jobs_dir.mkdir()

            for stem in underscore_stems:
                (jobs_dir / f"{stem}.py").write_text("", encoding="utf-8")

            result = enumerate_job_names([str(jobs_dir)])

            # No underscore-prefixed stem should appear in the result
            for stem in underscore_stems:
                assert stem not in result, (
                    f"Underscore-prefixed stem {stem!r} found in result {result}. "
                    f"Files starting with _ must be excluded."
                )

    @given(
        valid_stems=_valid_stems_list,
        underscore_stems=_underscore_stems_list,
    )
    def test_mixed_files_only_valid_stems_included(
        self,
        valid_stems: list[str],
        underscore_stems: list[str],
    ) -> None:
        """With a mix of valid and underscore files, only valid stems appear.

        **Validates: Requirements 2.1, 2.2, 2.5**
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            jobs_dir = tmp_path / "jobs"
            jobs_dir.mkdir()

            for stem in valid_stems:
                (jobs_dir / f"{stem}.py").write_text("", encoding="utf-8")
            for stem in underscore_stems:
                (jobs_dir / f"{stem}.py").write_text("", encoding="utf-8")

            result = enumerate_job_names([str(jobs_dir)])

            # All valid stems must be present (superset guarantee)
            for stem in valid_stems:
                assert stem in result, (
                    f"Valid stem {stem!r} missing from result. "
                    f"enumerate_job_names must not produce false negatives."
                )

            # No underscore stems should be present
            for stem in underscore_stems:
                assert stem not in result, (
                    f"Underscore stem {stem!r} unexpectedly in result."
                )

    @given(valid_stems=_valid_stems_list)
    def test_result_contains_only_stems_without_extension(
        self, valid_stems: list[str]
    ) -> None:
        """Result contains stems (no .py extension), matching requirement 2.2.

        **Validates: Requirements 2.2**
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            jobs_dir = tmp_path / "jobs"
            jobs_dir.mkdir()

            for stem in valid_stems:
                (jobs_dir / f"{stem}.py").write_text("", encoding="utf-8")

            result = enumerate_job_names([str(jobs_dir)])

            # No result should end with .py — they are stems, not filenames
            for name in result:
                assert not name.endswith(".py"), (
                    f"Result {name!r} ends with .py — enumerate_job_names "
                    f"should return stems without extension."
                )
