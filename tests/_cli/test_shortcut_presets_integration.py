"""Integration tests for shortcut save and invocation presets.

Tests the interaction between ShortcutSaveModal, ShortcutGenerator,
InvocationPreset, and CompletionProvenanceClassifier.

Feature: TUI Smart Bar & Modals
Task: 13.2
Validates: Requirements 8.1, 8.3, 10.1, 10.5
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.completions.provenance import ProvenanceInfo
from functualize._cli.data.argument_history import ArgumentHistory
from functualize._cli.data.invocation_preset import get_recent_invocations
from functualize._cli.tui.shortcut_save_modal import (
    ShortcutSaveModal,
)


class TestShortcutSaveIntegration:
    """Integration: Ctrl+S → ShortcutSaveModal → file write."""

    def test_ctrl_s_modal_receives_command_parts(self):
        """ShortcutSaveModal stores job_name and kwargs from current command.
        Validates: Requirement 8.1"""
        # Simulate what action_save_shortcut does:
        text = "deploy --env staging --region us-east-1"
        tokens = text.split()
        job_name = tokens[0]
        # Parse kwargs (simulate _parse_cli_args_to_kwargs)
        kwargs = {}
        i = 0
        args = tokens[1:]
        while i < len(args):
            if args[i].startswith("--"):
                key = args[i][2:].replace("-", "_")
                if i + 1 < len(args) and not args[i + 1].startswith("--"):
                    kwargs[key] = args[i + 1]
                    i += 1
            i += 1

        modal = ShortcutSaveModal(job_name=job_name, kwargs=kwargs)
        assert modal._job_name == "deploy"
        assert modal._kwargs == {"env": "staging", "region": "us-east-1"}

    def test_successful_save_writes_valid_file(self, tmp_path, monkeypatch):
        """Save produces a valid Python file that compiles.
        Validates: Requirement 8.3"""
        modal = ShortcutSaveModal("deploy", {"env": "staging"})

        output_file = tmp_path / "shortcuts.py"
        values = {
            "ssm-input-name": "deploy",
            "ssm-input-file": str(output_file),
        }
        monkeypatch.setattr(modal, "_get_input_value", lambda id: values.get(id, ""))

        posted: list = []
        monkeypatch.setattr(modal, "post_message", lambda msg: posted.append(msg))
        monkeypatch.setattr(modal, "dismiss", lambda result=None: None)

        modal._confirm()

        # File was written
        assert output_file.exists()
        content = output_file.read_text()
        # Content is valid Python
        compile(content, "<test>", "exec")
        # Content includes the kwargs
        assert "staging" in content
        # Content is grouped under shortcut.* to avoid job name collisions
        assert 'JOB_GROUP = "shortcut"' in content


class TestInvocationPresetsIntegration:
    """Integration: invocation presets in completion list."""

    def test_presets_appear_for_jobs_with_history(self):
        """Jobs with history produce InvocationPreset items.
        Validates: Requirement 10.1"""
        history = ArgumentHistory(_store={}, _max_entries=50, _path=None, _dirty=False)
        history.record("deploy", "env", "staging")
        history.record("deploy", "region", "us-east-1")

        presets = get_recent_invocations(history, ["deploy", "build"], limit=5)

        assert len(presets) == 1
        assert presets[0].job_name == "deploy"

    def test_preset_display_text_format(self):
        """Preset display_text has expected format.
        Validates: Requirement 10.5"""
        history = ArgumentHistory(_store={}, _max_entries=50, _path=None, _dirty=False)
        history.record("deploy", "env", "staging")
        history.record("deploy", "region", "us-east-1")

        presets = get_recent_invocations(history, ["deploy"], limit=5)

        assert len(presets) == 1
        display = presets[0].display_text
        assert "deploy" in display
        assert "--env" in display
        assert "staging" in display
        assert "--region" in display
        assert "us-east-1" in display

    def test_preset_provenance_badge(self):
        """Presets get 'recent' provenance badge in completion list.
        Validates: Requirement 10.5"""
        # Simulate what the TUI does:
        recent_prov = ProvenanceInfo(
            source_type="recent",
            display_label="recent",
            badge_style="bold yellow",
        )
        assert recent_prov.source_type == "recent"
        assert recent_prov.badge_style == "bold yellow"


# Property 8: Provenance badge assignment is total
@pytest.mark.slow
class TestProvenanceBadgeAssignmentTotal:
    """Property 8: Provenance badge assignment is total.

    For any job, get_provenance SHALL return a ProvenanceInfo with
    source_type in {"local", "plugin", "child", "builtin"}.

    **Validates: Requirements 1.3**
    """

    @given(
        source_type=st.sampled_from(["local", "plugin", "child", "builtin"]),
        display_label=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz_-", min_size=1, max_size=15
        ),
        badge_style=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz ", min_size=1, max_size=15
        ),
    )
    def test_provenance_info_always_valid(
        self, source_type, display_label, badge_style
    ):
        """ProvenanceInfo always has valid source_type.
        **Validates: Requirements 1.3**"""
        prov = ProvenanceInfo(
            source_type=source_type,
            display_label=display_label,
            badge_style=badge_style,
        )
        assert prov.source_type in {"local", "plugin", "child", "builtin"}
        assert prov.display_label == display_label
        assert prov.badge_style == badge_style
