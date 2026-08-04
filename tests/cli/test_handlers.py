"""Unit tests for CLI handler functions in _cli/main.py.

Tests cover:
- _handle_unknown error output and fuzzy suggestions (task 6.5)
- _fuzzy_suggest algorithm correctness (task 6.5)
- _handle_bare TTY vs non-TTY branching (task 6.6)
- Non-TTY: parseable job list output (one per line)
- Non-TTY with no jobs: "No jobs discovered." output
- Property 11: Job List Output Format (task 10.3)

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 6.1, 6.2, 6.3, 6.4
"""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._cli.main import _fuzzy_suggest, _handle_unknown
from functualize._types.descriptors import JobDescriptor

# Patch targets for _handle_bare — uses local imports from these modules
_PATCH_RESOLVE = "functualize._cli.config.resolve_cli_config"
_PATCH_APP = "functualize.app.FunctualizeApp"
_PATCH_DISCOVER = "functualize.app.utils.auto_discover"
_PATCH_TUI = "functualize._cli.inline_tui.launch_inline_tui"


def _make_job(name: str, docstring: str | None = None) -> JobDescriptor:
    """Create a minimal JobDescriptor for testing."""
    return JobDescriptor(name=name, group=None, docstring=docstring)


def _make_cli_flags() -> dict[str, Any]:
    """Return minimal cli_flags dict."""
    return {}


def _make_effective() -> dict[str, list[str]]:
    """Return minimal effective directories dict."""
    return {"jobs_directories": [], "import_libs": []}


def _mock_cli_config() -> MagicMock:
    """Create a mock resolve_cli_config return value."""
    mock = MagicMock()
    mock.scan_depth = 0
    mock.discovery = MagicMock()
    mock.dotenv = False
    mock.dotenv_path = None
    return mock


# =============================================================================
# Task 6.5: _fuzzy_suggest tests
# =============================================================================


class TestFuzzySuggest:
    """Tests for _fuzzy_suggest() suggestion algorithm."""

    def test_typo_suggests_close_match(self) -> None:
        """deply is Levenshtein <= 2 from deploy -> suggested."""
        result = _fuzzy_suggest("deply", {"deploy", "migrate", "test"})
        assert result == ["deploy"]

    def test_prefix_match_scores_highest(self) -> None:
        """Prefix matches score higher than substring or Levenshtein."""
        result = _fuzzy_suggest("dep", {"deploy", "undeploy", "test"})
        # deploy is prefix match (score=3), undeploy contains dep (score=2)
        assert result[0] == "deploy"

    def test_empty_job_names_returns_empty(self) -> None:
        """No job names -> no suggestions."""
        result = _fuzzy_suggest("deploy", set())
        assert result == []

    def test_no_close_match_returns_empty(self) -> None:
        """Command far from all job names -> empty list."""
        result = _fuzzy_suggest("zzzzzzz", {"deploy", "migrate", "test"})
        assert result == []

    def test_max_results_caps_output(self) -> None:
        """Never returns more than max_results suggestions."""
        jobs = {f"d{i}" for i in range(20)}
        result = _fuzzy_suggest("d", jobs, max_results=5)
        assert len(result) <= 5

    def test_substring_match(self) -> None:
        """Command contained within job name -> suggested."""
        result = _fuzzy_suggest("ploy", {"deploy", "migrate", "test"})
        assert "deploy" in result


# =============================================================================
# Task 6.5: _handle_unknown tests
# =============================================================================


class TestHandleUnknown:
    """Tests for _handle_unknown() error output."""

    def test_unknown_command_output_contains_command_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Output to stderr includes the unknown command name."""
        stderr_capture = StringIO()
        monkeypatch.setattr(sys, "stderr", stderr_capture)

        _handle_unknown(["deplyo"], {"deploy", "migrate"})

        output = stderr_capture.getvalue()
        assert "deplyo" in output

    def test_unknown_command_suggests_close_match(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When fuzzy matches exist, suggestions are printed."""
        stderr_capture = StringIO()
        monkeypatch.setattr(sys, "stderr", stderr_capture)

        _handle_unknown(["deplyo"], {"deploy", "migrate"})

        output = stderr_capture.getvalue()
        assert "deploy" in output
        assert "Did you mean" in output

    def test_empty_job_names_still_prints_guidance(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With no job names, still prints guidance to run func."""
        stderr_capture = StringIO()
        monkeypatch.setattr(sys, "stderr", stderr_capture)

        _handle_unknown(["unknown_cmd"], set())

        output = stderr_capture.getvalue()
        assert "unknown_cmd" in output
        assert "Run 'func' to see all available commands." in output
        # No suggestions when job_names is empty
        assert "Did you mean" not in output

    def test_returns_none(self) -> None:
        """_handle_unknown returns None - caller handles exit code."""
        result = _handle_unknown(["deplyo"], {"deploy", "migrate"})
        assert result is None

    def test_always_prints_func_guidance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Every unknown command response directs user to run func."""
        stderr_capture = StringIO()
        monkeypatch.setattr(sys, "stderr", stderr_capture)

        _handle_unknown(["deplyo"], {"deploy", "migrate"})

        output = stderr_capture.getvalue()
        assert "Run 'func' to see all available commands." in output


# =============================================================================
# Task 6.6: _handle_bare non-TTY tests
# =============================================================================


class TestHandleBareNonTTY:
    """Test _handle_bare when no TTY is attached (piped/scripted)."""

    def test_non_tty_prints_job_list_one_per_line(self, tmp_path: Path) -> None:
        """WHEN non-TTY, _handle_bare SHALL print one job per line.

        Requirements: 6.2, 6.3
        """
        jobs = [
            _make_job("deploy", "Deploy the application to production"),
            _make_job("migrate", "Run database migrations"),
            _make_job("test", "Execute test suite"),
        ]

        mock_app = MagicMock()
        mock_app.get_jobs.return_value = jobs

        with (
            patch("sys.stdin.isatty", return_value=False),
            patch("sys.stdout.isatty", return_value=False),
            patch(_PATCH_RESOLVE, return_value=_mock_cli_config()),
            patch(_PATCH_DISCOVER, return_value=MagicMock()),
            patch(_PATCH_APP, return_value=mock_app),
            patch("click.echo") as mock_echo,
        ):
            from functualize._cli.main import _handle_bare

            _handle_bare(tmp_path, {}, _make_effective(), _make_cli_flags())

            # Should have 3 calls (one per job, sorted)
            assert mock_echo.call_count == 3

            # Check that job names appear in the output (sorted order)
            call_args = [mock_echo.call_args_list[i][0][0] for i in range(3)]
            assert "deploy" in call_args[0]
            assert "migrate" in call_args[1]
            assert "test" in call_args[2]

    def test_non_tty_job_format_includes_dash_and_docstring(
        self, tmp_path: Path
    ) -> None:
        """WHEN printing job list, each line SHALL have name \u2014 docstring format.

        Requirements: 6.3
        """
        jobs = [
            _make_job("deploy", "Deploy to production"),
        ]

        mock_app = MagicMock()
        mock_app.get_jobs.return_value = jobs

        with (
            patch("sys.stdin.isatty", return_value=False),
            patch("sys.stdout.isatty", return_value=False),
            patch(_PATCH_RESOLVE, return_value=_mock_cli_config()),
            patch(_PATCH_DISCOVER, return_value=MagicMock()),
            patch(_PATCH_APP, return_value=mock_app),
            patch("click.echo") as mock_echo,
        ):
            from functualize._cli.main import _handle_bare

            _handle_bare(tmp_path, {}, _make_effective(), _make_cli_flags())

            # Verify the format is "name \u2014 description"
            mock_echo.assert_called_once_with("deploy \u2014 Deploy to production")

    def test_non_tty_job_without_docstring_prints_name_only(
        self, tmp_path: Path
    ) -> None:
        """WHEN a job has no docstring, only the name is printed.

        Requirements: 6.3
        """
        jobs = [
            _make_job("cleanup", None),
        ]

        mock_app = MagicMock()
        mock_app.get_jobs.return_value = jobs

        with (
            patch("sys.stdin.isatty", return_value=False),
            patch("sys.stdout.isatty", return_value=False),
            patch(_PATCH_RESOLVE, return_value=_mock_cli_config()),
            patch(_PATCH_DISCOVER, return_value=MagicMock()),
            patch(_PATCH_APP, return_value=mock_app),
            patch("click.echo") as mock_echo,
        ):
            from functualize._cli.main import _handle_bare

            _handle_bare(tmp_path, {}, _make_effective(), _make_cli_flags())

            mock_echo.assert_called_once_with("cleanup")

    def test_non_tty_no_jobs_prints_no_jobs_discovered(self, tmp_path: Path) -> None:
        """WHEN no jobs are discovered, SHALL print 'No jobs discovered.' and return.

        Requirements: 6.4
        """
        mock_app = MagicMock()
        mock_app.get_jobs.return_value = []

        with (
            patch("sys.stdin.isatty", return_value=False),
            patch("sys.stdout.isatty", return_value=False),
            patch(_PATCH_RESOLVE, return_value=_mock_cli_config()),
            patch(_PATCH_DISCOVER, return_value=MagicMock()),
            patch(_PATCH_APP, return_value=mock_app),
            patch("click.echo") as mock_echo,
        ):
            from functualize._cli.main import _handle_bare

            _handle_bare(tmp_path, {}, _make_effective(), _make_cli_flags())

            mock_echo.assert_called_once_with("No jobs discovered.")

    def test_non_tty_does_not_launch_tui(self, tmp_path: Path) -> None:
        """WHEN non-TTY, _handle_bare SHALL NOT launch the TUI.

        Requirements: 6.1, 6.2
        """
        jobs = [_make_job("deploy", "Deploy app")]
        mock_app = MagicMock()
        mock_app.get_jobs.return_value = jobs

        with (
            patch("sys.stdin.isatty", return_value=False),
            patch("sys.stdout.isatty", return_value=False),
            patch(_PATCH_RESOLVE, return_value=_mock_cli_config()),
            patch(_PATCH_DISCOVER, return_value=MagicMock()),
            patch(_PATCH_APP, return_value=mock_app),
            patch("click.echo"),
            patch(_PATCH_TUI) as mock_tui,
        ):
            from functualize._cli.main import _handle_bare

            _handle_bare(tmp_path, {}, _make_effective(), _make_cli_flags())

            mock_tui.assert_not_called()


# =============================================================================
# Task 6.6: _handle_bare TTY tests
# =============================================================================


class TestHandleBareTTY:
    """Test _handle_bare when TTY is attached (interactive terminal)."""

    def test_tty_launches_tui(self, tmp_path: Path) -> None:
        """WHEN TTY is attached to both stdin and stdout, SHALL launch TUI.

        Requirements: 6.1
        """
        mock_app = MagicMock()

        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("sys.stdout.isatty", return_value=True),
            patch(_PATCH_RESOLVE, return_value=_mock_cli_config()),
            patch(_PATCH_DISCOVER, return_value=MagicMock()),
            patch(_PATCH_APP, return_value=mock_app),
            patch(_PATCH_TUI) as mock_tui,
        ):
            from functualize._cli.main import _handle_bare

            with pytest.raises(SystemExit):
                _handle_bare(tmp_path, {}, _make_effective(), _make_cli_flags())

            mock_tui.assert_called_once_with(mock_app)


# =============================================================================
# Task 10.3: Property 11 - Job List Output Format
# =============================================================================

# Strategies for generating job data
_job_name_chars = st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789_")
_job_name_st = st.text(_job_name_chars, min_size=1, max_size=20)
_docstring_st = st.one_of(
    st.none(),
    st.text(
        st.characters(blacklist_categories=("Cs",), blacklist_characters="\n\r"),
        min_size=1,
        max_size=60,
    ),
)

# A list of (name, docstring) tuples representing jobs
_job_list_st = st.lists(
    st.tuples(_job_name_st, _docstring_st),
    min_size=1,
    max_size=20,
    unique_by=lambda x: x[0],  # unique job names
)


@pytest.mark.slow
class TestJobListOutputFormatProperty:
    """Property 11: Job List Output Format.

    For any set of discovered jobs with names and docstrings, the non-TTY
    bare invocation output SHALL contain exactly one line per job, and each
    line SHALL include the job name.

    **Validates: Requirements 6.2, 6.3**
    """

    @given(job_data=_job_list_st)
    @settings(max_examples=200)
    def test_output_has_one_line_per_job(
        self, job_data: list[tuple[str, str | None]]
    ) -> None:
        """Non-TTY bare invocation output has exactly one line per job.

        **Validates: Requirements 6.2, 6.3**
        """
        jobs = [_make_job(name, doc) for name, doc in job_data]

        mock_app = MagicMock()
        mock_app.get_jobs.return_value = jobs

        echo_calls: list[str] = []

        def capture_echo(msg: str) -> None:
            echo_calls.append(msg)

        anchor = Path("/tmp/fake-anchor")

        with (
            patch("sys.stdin.isatty", return_value=False),
            patch("sys.stdout.isatty", return_value=False),
            patch(_PATCH_RESOLVE, return_value=_mock_cli_config()),
            patch(_PATCH_DISCOVER, return_value=MagicMock()),
            patch(_PATCH_APP, return_value=mock_app),
            patch("click.echo", side_effect=capture_echo),
        ):
            from functualize._cli.main import _handle_bare

            _handle_bare(anchor, {}, _make_effective(), _make_cli_flags())

        # Exactly one line per job
        assert len(echo_calls) == len(jobs), (
            f"Expected {len(jobs)} output lines, got {len(echo_calls)}. "
            f"Jobs: {[j.name for j in jobs]}, Output: {echo_calls}"
        )

    @given(job_data=_job_list_st)
    @settings(max_examples=200)
    def test_each_line_contains_job_name(
        self, job_data: list[tuple[str, str | None]]
    ) -> None:
        """Each output line contains the corresponding job name.

        **Validates: Requirements 6.2, 6.3**
        """
        jobs = [_make_job(name, doc) for name, doc in job_data]

        mock_app = MagicMock()
        mock_app.get_jobs.return_value = jobs

        echo_calls: list[str] = []

        def capture_echo(msg: str) -> None:
            echo_calls.append(msg)

        anchor = Path("/tmp/fake-anchor")

        with (
            patch("sys.stdin.isatty", return_value=False),
            patch("sys.stdout.isatty", return_value=False),
            patch(_PATCH_RESOLVE, return_value=_mock_cli_config()),
            patch(_PATCH_DISCOVER, return_value=MagicMock()),
            patch(_PATCH_APP, return_value=mock_app),
            patch("click.echo", side_effect=capture_echo),
        ):
            from functualize._cli.main import _handle_bare

            _handle_bare(anchor, {}, _make_effective(), _make_cli_flags())

        # Jobs are output sorted by name
        sorted_jobs = sorted(jobs, key=lambda j: j.name)

        for i, job in enumerate(sorted_jobs):
            assert job.name in echo_calls[i], (
                f"Expected job name '{job.name}' in output line {i}: '{echo_calls[i]}'"
            )
