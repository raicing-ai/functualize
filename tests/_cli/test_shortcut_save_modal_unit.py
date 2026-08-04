"""Unit tests for ShortcutSaveModal.

Tests the modal's internal logic: name sanitization, confirm flow,
file writing, and message posting behavior.

Feature: TUI Smart Bar & Modals (Phase 3)
Task: 9.2
Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5
"""

from __future__ import annotations

from functualize._cli.tui.shortcut_save_modal import (
    ShortcutSaveModal,
    _sanitize_name_for_python,
)

# ===========================================================================
# Unit Tests: _sanitize_name_for_python
# ===========================================================================


class TestSanitizeName:
    """Test the module-level helper that converts job names to Python identifiers."""

    def test_hyphens_to_underscores(self):
        """Hyphens in job name are replaced with underscores."""
        assert _sanitize_name_for_python("my-deploy") == "my_deploy"

    def test_dots_to_underscores(self):
        """Dots in job name are replaced with underscores."""
        assert _sanitize_name_for_python("infra.deploy") == "infra_deploy"

    def test_no_change_needed(self):
        """Simple names pass through unchanged."""
        assert _sanitize_name_for_python("deploy") == "deploy"

    def test_mixed(self):
        """Mixed hyphens and dots are all replaced."""
        assert _sanitize_name_for_python("my-infra.deploy") == "my_infra_deploy"


# ===========================================================================
# Unit Tests: Constructor
# ===========================================================================


class TestShortcutSaveModalConstruction:
    """Test that modal stores job_name and kwargs from constructor."""

    def test_stores_job_name(self):
        """Modal stores _job_name from constructor."""
        modal = ShortcutSaveModal("deploy", {"env": "staging"})
        assert modal._job_name == "deploy"

    def test_stores_kwargs(self):
        """Modal stores _kwargs dict from constructor."""
        kwargs = {"env": "staging", "region": "us-east-1"}
        modal = ShortcutSaveModal("deploy", kwargs)
        assert modal._kwargs == kwargs

    def test_stores_empty_kwargs(self):
        """Modal handles empty kwargs dict."""
        modal = ShortcutSaveModal("deploy", {})
        assert modal._kwargs == {}


# ===========================================================================
# Unit Tests: _confirm (ShortcutSaved message posted on success)
# ===========================================================================


class TestShortcutSaveModalConfirm:
    """Test _confirm validates, writes file, and posts ShortcutSaved."""

    def test_confirm_writes_file_and_posts_saved(self, tmp_path, monkeypatch):
        """_confirm writes file and posts ShortcutSaved on success.

        Validates: Requirement 8.2, 8.3
        """
        modal = ShortcutSaveModal("deploy", {"env": "staging"})

        output_file = tmp_path / "shortcuts.py"
        values = {
            "ssm-input-name": "deploy",
            "ssm-input-file": str(output_file),
        }
        monkeypatch.setattr(modal, "_get_input_value", lambda id: values.get(id, ""))

        # Capture messages
        posted: list = []
        monkeypatch.setattr(modal, "post_message", lambda msg: posted.append(msg))

        dismissed: list = []
        monkeypatch.setattr(
            modal, "dismiss", lambda result=None: dismissed.append(result)
        )

        modal._confirm()

        assert len(posted) == 1
        msg = posted[0]
        assert isinstance(msg, ShortcutSaveModal.ShortcutSaved)
        assert "shortcuts.py" in msg.path

        # Verify file was written
        assert output_file.exists()
        content = output_file.read_text()
        assert "def deploy" in content
        assert 'JOB_GROUP = "shortcut"' in content

        # ModalScreen contract: confirm dismisses with the
        # written file's path, matching the ShortcutSaved message's path.
        assert dismissed == [str(output_file)]

    def test_confirm_with_invalid_name_shows_error(self, monkeypatch):
        """_confirm with invalid name shows error, doesn't post ShortcutSaved.

        Validates: Requirement 8.5
        """
        modal = ShortcutSaveModal("deploy", {})

        values = {
            "ssm-input-name": "123invalid",
            "ssm-input-file": "/tmp/shortcuts.py",
        }
        monkeypatch.setattr(modal, "_get_input_value", lambda id: values.get(id, ""))

        posted: list = []
        monkeypatch.setattr(modal, "post_message", lambda msg: posted.append(msg))

        errors_shown: list = []
        monkeypatch.setattr(modal, "_show_error", lambda msg: errors_shown.append(msg))

        dismissed: list = []
        monkeypatch.setattr(
            modal, "dismiss", lambda result=None: dismissed.append(result)
        )

        modal._confirm()

        assert len(posted) == 0  # No ShortcutSaved posted
        assert len(errors_shown) == 1  # Error was shown
        # Scenario 9 (invalid name): screen must remain open — no dismiss.
        assert dismissed == []

    def test_confirm_output_file_not_ending_in_py_shows_error(self, monkeypatch):
        """_confirm with an output file that doesn't end in .py shows error."""
        modal = ShortcutSaveModal("deploy", {"env": "staging"})

        values = {
            "ssm-input-name": "deploy",
            "ssm-input-file": "/tmp/shortcuts",
        }
        monkeypatch.setattr(modal, "_get_input_value", lambda id: values.get(id, ""))

        posted: list = []
        monkeypatch.setattr(modal, "post_message", lambda msg: posted.append(msg))

        errors_shown: list = []
        monkeypatch.setattr(modal, "_show_error", lambda msg: errors_shown.append(msg))

        dismissed: list = []
        monkeypatch.setattr(
            modal, "dismiss", lambda result=None: dismissed.append(result)
        )

        modal._confirm()

        assert len(posted) == 0
        assert len(errors_shown) == 1
        assert ".py" in errors_shown[0]
        assert dismissed == []

    def test_confirm_unwritable_dir_shows_error(self, tmp_path, monkeypatch):
        """_confirm with non-writable output dir shows error.

        Validates: Requirement 8.5
        """
        modal = ShortcutSaveModal("deploy", {"env": "staging"})

        # Use a path that doesn't exist and can't be created
        bad_file = "/root/nonexistent_dir_for_test_xyz/shortcuts.py"
        values = {
            "ssm-input-name": "deploy",
            "ssm-input-file": bad_file,
        }
        monkeypatch.setattr(modal, "_get_input_value", lambda id: values.get(id, ""))

        posted: list = []
        monkeypatch.setattr(modal, "post_message", lambda msg: posted.append(msg))

        errors_shown: list = []
        monkeypatch.setattr(modal, "_show_error", lambda msg: errors_shown.append(msg))

        dismissed: list = []
        monkeypatch.setattr(
            modal, "dismiss", lambda result=None: dismissed.append(result)
        )

        modal._confirm()

        assert len(posted) == 0  # No ShortcutSaved
        assert len(errors_shown) == 1  # Error was displayed
        assert "Write failed" in errors_shown[0]
        assert dismissed == []


# ===========================================================================
# Unit Tests: Escape (ShortcutCancelled)
# ===========================================================================


class TestShortcutSaveModalEscape:
    """Test that Escape posts ShortcutCancelled and dismisses the ModalScreen.

    Validates: Requirement 8.4 (dismiss(None) on cancel)
    """

    def test_escape_posts_cancelled_and_dismisses_with_none(self, monkeypatch):
        """Pressing Escape posts ShortcutCancelled and calls dismiss(None)."""
        modal = ShortcutSaveModal("deploy", {})

        posted: list = []
        monkeypatch.setattr(modal, "post_message", lambda msg: posted.append(msg))

        dismissed: list = []
        monkeypatch.setattr(
            modal, "dismiss", lambda result=None: dismissed.append(result)
        )

        class FakeEvent:
            key = "escape"

            def prevent_default(self):
                pass

            def stop(self):
                pass

        modal.on_key(FakeEvent())

        assert len(posted) == 1
        assert isinstance(posted[0], ShortcutSaveModal.ShortcutCancelled)
        # ModalScreen contract: cancel path dismisses with None.
        assert dismissed == [None]


# ===========================================================================
# Unit Tests: Pre-fill from job_name
# ===========================================================================


class TestShortcutSaveModalPreFill:
    """Test that shortcut_name is pre-filled from sanitized job_name.

    Validates: Requirement 8.1
    """

    def test_job_name_sanitized_for_prefill(self):
        """Job name with hyphens/dots produces sanitized shortcut_name default."""
        modal = ShortcutSaveModal("my-infra.deploy", {"env": "staging"})
        # The compose() method creates an Input with value=_sanitize_name_for_python(job_name)
        # We verify the job_name is stored and sanitization is correct
        assert modal._job_name == "my-infra.deploy"
        assert _sanitize_name_for_python(modal._job_name) == "my_infra_deploy"

    def test_simple_job_name_unchanged(self):
        """Simple job name without special chars used as-is."""
        modal = ShortcutSaveModal("deploy", {})
        assert _sanitize_name_for_python(modal._job_name) == "deploy"


# ===========================================================================
# Unit Tests: CSS Layer
# ===========================================================================


class TestShortcutSaveModalCSS:
    """Test that modal renders on the 'modal' layer."""

    def test_modal_layer_in_css(self):
        """DEFAULT_CSS bounds the inner dialog container, not the Screen itself.

        ``ShortcutSaveModal`` is a ``ModalScreen`` — it renders on top via
        Textual's screen_stack (no ``layer: modal`` hack needed, unlike the
        old Widget-based version). Box-model constraints (width/max-height)
        must target the inner ``#ssm-dialog`` container: applying them
        directly to the Screen selector doesn't produce a bounded floating
        panel, since a Screen fills the viewport by default.
        """
        css = ShortcutSaveModal.DEFAULT_CSS
        assert "align: center middle" in css
        assert "#ssm-dialog" in css
        assert "width:" in css
        assert "max-height:" in css
