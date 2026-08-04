"""Unit tests for PreFlightWidget.

Tests the widget's rendering logic: field display, override indicators,
sensitive field masking, empty state, and keybinding hints.

Feature: TUI Config Inspector (Phase 4)
Task: 7.2
Validates: Requirements 5.2, 5.3, 5.4, 5.5, 5.6, 12.1
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._cli.data.pending_execution import PendingExecution
from functualize._cli.tui.preflight_widget import _MASK, PreFlightWidget, _is_sensitive
from functualize._config.chain import ResolvedValue

# ---------------------------------------------------------------------------
# Fake helpers
# ---------------------------------------------------------------------------


class FakeStatic:
    """Fake Static widget that captures update() calls."""

    def __init__(self) -> None:
        self.content: str = ""

    def update(self, content: str) -> None:
        self.content = content


class FakeKeyEvent:
    """Minimal fake Key event for testing on_key handler."""

    def __init__(self, key: str) -> None:
        self.key = key

    def prevent_default(self) -> None:
        pass

    def stop(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _resolved(value: Any, source_type: str = "file") -> ResolvedValue:
    """Create a ResolvedValue for testing."""
    return ResolvedValue(
        value=value,
        source_type=source_type,
        source_id="test",
        key="test_key",
        alternatives=[],
    )


def _make_pending(
    fields: dict[str, tuple[Any, str]],
    overrides: dict[str, tuple[Any, str]] | None = None,
) -> PendingExecution:
    """Create a PendingExecution from a simplified field spec.

    Args:
        fields: Mapping of field_name -> (value, source_type).
        overrides: Mapping of field_name -> (override_value, ignored). Under the
            SmartBar-as-CLI model overrides carry no per-field target, so the
            second tuple element is retained only for call-site compatibility.
    """
    resolved = {name: _resolved(val, src) for name, (val, src) in fields.items()}
    pending = PendingExecution(job_name="test_job", resolved_values=resolved)
    if overrides:
        for name, (val, _target) in overrides.items():
            pending.overrides[name] = val
    return pending


def _patch_widget(widget: PreFlightWidget, monkeypatch) -> FakeStatic:
    """Patch query_one on the widget to return a FakeStatic for '#pf-field-list'."""
    field_list = FakeStatic()

    def fake_query_one(selector, cls=None):
        if selector == "#pf-field-list":
            return field_list
        raise LookupError(f"No match for {selector}")

    monkeypatch.setattr(widget, "query_one", fake_query_one)
    return field_list


# ===========================================================================
# Unit Tests: update_from_pending renders fields
# ===========================================================================


class TestPreFlightRenderFields:
    """Test update_from_pending renders all fields with correct values and sources."""

    def test_renders_field_name_value_source(self, monkeypatch):
        """Each field name, its effective value, and source appear in output."""
        widget = PreFlightWidget()
        field_list = _patch_widget(widget, monkeypatch)

        pending = _make_pending(
            {
                "environment": ("production", "file"),
                "region": ("us-east-1", "env"),
            }
        )
        widget.update_from_pending(pending)

        assert "environment" in field_list.content
        assert "'production'" in field_list.content
        assert "file" in field_list.content
        assert "region" in field_list.content
        assert "'us-east-1'" in field_list.content
        assert "env" in field_list.content

    def test_renders_multiple_fields_sorted(self, monkeypatch):
        """Fields are rendered in alphabetical order."""
        widget = PreFlightWidget()
        field_list = _patch_widget(widget, monkeypatch)

        pending = _make_pending(
            {
                "zebra": ("z", "default"),
                "alpha": ("a", "cli"),
                "middle": ("m", "session"),
            }
        )
        widget.update_from_pending(pending)

        content = field_list.content
        assert content.index("alpha") < content.index("middle") < content.index("zebra")

    def test_renders_effective_override_value(self, monkeypatch):
        """When a field is overridden, the effective (override) value is shown."""
        widget = PreFlightWidget()
        field_list = _patch_widget(widget, monkeypatch)

        pending = _make_pending(
            {"environment": ("production", "file")},
            overrides={"environment": ("staging", "session")},
        )
        widget.update_from_pending(pending)

        # Should show the override value, not the resolved value
        assert "'staging'" in field_list.content

    def test_renders_override_source_label(self, monkeypatch):
        """When a field is overridden, source label is 'cli' (SmartBar-as-CLI)."""
        widget = PreFlightWidget()
        field_list = _patch_widget(widget, monkeypatch)

        pending = _make_pending(
            {"environment": ("production", "file")},
            overrides={"environment": ("staging", "session")},
        )
        widget.update_from_pending(pending)

        assert "(cli)" in field_list.content


# ===========================================================================
# Unit Tests: Override indicator
# ===========================================================================


class TestPreFlightOverrideIndicator:
    """Test override indicator appears for overridden fields."""

    def test_override_indicator_present(self, monkeypatch):
        """Overridden field shows the override marker."""
        widget = PreFlightWidget()
        field_list = _patch_widget(widget, monkeypatch)

        pending = _make_pending(
            {"environment": ("production", "file")},
            overrides={"environment": ("staging", "session")},
        )
        widget.update_from_pending(pending)

        assert "⚡override" in field_list.content

    def test_no_override_indicator_for_unmodified(self, monkeypatch):
        """Non-overridden field does NOT show override marker."""
        widget = PreFlightWidget()
        field_list = _patch_widget(widget, monkeypatch)

        pending = _make_pending({"environment": ("production", "file")})
        widget.update_from_pending(pending)

        assert "⚡override" not in field_list.content

    def test_mixed_override_and_unmodified(self, monkeypatch):
        """Only overridden fields show indicator, not unmodified ones."""
        widget = PreFlightWidget()
        field_list = _patch_widget(widget, monkeypatch)

        pending = _make_pending(
            {
                "environment": ("production", "file"),
                "region": ("us-east-1", "env"),
            },
            overrides={"environment": ("staging", "session")},
        )
        widget.update_from_pending(pending)

        # The content will contain exactly one override marker
        assert field_list.content.count("⚡override") == 1


# ===========================================================================
# Unit Tests: Sensitive field masking
# ===========================================================================


class TestPreFlightSensitiveMasking:
    """Test sensitive field masking (fields with sensitive keywords show asterisks)."""

    def test_password_field_masked(self, monkeypatch):
        """Field with 'password' in name shows asterisks."""
        widget = PreFlightWidget()
        field_list = _patch_widget(widget, monkeypatch)

        pending = _make_pending({"db_password": ("supersecret123", "file")})
        widget.update_from_pending(pending)

        assert _MASK in field_list.content
        assert "supersecret123" not in field_list.content

    def test_secret_field_masked(self, monkeypatch):
        """Field with 'secret' in name shows asterisks."""
        widget = PreFlightWidget()
        field_list = _patch_widget(widget, monkeypatch)

        pending = _make_pending({"api_secret": ("abc123", "env")})
        widget.update_from_pending(pending)

        assert _MASK in field_list.content
        assert "abc123" not in field_list.content

    def test_token_field_masked(self, monkeypatch):
        """Field with 'token' in name shows asterisks."""
        widget = PreFlightWidget()
        field_list = _patch_widget(widget, monkeypatch)

        pending = _make_pending({"auth_token": ("tok_xyz", "session")})
        widget.update_from_pending(pending)

        assert _MASK in field_list.content
        assert "tok_xyz" not in field_list.content

    def test_key_field_masked(self, monkeypatch):
        """Field with 'key' in name shows asterisks."""
        widget = PreFlightWidget()
        field_list = _patch_widget(widget, monkeypatch)

        pending = _make_pending({"api_key": ("key_abc", "file")})
        widget.update_from_pending(pending)

        assert _MASK in field_list.content
        assert "key_abc" not in field_list.content

    def test_non_sensitive_field_not_masked(self, monkeypatch):
        """Field without sensitive keywords shows the actual value."""
        widget = PreFlightWidget()
        field_list = _patch_widget(widget, monkeypatch)

        pending = _make_pending({"environment": ("production", "file")})
        widget.update_from_pending(pending)

        assert "'production'" in field_list.content
        assert _MASK not in field_list.content

    def test_case_insensitive_masking(self, monkeypatch):
        """Masking is case-insensitive: 'PASSWORD', 'Password' etc. all masked."""
        widget = PreFlightWidget()
        field_list = _patch_widget(widget, monkeypatch)

        pending = _make_pending({"DB_PASSWORD": ("secret", "file")})
        widget.update_from_pending(pending)

        assert _MASK in field_list.content
        assert "'secret'" not in field_list.content


# ===========================================================================
# Unit Tests: Empty resolved_values
# ===========================================================================


class TestPreFlightEmptyState:
    """Test empty resolved_values shows 'No configuration fields' message."""

    def test_empty_resolved_values_message(self, monkeypatch):
        """Empty resolved_values shows the no-fields message."""
        widget = PreFlightWidget()
        field_list = _patch_widget(widget, monkeypatch)

        pending = PendingExecution(
            job_name="test_job",
            resolved_values={},
            overrides={},
        )
        widget.update_from_pending(pending)

        assert "No configuration fields" in field_list.content


# ===========================================================================
# Unit Tests: Keybinding hints (verified via source inspection)
# ===========================================================================


class TestPreFlightKeybindingHints:
    """Test keybinding hints are displayed.

    The hints are baked into the compose() method as a Static widget.
    Since compose() requires an active Textual App context (uses Vertical),
    we use the Textual App test driver for these.
    """

    async def test_hints_contain_ctrl_k(self):
        """Hints include Ctrl+J."""
        from textual.app import App, ComposeResult

        class _App(App):
            def compose(self) -> ComposeResult:
                yield PreFlightWidget(id="pf")

        app = _App()
        async with app.run_test(size=(120, 20)) as pilot:
            await pilot.pause()
            hints = app.query(".pf-hints")
            assert len(hints) > 0
            content = hints[0].content
            assert "Ctrl+J" in content

    async def test_hints_contain_ctrl_o(self):
        """Hints include Ctrl+K."""
        from textual.app import App, ComposeResult

        class _App(App):
            def compose(self) -> ComposeResult:
                yield PreFlightWidget(id="pf")

        app = _App()
        async with app.run_test(size=(120, 20)) as pilot:
            await pilot.pause()
            hints = app.query(".pf-hints")
            content = hints[0].content
            assert "Ctrl+K" in content

    async def test_hints_contain_ctrl_d(self):
        """Hints include Ctrl+L."""
        from textual.app import App, ComposeResult

        class _App(App):
            def compose(self) -> ComposeResult:
                yield PreFlightWidget(id="pf")

        app = _App()
        async with app.run_test(size=(120, 20)) as pilot:
            await pilot.pause()
            hints = app.query(".pf-hints")
            content = hints[0].content
            assert "Ctrl+L" in content


# ===========================================================================
# Unit Tests: Key event handling
# ===========================================================================


class TestPreFlightKeyHandling:
    """Test key event handling posts correct messages."""

    def test_ctrl_k_posts_config_table_requested(self, monkeypatch):
        """Ctrl+J posts ConfigTableRequested message."""
        widget = PreFlightWidget()
        posted: list = []
        monkeypatch.setattr(widget, "post_message", lambda msg: posted.append(msg))

        widget.on_key(FakeKeyEvent("ctrl+j"))

        assert len(posted) == 1
        assert isinstance(posted[0], PreFlightWidget.ConfigTableRequested)

    def test_ctrl_o_posts_override_requested(self, monkeypatch):
        """Ctrl+K posts OverrideRequested message."""
        widget = PreFlightWidget()
        posted: list = []
        monkeypatch.setattr(widget, "post_message", lambda msg: posted.append(msg))

        widget.on_key(FakeKeyEvent("ctrl+k"))

        assert len(posted) == 1
        assert isinstance(posted[0], PreFlightWidget.OverrideRequested)

    def test_ctrl_d_posts_diff_requested(self, monkeypatch):
        """Ctrl+L posts DiffRequested message."""
        widget = PreFlightWidget()
        posted: list = []
        monkeypatch.setattr(widget, "post_message", lambda msg: posted.append(msg))

        widget.on_key(FakeKeyEvent("ctrl+l"))

        assert len(posted) == 1
        assert isinstance(posted[0], PreFlightWidget.DiffRequested)

    def test_unhandled_key_no_message(self, monkeypatch):
        """Non-handled key does not post any message."""
        widget = PreFlightWidget()
        posted: list = []
        monkeypatch.setattr(widget, "post_message", lambda msg: posted.append(msg))

        widget.on_key(FakeKeyEvent("enter"))

        assert len(posted) == 0


# ===========================================================================
# Unit Tests: _is_sensitive helper
# ===========================================================================


class TestIsSensitive:
    """Test the _is_sensitive helper function directly."""

    def test_password_sensitive(self) -> None:
        assert _is_sensitive("db_password") is True

    def test_secret_sensitive(self) -> None:
        assert _is_sensitive("api_secret") is True

    def test_token_sensitive(self) -> None:
        assert _is_sensitive("auth_token") is True

    def test_key_sensitive(self) -> None:
        assert _is_sensitive("api_key") is True

    def test_non_sensitive(self) -> None:
        assert _is_sensitive("environment") is False

    def test_case_insensitive(self) -> None:
        assert _is_sensitive("DB_PASSWORD") is True
        assert _is_sensitive("Auth_Token") is True


# ===========================================================================
# Property 13: Display completeness
# ===========================================================================


_FIELD_NAME_ALPHABET = st.characters(
    whitelist_categories=("L", "N"),
    whitelist_characters="_",
)


class TestDisplayCompletenessProperty:
    """Property 13: Display completeness.

    Every field from resolved_values appears in rendered output.

    **Validates: Requirements 5.2**
    """

    @pytest.mark.slow
    @given(
        field_names=st.lists(
            st.text(alphabet=_FIELD_NAME_ALPHABET, min_size=1, max_size=20),
            min_size=1,
            max_size=10,
            unique=True,
        ),
    )
    @settings(max_examples=100)
    def test_every_field_in_output(self, field_names: list[str]) -> None:
        """Every field from resolved_values appears in the rendered text.

        **Validates: Requirements 5.2**
        """
        resolved = {
            name: _resolved(f"val_{i}", "file") for i, name in enumerate(field_names)
        }
        pending = PendingExecution(
            job_name="test_job",
            resolved_values=resolved,
            overrides={},
        )

        widget = PreFlightWidget()
        field_list = FakeStatic()
        widget.query_one = lambda selector, cls=None: field_list  # type: ignore[assignment]
        widget.update_from_pending(pending)

        for name in field_names:
            assert name in field_list.content, (
                f"Field {name!r} not found in rendered output"
            )


# ===========================================================================
# Property 15: Sensitive field masking
# ===========================================================================


_SENSITIVE_KEYWORDS = ["secret", "password", "token", "key"]


class TestSensitiveMaskingProperty:
    """Property 15: Sensitive field masking.

    Fields with sensitive keywords show asterisks instead of actual values.

    **Validates: Requirements 5.6, 12.1**
    """

    @pytest.mark.slow
    @given(
        keyword=st.sampled_from(_SENSITIVE_KEYWORDS),
        prefix=st.text(
            alphabet=st.characters(whitelist_categories=("L",)),
            min_size=0,
            max_size=10,
        ),
        suffix=st.text(
            alphabet=st.characters(whitelist_categories=("L",)),
            min_size=0,
            max_size=10,
        ),
        value=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "P")),
            min_size=1,
            max_size=50,
        ),
    )
    @settings(max_examples=100)
    def test_sensitive_fields_always_masked(
        self, keyword: str, prefix: str, suffix: str, value: str
    ) -> None:
        """Any field containing a sensitive keyword has its value masked.

        **Validates: Requirements 5.6, 12.1**
        """
        field_name = f"{prefix}{keyword}{suffix}"
        # Ensure it's a valid non-empty name
        if not field_name.strip():
            field_name = keyword

        resolved = {field_name: _resolved(value, "file")}
        pending = PendingExecution(
            job_name="test_job",
            resolved_values=resolved,
            overrides={},
        )

        widget = PreFlightWidget()
        field_list = FakeStatic()
        widget.query_one = lambda selector, cls=None: field_list  # type: ignore[assignment]
        widget.update_from_pending(pending)

        # The mask should appear
        assert _MASK in field_list.content, (
            f"Expected mask {_MASK!r} for sensitive field {field_name!r}"
        )
        # The actual value repr should NOT appear (unless it happens to equal the mask)
        if repr(value) != _MASK and value != _MASK:
            assert repr(value) not in field_list.content, (
                f"Sensitive value {value!r} should be masked for field {field_name!r}"
            )
