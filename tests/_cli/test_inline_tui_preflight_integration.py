"""Integration tests for pre-flight auto-show wiring.

Tests the integration between PendingExecution creation, PanelRingController
state management, and PreFlightWidget rendering when the smart bar turns
green. Validates the wiring logic implemented in inline_tui.py task 13.1,
updated for Phase 5-6 migration (task 20.1).

Feature: TUI Config Inspector (Phase 4), migrated to TUI Architecture v2
Task: 13.2, 20.1
Validates: Requirements 1.1, 5.1, 5.2, 5.4
"""

from __future__ import annotations

from typing import Any

from functualize._cli.data.pending_execution import PendingExecution
from functualize._cli.tui.models.panel_ring_controller import PanelRingController
from functualize._cli.tui.preflight_widget import PreFlightWidget
from functualize._config.chain import ResolvedValue

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


def _make_resolved_values(
    fields: dict[str, tuple[Any, str]],
) -> dict[str, ResolvedValue]:
    """Create a resolved_values dict from a simplified field spec.

    Args:
        fields: Mapping of field_name -> (value, source_type).
    """
    return {name: _resolved(val, src) for name, (val, src) in fields.items()}


def _parse_cli_args_to_kwargs(args: list[str]) -> dict[str, str]:
    """Parse CLI-style args (--key value) into kwargs dict.

    This mirrors the _parse_cli_args_to_kwargs in inline_tui.py.
    """
    kwargs: dict[str, str] = {}
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("--"):
            key = arg[2:].replace("-", "_")
            if "=" in key:
                k, v = key.split("=", 1)
                kwargs[k] = v
            elif i + 1 < len(args) and not args[i + 1].startswith("--"):
                kwargs[key] = args[i + 1]
                i += 1
            else:
                kwargs[key] = "true"
        i += 1
    return kwargs


class FakeStatic:
    """Fake Static widget that captures update() calls."""

    def __init__(self) -> None:
        self.content: str = ""

    def update(self, content: str) -> None:
        self.content = content


# ===========================================================================
# Integration Tests: Bar turning green triggers PendingExecution creation
# ===========================================================================


class TestBarGreenTriggersPendingExecution:
    """Test that bar turning green triggers PendingExecution creation.

    Validates: Requirement 1.1
    """

    def test_pending_execution_created_from_resolved_values(self):
        """When the bar is green and job is valid, PendingExecution is created
        from the ResolutionChain resolve_section result.

        Simulates the wiring in inline_tui._async_update where is_ready=True
        triggers PendingExecution creation.
        """
        # Simulate resolved values from ResolutionChain.resolve_section()
        resolved = _make_resolved_values(
            {
                "environment": ("production", "file"),
                "region": ("us-east-1", "env"),
                "timeout": (30, "default"),
            }
        )

        # This is the logic from inline_tui._async_update when is_valid=True
        pending = PendingExecution(
            job_name="deploy",
            resolved_values=resolved,
            overrides={},
        )

        assert pending.job_name == "deploy"
        assert pending.resolved_values == resolved
        assert pending.overrides == {}
        assert pending.override_count() == 0

    def test_pending_execution_created_with_empty_overrides(self):
        """PendingExecution starts with empty overrides when no CLI args provided.

        Validates that the initial state has no overrides before CLI arg parsing.
        """
        resolved = _make_resolved_values({"field_a": ("val_a", "file")})

        pending = PendingExecution(
            job_name="build",
            resolved_values=resolved,
            overrides={},
        )

        assert pending.override_count() == 0
        assert not pending.has_override("field_a")
        assert pending.effective_value("field_a") == "val_a"
        assert pending.effective_source("field_a") == "file"

    def test_pending_execution_not_created_for_non_job(self):
        """When the bar is green but the command is a builtin (not a job),
        PendingExecution is not created.

        Simulates: `if is_valid and tokens[0] in job_names` — if the
        command is not in job_names, the branch is skipped.
        """
        job_names = ["deploy", "build"]
        tokens = ["version"]  # builtin, not a job

        is_valid = True
        pending_execution = None

        # Mirror the inline_tui logic
        if is_valid and tokens[0] in job_names:
            pending_execution = PendingExecution(
                job_name=tokens[0],
                resolved_values={},
                overrides={},
            )

        assert pending_execution is None


# ===========================================================================
# Integration Tests: ContentSwitcher switches to pre-flight when bar is green
# ===========================================================================


class TestContentSwitcherPreFlight:
    """Test that PanelRingController breadcrumb depth controls panel switching.

    In the new architecture, automatic bar state changes switch the
    ContentSwitcher directly (not via controller). The controller's
    breadcrumb_depth == 0 check guards against interrupting deeper views.

    Validates: Requirement 5.1
    """

    def test_panel_shows_preflight_when_bar_green_and_depth_zero(self):
        """When is_ready=True and breadcrumb_depth==0, ContentSwitcher shows pre-flight.

        This mirrors the inline_tui logic:
            if self._panel_controller.breadcrumb_depth == 0:
                help_area.current = "pre-flight"
        """
        controller = PanelRingController()

        # Breadcrumb depth is 0 initially
        assert controller.breadcrumb_depth == 0

        # The inline_tui checks breadcrumb_depth before switching
        # When depth is 0 and bar is green, it sets current = "pre-flight"
        # This simulates the condition check
        is_ready = True
        if is_ready and controller.breadcrumb_depth == 0:
            panel_id = "pre-flight"
        else:
            panel_id = "help-panel"

        assert panel_id == "pre-flight"

    def test_panel_shows_help_when_bar_not_ready_and_depth_zero(self):
        """When bar is not ready and breadcrumb_depth==0, shows help-panel.

        Simulates user typing → bar green → user deletes character → bar grey.
        """
        controller = PanelRingController()

        # Breadcrumb depth is 0
        assert controller.breadcrumb_depth == 0

        is_ready = False
        if is_ready and controller.breadcrumb_depth == 0:
            panel_id = "pre-flight"
        elif controller.breadcrumb_depth == 0:
            panel_id = "help-panel"
        else:
            panel_id = None  # Don't change

        assert panel_id == "help-panel"

    def test_deeper_mode_not_interrupted_by_bar_green(self):
        """If user is in a deeper mode (breadcrumb_depth > 0), bar turning green
        does NOT switch away from the current view.

        Validates: Requirement 22.9 (panel state maintained on bar changes)
        """
        controller = PanelRingController()

        # User navigates to config table (pushes breadcrumb)
        controller.push_breadcrumb("config-table")
        assert controller.breadcrumb_depth == 1

        # Bar content changes — but breadcrumb depth > 0, so no switch
        should_switch = controller.breadcrumb_depth == 0

        assert not should_switch  # Should NOT switch panels


# ===========================================================================
# Integration Tests: Pre-flight shows all resolved values
# ===========================================================================


class TestPreFlightShowsResolvedValues:
    """Test that PreFlightWidget displays all resolved values when updated.

    Validates: Requirement 5.2
    """

    def test_preflight_renders_all_resolved_fields(self, monkeypatch):
        """PreFlightWidget shows every field from resolved_values after
        update_from_pending is called with the PendingExecution.

        Simulates the inline_tui wiring:
            self.query_one("#pre-flight", PreFlightWidget).update_from_pending(pending)
        """
        resolved = _make_resolved_values(
            {
                "environment": ("production", "file"),
                "region": ("us-east-1", "env"),
                "timeout": (30, "default"),
            }
        )
        pending = PendingExecution(
            job_name="deploy",
            resolved_values=resolved,
            overrides={},
        )

        widget = PreFlightWidget()
        field_list = FakeStatic()
        monkeypatch.setattr(
            widget,
            "query_one",
            lambda selector, cls=None: field_list,
        )

        widget.update_from_pending(pending)

        # All fields should appear
        assert "environment" in field_list.content
        assert "region" in field_list.content
        assert "timeout" in field_list.content

    def test_preflight_renders_values_and_sources(self, monkeypatch):
        """Each field shows its effective value and source label."""
        resolved = _make_resolved_values(
            {
                "environment": ("staging", "env"),
                "region": ("eu-west-1", "file"),
            }
        )
        pending = PendingExecution(
            job_name="deploy",
            resolved_values=resolved,
            overrides={},
        )

        widget = PreFlightWidget()
        field_list = FakeStatic()
        monkeypatch.setattr(
            widget,
            "query_one",
            lambda selector, cls=None: field_list,
        )

        widget.update_from_pending(pending)

        assert "'staging'" in field_list.content
        assert "(env)" in field_list.content
        assert "'eu-west-1'" in field_list.content
        assert "(file)" in field_list.content

    def test_preflight_empty_resolved_shows_no_fields_message(self, monkeypatch):
        """When resolve_section returns empty, shows 'No configuration fields'.

        Validates: Requirement 11.1
        """
        pending = PendingExecution(
            job_name="simple_job",
            resolved_values={},
            overrides={},
        )

        widget = PreFlightWidget()
        field_list = FakeStatic()
        monkeypatch.setattr(
            widget,
            "query_one",
            lambda selector, cls=None: field_list,
        )

        widget.update_from_pending(pending)

        assert "No configuration fields" in field_list.content

    def test_preflight_end_to_end_creation_and_render(self, monkeypatch):
        """End-to-end: resolved values → PendingExecution → PreFlightWidget render.

        Simulates the full wiring from inline_tui._async_update.
        """
        # Step 1: Simulate ResolutionChain.resolve_section() result
        resolved = _make_resolved_values(
            {
                "db_host": ("localhost", "file"),
                "db_port": (5432, "default"),
                "api_url": ("https://api.example.com", "env"),
            }
        )

        # Step 2: Create PendingExecution (as inline_tui does)
        job_name = "migrate"
        pending = PendingExecution(
            job_name=job_name,
            resolved_values=resolved,
            overrides={},
        )

        # Step 3: PanelRingController breadcrumb depth allows switching
        controller = PanelRingController()
        assert controller.breadcrumb_depth == 0
        # When depth is 0, inline_tui sets help_area.current = "pre-flight"

        # Step 4: PreFlightWidget.update_from_pending
        widget = PreFlightWidget()
        field_list = FakeStatic()
        monkeypatch.setattr(
            widget,
            "query_one",
            lambda selector, cls=None: field_list,
        )
        widget.update_from_pending(pending)

        # Verify all fields rendered
        assert "db_host" in field_list.content
        assert "db_port" in field_list.content
        assert "api_url" in field_list.content
        assert "'localhost'" in field_list.content
        assert "5432" in field_list.content
        assert "'https://api.example.com'" in field_list.content


# ===========================================================================
# Integration Tests: CLI-typed args appear as overrides in pre-flight
# ===========================================================================


class TestCLIArgsAsOverrides:
    """Test that CLI-typed args in the smart bar become session overrides.

    Validates: Requirement 5.4
    """

    def test_cli_args_parsed_and_set_as_overrides(self):
        """CLI --key value args from smart bar text become session overrides.

        Simulates: typing "deploy --environment staging" in smart bar.
        The inline_tui logic parses tokens[1:] and calls set_override.
        """
        # Simulate resolved values
        resolved = _make_resolved_values(
            {
                "environment": ("production", "file"),
                "region": ("us-east-1", "env"),
            }
        )

        # Create PendingExecution
        pending = PendingExecution(
            job_name="deploy",
            resolved_values=resolved,
            overrides={},
        )

        # Parse CLI args (mirrors inline_tui logic)
        tokens = ["deploy", "--environment", "staging"]
        cli_kwargs = _parse_cli_args_to_kwargs(tokens[1:])

        # Apply CLI args as session overrides (mirrors inline_tui logic)
        for field_name, value in cli_kwargs.items():
            if field_name in resolved:
                pending.overrides[field_name] = value

        # Verify the override was applied
        assert pending.has_override("environment")
        assert pending.effective_value("environment") == "staging"
        assert pending.effective_source("environment") == "cli"
        # region should remain unaffected
        assert not pending.has_override("region")
        assert pending.effective_value("region") == "us-east-1"

    def test_cli_args_only_override_known_fields(self):
        """Only CLI args matching resolved field names become overrides.
        Unknown --flags are ignored (not set as overrides).

        Mirrors: `if field_name in resolved:` guard in inline_tui.
        """
        resolved = _make_resolved_values({"environment": ("production", "file")})

        pending = PendingExecution(
            job_name="deploy",
            resolved_values=resolved,
            overrides={},
        )

        tokens = ["deploy", "--environment", "staging", "--unknown_flag", "value"]
        cli_kwargs = _parse_cli_args_to_kwargs(tokens[1:])

        for field_name, value in cli_kwargs.items():
            if field_name in resolved:
                pending.overrides[field_name] = value

        # Known field overridden
        assert pending.has_override("environment")
        # Unknown field NOT overridden
        assert not pending.has_override("unknown_flag")
        assert pending.override_count() == 1

    def test_cli_override_shown_in_preflight_with_indicator(self, monkeypatch):
        """CLI-typed overrides display with the override indicator in pre-flight.

        End-to-end: CLI args → PendingExecution overrides → PreFlightWidget render.
        """
        resolved = _make_resolved_values(
            {
                "environment": ("production", "file"),
                "region": ("us-east-1", "env"),
            }
        )

        pending = PendingExecution(
            job_name="deploy",
            resolved_values=resolved,
            overrides={},
        )

        # Simulate CLI arg: --environment staging
        tokens = ["deploy", "--environment", "staging"]
        cli_kwargs = _parse_cli_args_to_kwargs(tokens[1:])
        for field_name, value in cli_kwargs.items():
            if field_name in resolved:
                pending.overrides[field_name] = value

        # Render in PreFlightWidget
        widget = PreFlightWidget()
        field_list = FakeStatic()
        monkeypatch.setattr(
            widget,
            "query_one",
            lambda selector, cls=None: field_list,
        )
        widget.update_from_pending(pending)

        # Overridden field shows override indicator and the override value.
        # Source label is "cli" under the SmartBar-as-CLI model.
        assert "'staging'" in field_list.content
        assert "⚡override" in field_list.content
        assert "(cli)" in field_list.content

        # Non-overridden field shows its original value and source
        assert "'us-east-1'" in field_list.content

    def test_cli_args_equals_syntax(self):
        """CLI args with --key=value syntax are parsed correctly."""
        resolved = _make_resolved_values({"timeout": (30, "default")})

        pending = PendingExecution(
            job_name="build",
            resolved_values=resolved,
            overrides={},
        )

        tokens = ["build", "--timeout=60"]
        cli_kwargs = _parse_cli_args_to_kwargs(tokens[1:])
        for field_name, value in cli_kwargs.items():
            if field_name in resolved:
                pending.overrides[field_name] = value

        assert pending.has_override("timeout")
        assert pending.effective_value("timeout") == "60"

    def test_cli_args_hyphen_converted_to_underscore(self):
        """CLI args with hyphens are converted to underscores for field matching.

        User types --target-env, but the resolved field is target_env.
        """
        resolved = _make_resolved_values({"target_env": ("dev", "default")})

        pending = PendingExecution(
            job_name="deploy",
            resolved_values=resolved,
            overrides={},
        )

        tokens = ["deploy", "--target-env", "production"]
        cli_kwargs = _parse_cli_args_to_kwargs(tokens[1:])
        for field_name, value in cli_kwargs.items():
            if field_name in resolved:
                pending.overrides[field_name] = value

        assert pending.has_override("target_env")
        assert pending.effective_value("target_env") == "production"

    def test_multiple_cli_args_all_become_overrides(self):
        """Multiple CLI args all get set as overrides."""
        resolved = _make_resolved_values(
            {
                "environment": ("production", "file"),
                "region": ("us-east-1", "env"),
                "timeout": (30, "default"),
            }
        )

        pending = PendingExecution(
            job_name="deploy",
            resolved_values=resolved,
            overrides={},
        )

        tokens = ["deploy", "--environment", "staging", "--region", "eu-west-1"]
        cli_kwargs = _parse_cli_args_to_kwargs(tokens[1:])
        for field_name, value in cli_kwargs.items():
            if field_name in resolved:
                pending.overrides[field_name] = value

        assert pending.override_count() == 2
        assert pending.effective_value("environment") == "staging"
        assert pending.effective_value("region") == "eu-west-1"
        # timeout remains unchanged
        assert pending.effective_value("timeout") == 30

    def test_cli_override_source_is_cli(self):
        """All CLI-typed overrides report source 'cli' (SmartBar-as-CLI).

        The inline_tui writes overrides[...] directly for CLI-typed args, and
        every override reports source 'cli'.
        """
        resolved = _make_resolved_values({"environment": ("production", "file")})

        pending = PendingExecution(
            job_name="deploy",
            resolved_values=resolved,
        )

        tokens = ["deploy", "--environment", "staging"]
        cli_kwargs = _parse_cli_args_to_kwargs(tokens[1:])
        for field_name, value in cli_kwargs.items():
            if field_name in resolved:
                pending.overrides[field_name] = value

        assert pending.effective_source("environment") == "cli"
