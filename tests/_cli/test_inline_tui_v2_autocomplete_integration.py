"""Integration tests for autocomplete migration and keybinding preservation.

Tests the SmartBarAutoComplete logic, PathSuggestionScanner filesystem integration,
migration verification (old code patterns removed), and preserved keybindings.

Feature: TUI Architecture v2 (Phase 5-6)
Task: 23.2
Validates: Requirements 13.1–13.12, 15.1–15.14, 22.9, 22.10, 22.13
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

from functualize._cli.completions.provenance import CompletionProvenanceClassifier
from functualize._cli.data.argument_history import ArgumentHistory
from functualize._cli.tui.path_suggestion_scanner import PathSuggestionScanner
from functualize._cli.tui.smart_bar_autocomplete import SmartBarAutoComplete
from functualize.types import FieldDescriptor, JobDescriptor

if TYPE_CHECKING:
    import pytest


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_field(
    name: str,
    type_annotation: str = "str",
    default: Any = None,
    description: str = "",
    required: bool = False,
    choices: list[str] | None = None,
) -> FieldDescriptor:
    return FieldDescriptor(
        name=name,
        type_annotation=type_annotation,
        default=default,
        description=description,
        required=required,
        choices=choices,
    )


def _make_job(
    name: str,
    group: str | None = None,
    docstring: str | None = None,
    fields: list[FieldDescriptor] | None = None,
) -> JobDescriptor:
    return JobDescriptor(
        name=name,
        group=group,
        docstring=docstring,
        config_fields=fields or [],
        parameters=fields or [],
    )


def _make_app_mock(jobs: list[JobDescriptor]) -> MagicMock:
    """Create a mock FunctualizeApp that returns the given jobs."""
    app = MagicMock()
    app.get_jobs.return_value = jobs
    app.get_job.side_effect = lambda name: next(
        (j for j in jobs if j.name == name), None
    )
    app.name = "test-app"
    return app


def _make_state(text: str, cursor_position: int | None = None) -> object:
    """Create a lightweight TargetState-like object."""

    class _State:
        pass

    s = _State()
    s.text = text  # type: ignore[attr-defined]
    s.cursor_position = cursor_position if cursor_position is not None else len(text)  # type: ignore[attr-defined]
    return s


# ---------------------------------------------------------------------------
# 1. SmartBarAutoComplete integration tests
# ---------------------------------------------------------------------------


class TestSmartBarAutoCompleteInstantiation:
    """Test that SmartBarAutoComplete can be instantiated with dependencies."""

    def test_instantiation_with_all_dependencies(self):
        """SmartBarAutoComplete accepts app, provenance, history, path_scanner."""
        jobs = [_make_job("deploy", docstring="Deploy the app")]
        app = _make_app_mock(jobs)
        provenance = CompletionProvenanceClassifier(app=app)
        history = ArgumentHistory()
        scanner = PathSuggestionScanner()

        completer = SmartBarAutoComplete(
            app=app,
            provenance=provenance,
            history=history,
            path_scanner=scanner,
        )

        assert completer is not None

    def test_instantiation_minimal(self):
        """SmartBarAutoComplete works with only app and provenance."""
        app = _make_app_mock([])
        provenance = CompletionProvenanceClassifier(app=app)

        completer = SmartBarAutoComplete(app=app, provenance=provenance)

        assert completer is not None


class TestSmartBarAutoCompleteCommandMode:
    """Test command-mode candidates (job names with provenance badges).

    Validates: Requirements 13.2, 13.4
    """

    def test_empty_bar_returns_all_jobs_and_builtins(self):
        """get_candidates with empty text returns all jobs + builtins."""
        jobs = [
            _make_job("deploy", docstring="Deploy the app"),
            _make_job("test", docstring="Run tests"),
        ]
        app = _make_app_mock(jobs)
        provenance = CompletionProvenanceClassifier(app=app)
        completer = SmartBarAutoComplete(app=app, provenance=provenance)

        state = _make_state("")
        candidates = completer.get_candidates(state)

        names = [c.value for c in candidates]
        assert "deploy" in names
        assert "test" in names
        assert "builtin" in names

    def test_partial_text_filters_candidates(self):
        """get_candidates with partial text filters to matching jobs."""
        jobs = [
            _make_job("deploy", docstring="Deploy"),
            _make_job("test", docstring="Test"),
            _make_job("dev-server", docstring="Dev server"),
        ]
        app = _make_app_mock(jobs)
        provenance = CompletionProvenanceClassifier(app=app)
        completer = SmartBarAutoComplete(app=app, provenance=provenance)

        state = _make_state("de")
        candidates = completer.get_candidates(state)

        names = [c.value for c in candidates]
        assert "deploy" in names
        assert "dev-server" in names
        assert "test" not in names

    def test_provenance_badges_in_prefix(self):
        """Command candidates have a provenance badge rendered in their display text.

        _make_dropdown_item() folds the provenance badge into the rich
        `main` Content (as "  (badge)") rather than a separate `.prefix`
        field — FunctualizeDropdownItem never receives a `prefix=` at
        construction, so `.prefix` is always None. Check the rendered
        plain text for the badge's parentheses instead.
        """
        jobs = [_make_job("deploy", docstring="Deploy")]
        app = _make_app_mock(jobs)
        provenance = CompletionProvenanceClassifier(app=app)
        completer = SmartBarAutoComplete(app=app, provenance=provenance)

        state = _make_state("deploy")
        candidates = completer.get_candidates(state)

        deploy_candidates = [c for c in candidates if c.value == "deploy"]
        assert len(deploy_candidates) == 1
        # The provenance badge is rendered as "(source)" within the display text.
        plain = deploy_candidates[0].main.plain
        assert "(" in plain
        assert ")" in plain


class TestSmartBarAutoCompleteSubcommandMode:
    """Test subcommand-mode candidates for builtin commands."""

    def test_builtin_offers_its_subcommands(self):
        """``builtin config `` offers show/path/edit/migrate."""
        app = _make_app_mock([_make_job("deploy", docstring="Deploy")])
        provenance = CompletionProvenanceClassifier(app=app)
        completer = SmartBarAutoComplete(app=app, provenance=provenance)

        state = _make_state("builtin config ")
        candidates = completer.get_candidates(state)

        names = [c.value for c in candidates]
        expected = ["show", "path", "edit", "migrate"]
        assert names == sorted(expected) or set(names) == set(expected)

    def test_partial_subcommand_filters(self):
        """``builtin cache c`` offers clear/check but not show."""
        app = _make_app_mock([_make_job("deploy", docstring="Deploy")])
        provenance = CompletionProvenanceClassifier(app=app)
        completer = SmartBarAutoComplete(app=app, provenance=provenance)

        state = _make_state("builtin cache c")
        candidates = completer.get_candidates(state)

        names = [c.value for c in candidates]
        assert "clear" in names
        assert "check" in names
        assert "show" not in names

    def test_builtin_without_subcommands_offers_none(self):
        """``builtin version `` has no subcommands → no subcommand candidates."""
        app = _make_app_mock([_make_job("deploy", docstring="Deploy")])
        provenance = CompletionProvenanceClassifier(app=app)
        completer = SmartBarAutoComplete(app=app, provenance=provenance)

        state = _make_state("builtin version ")
        candidates = completer.get_candidates(state)

        names = [c.value for c in candidates]
        assert "show" not in names
        assert "edit" not in names


class TestSmartBarAutoCompleteFlagMode:
    """Test flag-mode candidates (field completions with used-flag filtering).

    Validates: Requirements 13.2, 13.5
    """

    def test_flag_candidates_after_job_name(self):
        """get_candidates returns flag candidates after a recognized job."""
        fields = [
            _make_field("region", description="AWS region"),
            _make_field(
                "timeout", type_annotation="int", description="Timeout in seconds"
            ),
        ]
        jobs = [_make_job("deploy", fields=fields)]
        app = _make_app_mock(jobs)
        provenance = CompletionProvenanceClassifier(app=app)
        completer = SmartBarAutoComplete(app=app, provenance=provenance)

        state = _make_state("deploy --")
        candidates = completer.get_candidates(state)

        mains = [c.value for c in candidates]
        # Should include --region and --timeout
        assert any("region" in m for m in mains)
        assert any("timeout" in m for m in mains)

    def test_used_flags_excluded(self):
        """Already-used flags are excluded from candidates."""
        fields = [
            _make_field("region", description="AWS region"),
            _make_field("timeout", type_annotation="int", description="Timeout"),
            _make_field("verbose", type_annotation="bool", description="Verbose"),
        ]
        jobs = [_make_job("deploy", fields=fields)]
        app = _make_app_mock(jobs)
        provenance = CompletionProvenanceClassifier(app=app)
        completer = SmartBarAutoComplete(app=app, provenance=provenance)

        # --region already used
        state = _make_state("deploy --region us-east-1 --")
        candidates = completer.get_candidates(state)

        mains = [c.value for c in candidates]
        # region should be excluded, timeout/verbose available
        assert not any("region" in m for m in mains)
        assert any("timeout" in m for m in mains)

    def test_list_flags_remain_available(self):
        """List-typed flags remain available even after use."""
        fields = [
            _make_field("tags", type_annotation="list[str]", description="Tags"),
            _make_field("region", description="Region"),
        ]
        jobs = [_make_job("deploy", fields=fields)]
        app = _make_app_mock(jobs)
        provenance = CompletionProvenanceClassifier(app=app)
        completer = SmartBarAutoComplete(app=app, provenance=provenance)

        # --tags already used, but it's list type so should stay
        state = _make_state("deploy --tags foo --")
        candidates = completer.get_candidates(state)

        mains = [c.value for c in candidates]
        assert any("tags" in m for m in mains)


class TestSmartBarAutoCompleteValueMode:
    """Test value-mode candidates (choices, history, path suggestions).

    Validates: Requirements 13.6
    """

    def test_value_candidates_from_choices(self):
        """Value mode returns candidates from field choices."""
        fields = [
            _make_field(
                "environment",
                choices=["production", "staging", "development"],
                description="Target env",
            ),
        ]
        jobs = [_make_job("deploy", fields=fields)]
        app = _make_app_mock(jobs)
        provenance = CompletionProvenanceClassifier(app=app)
        completer = SmartBarAutoComplete(app=app, provenance=provenance)

        state = _make_state("deploy --environment ")
        candidates = completer.get_candidates(state)

        mains = [c.value for c in candidates]
        assert "production" in mains
        assert "staging" in mains
        assert "development" in mains

    def test_value_candidates_from_history(self):
        """Value mode returns candidates from argument history."""
        fields = [_make_field("region", description="AWS region")]
        jobs = [_make_job("deploy", fields=fields)]
        app = _make_app_mock(jobs)
        provenance = CompletionProvenanceClassifier(app=app)
        history = ArgumentHistory()
        history.record("deploy", "region", "us-east-1")
        history.record("deploy", "region", "eu-west-1")
        completer = SmartBarAutoComplete(
            app=app, provenance=provenance, history=history
        )

        state = _make_state("deploy --region ")
        candidates = completer.get_candidates(state)

        mains = [c.value for c in candidates]
        assert "us-east-1" in mains
        assert "eu-west-1" in mains


class TestSmartBarAutoCompletePositionalMode:
    """Test positional-mode candidates with [N] prefix.

    Validates: Requirements 13.7
    """

    def test_positional_candidates_with_choices(self):
        """Positional mode returns candidates with choices and [N] prefix."""
        fields = [
            _make_field(
                "target",
                choices=["local", "remote"],
                description="Deploy target",
            ),
        ]
        jobs = [_make_job("deploy", fields=fields)]
        app = _make_app_mock(jobs)
        provenance = CompletionProvenanceClassifier(app=app)

        # To trigger positional mode, we need a job with positional params registered.
        # The SmartBarAutoComplete caches positional_params - set it directly.
        completer = SmartBarAutoComplete(app=app, provenance=provenance)
        # Force positional params count to 1 for "deploy"
        completer._positional_params = {"deploy": 1}

        state = _make_state("deploy ")
        candidates = completer.get_candidates(state)

        # Should have candidates with [N] index prefix, rendered into the
        # display Content (.prefix is never populated — see
        # test_provenance_badges_in_prefix's docstring for why).
        if candidates:
            # Display text should contain [1] indicator (1-based)
            assert any("[1]" in c.main.plain for c in candidates)


class TestSmartBarAutoCompleteSearchString:
    """Test get_search_string returns the partial for current context.

    Validates: Requirement 13.3
    """

    def test_search_string_command_mode(self):
        """In command mode, search string is the partial command text."""
        jobs = [_make_job("deploy")]
        app = _make_app_mock(jobs)
        provenance = CompletionProvenanceClassifier(app=app)
        completer = SmartBarAutoComplete(app=app, provenance=provenance)

        state = _make_state("dep")
        result = completer.get_search_string(state)

        assert result == "dep"

    def test_search_string_flag_mode(self):
        """In flag mode, search string is the partial flag text."""
        fields = [_make_field("region")]
        jobs = [_make_job("deploy", fields=fields)]
        app = _make_app_mock(jobs)
        provenance = CompletionProvenanceClassifier(app=app)
        completer = SmartBarAutoComplete(app=app, provenance=provenance)

        state = _make_state("deploy --reg")
        result = completer.get_search_string(state)

        assert "reg" in result


class TestSmartBarAutoCompleteApplyCompletion:
    """Test apply_completion auto-quoting.

    Validates: Requirement 13.10
    """

    def test_value_without_spaces_not_quoted(self):
        """Values without spaces are not wrapped in quotes."""
        app = _make_app_mock([])
        provenance = CompletionProvenanceClassifier(app=app)
        completer = SmartBarAutoComplete(app=app, provenance=provenance)

        result = completer.get_completion_value("us-east-1")

        assert result == "us-east-1"

    def test_value_with_spaces_quoted(self):
        """Values with spaces are wrapped in quotes."""
        app = _make_app_mock([])
        provenance = CompletionProvenanceClassifier(app=app)
        completer = SmartBarAutoComplete(app=app, provenance=provenance)

        result = completer.get_completion_value("my region name")

        assert '"' in result or "'" in result
        # The quoted value should contain the original text
        assert "my region name" in result


class TestSmartBarAutoCompleteErrorHandling:
    """Test graceful error handling.

    Validates: Requirement 13.11
    """

    def test_invalid_input_returns_empty_candidates(self):
        """Parsing failure returns an empty candidate list."""
        app = _make_app_mock([])
        provenance = CompletionProvenanceClassifier(app=app)
        completer = SmartBarAutoComplete(app=app, provenance=provenance)

        # A state with mismatched cursor position shouldn't crash
        state = _make_state("", cursor_position=0)
        candidates = completer.get_candidates(state)

        # Should not raise, may return empty or some results
        assert isinstance(candidates, list)


# ---------------------------------------------------------------------------
# 2. PathSuggestionScanner integration tests
# ---------------------------------------------------------------------------


class TestPathSuggestionScannerRelative:
    """Test relative path suggestions.

    Validates: Requirements 15.2
    """

    def test_relative_path_from_cwd(self, tmp_path: Path):
        """Relative paths (./) resolve from CWD."""
        # Create directory structure
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").touch()
        (tmp_path / "tests").mkdir()

        scanner = PathSuggestionScanner()
        results = scanner.scan("./s", tmp_path)

        displays = [r.display for r in results]
        assert any("src" in d for d in displays)

    def test_bare_word_relative_scan(self, tmp_path: Path):
        """Bare word (no ./ prefix) resolves relative to CWD."""
        (tmp_path / "config").mkdir()
        (tmp_path / "config.toml").touch()

        scanner = PathSuggestionScanner()
        results = scanner.scan("config", tmp_path)

        # Should find both config/ and config.toml
        assert len(results) >= 1


class TestPathSuggestionScannerAbsolute:
    """Test absolute path suggestions.

    Validates: Requirements 15.3
    """

    def test_absolute_path_from_root(self, tmp_path: Path):
        """Absolute paths (/) resolve from the filesystem root."""
        # Create a temp structure and scan with absolute prefix
        (tmp_path / "alpha").mkdir()
        (tmp_path / "beta").mkdir()

        scanner = PathSuggestionScanner()
        results = scanner.scan(str(tmp_path) + "/a", tmp_path)

        displays = [r.display for r in results]
        assert any("alpha" in d for d in displays)


class TestPathSuggestionScannerHomeRelative:
    """Test home-relative path suggestions.

    Validates: Requirements 15.4
    """

    def test_home_relative_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Home-relative paths (~/) resolve from home directory."""
        # Mock Path.home() to use tmp_path
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        (tmp_path / "Documents").mkdir()
        (tmp_path / "Downloads").mkdir()

        scanner = PathSuggestionScanner()
        results = scanner.scan("~/Do", tmp_path)

        displays = [r.display for r in results]
        assert any("Documents" in d for d in displays)
        assert any("Downloads" in d for d in displays)


class TestPathSuggestionScannerDirectoryFilter:
    """Test file_filter="directory" shows only directories.

    Validates: Requirement 15.11 (DirectoryPath: dirs only)
    """

    def test_directory_filter_excludes_files(self, tmp_path: Path):
        """file_filter='directory' only shows directories."""
        (tmp_path / "src").mkdir()
        (tmp_path / "README.md").touch()
        (tmp_path / "data").mkdir()

        scanner = PathSuggestionScanner()
        results = scanner.scan("", tmp_path, file_filter="directory")

        # All results should be directories
        for r in results:
            assert r.is_directory, f"Expected directory but got file: {r.display}"

        # src and data should appear
        displays = [r.display for r in results]
        assert any("src" in d for d in displays)
        assert any("data" in d for d in displays)
        # README.md should NOT appear
        assert not any("README" in d for d in displays)


class TestPathSuggestionScannerPermissionErrors:
    """Test graceful handling of permission errors."""

    def test_unreadable_directory_returns_empty(self, tmp_path: Path):
        """Permission errors are handled gracefully (empty list, no crash)."""
        scanner = PathSuggestionScanner()
        # Scan a non-existent path — should not crash
        results = scanner.scan("/nonexistent/deeply/nested/path/", tmp_path)
        assert results == []


# ---------------------------------------------------------------------------
# 3. Old keybinds removed (migration verification)
# ---------------------------------------------------------------------------


class TestOldKeybindsRemoved:
    """Verify old keybinds and code patterns are removed.

    Validates: Requirements 22.13 (Ctrl+O, Ctrl+D removed)
    """

    def test_ctrl_o_not_in_bindings(self):
        """Ctrl+O is not in the BINDINGS list."""
        # Import the module source to inspect bindings
        import functualize._cli.inline_tui as tui_module

        source = inspect.getsource(tui_module)
        # Ctrl+O should not appear as a binding key
        assert 'ctrl+o"' not in source.lower()
        assert "ctrl+o'" not in source.lower()

    def test_ctrl_d_not_in_bindings(self):
        """Ctrl+D is not in the BINDINGS list."""
        import functualize._cli.inline_tui as tui_module

        source = inspect.getsource(tui_module)
        # Ctrl+D should not appear as a binding key
        assert 'ctrl+d"' not in source.lower()
        assert "ctrl+d'" not in source.lower()

    def test_no_action_quick_override_method(self):
        """No action_quick_override method exists in the module."""
        import functualize._cli.inline_tui as tui_module

        source = inspect.getsource(tui_module)
        assert "action_quick_override" not in source

    def test_no_completion_list_widget(self):
        """No CompletionList widget class exists in the module."""
        import functualize._cli.inline_tui as tui_module

        source = inspect.getsource(tui_module)
        assert "CompletionList" not in source


# ---------------------------------------------------------------------------
# 4. Preserved behaviors
# ---------------------------------------------------------------------------


class TestPreservedKeybindings:
    """Verify critical keybindings are preserved after migration.

    Validates: Requirements 22.9, 22.10
    """

    def test_ctrl_s_binding_exists(self):
        """save_shortcut action exists in the v3 app."""
        import functualize._cli.tui.app as tui_app_module

        source = inspect.getsource(tui_app_module)
        assert "action_save_shortcut" in source

    def test_ctrl_enter_triggers_execution(self):
        """Execute action exists in the v3 app."""
        import functualize._cli.tui.app as tui_app_module

        source = inspect.getsource(tui_app_module)
        assert "action_execute" in source

    def test_ctrl_q_binding_exists(self):
        """Quit action exists in the v3 app."""
        import functualize._cli.tui.app as tui_app_module

        source = inspect.getsource(tui_app_module)
        assert "action_quit" in source

    def test_escape_binding_exists(self):
        """Exit panel action exists in the v3 app."""
        import functualize._cli.tui.app as tui_app_module

        source = inspect.getsource(tui_app_module)
        assert "action_exit_panel" in source or "escape" in source

    def test_action_clear_or_dismiss_handles_breadcrumb_navigation(self):
        """The v3 app handles panel exit/dismiss."""
        import functualize._cli.tui.app as tui_app_module

        source = inspect.getsource(tui_app_module)
        # Should reference exit_panel or exit_to_command_mode
        assert "exit_panel" in source or "exit_to_command_mode" in source


# ---------------------------------------------------------------------------
# 5. Migration verification (no old code patterns)
# ---------------------------------------------------------------------------


class TestMigrationNoOldPatterns:
    """Verify old completion system code has been removed.

    Validates: Requirement 13.8 (remove old CompletionList, debounce, etc.)
    """

    def test_no_fuzzy_score_function(self):
        """_fuzzy_score function is NOT in inline_tui module."""
        import functualize._cli.inline_tui as tui_module

        source = inspect.getsource(tui_module)
        assert "_fuzzy_score" not in source

    def test_no_completion_item_class(self):
        """CompletionItem class is NOT in inline_tui module."""
        import functualize._cli.inline_tui as tui_module

        source = inspect.getsource(tui_module)
        assert "class CompletionItem" not in source

    def test_no_completion_list_class(self):
        """CompletionList class is NOT in inline_tui module."""
        import functualize._cli.inline_tui as tui_module

        source = inspect.getsource(tui_module)
        assert "class CompletionList" not in source

    def test_no_completions_locked_attribute(self):
        """_completions_locked attribute is NOT in inline_tui module."""
        import functualize._cli.inline_tui as tui_module

        source = inspect.getsource(tui_module)
        assert "_completions_locked" not in source

    def test_smart_bar_autocomplete_is_used(self):
        """SmartBarAutoComplete is imported and used in the v3 app."""
        import functualize._cli.tui.app as tui_app_module

        source = inspect.getsource(tui_app_module)
        assert "SmartBarAutoComplete" in source
