"""Tests for the `func domains list` CLI command.

Validates Requirement 22.6: The system SHALL provide a `func domains list` CLI
command that displays all discovered domains with their display names, installed
implementation providers, and the currently active provider.
"""

from __future__ import annotations

from importlib.metadata import EntryPoint
from unittest.mock import patch

import click
from click.testing import CliRunner

from functualize._plugins.domain_metadata import DomainMetadata


def _make_metadata(
    name: str = "ai",
    display_name: str = "AI / LLM",
    description: str = "LLM interaction capabilities",
    capability_class: str = "functualize_ai.AI",
    provider_protocol: str = "functualize_ai.AIProvider",
    config_section: str = "ai",
    entry_point_group: str = "functualize.ai_providers",
    events_prefix: str = "ai.",
) -> DomainMetadata:
    return DomainMetadata(
        name=name,
        display_name=display_name,
        description=description,
        capability_class=capability_class,
        provider_protocol=provider_protocol,
        config_section=config_section,
        entry_point_group=entry_point_group,
        events_prefix=events_prefix,
    )


def _create_app_with_domains() -> click.Group:
    """Create a Typer app with domains commands registered."""
    from functualize._cli.builtins import register_builtin_commands

    app = click.Group(name="func")
    register_builtin_commands(app)
    return app


runner = CliRunner()


class TestDomainsListCommand:
    """Tests for `func domains list` command."""

    def test_no_domains_discovered(self) -> None:
        """When no domains are discovered, shows install instructions."""
        app = _create_app_with_domains()

        with patch(
            "functualize.plugin.discover_domains",
            return_value=[],
        ):
            result = runner.invoke(app, ["builtin", "domains", "list"])

        assert result.exit_code == 0
        assert "No domains discovered" in result.output
        assert "pip install functualize-state" in result.output
        assert "pip install functualize-ai" in result.output

    def test_domains_listed_with_display_names(self) -> None:
        """Discovered domains are listed with display names."""
        ai_meta = _make_metadata(name="ai", display_name="AI / LLM")
        state_meta = _make_metadata(
            name="state",
            display_name="State / Persistence",
            config_section="state",
            entry_point_group="functualize.state_providers",
            events_prefix="state.",
        )

        app = _create_app_with_domains()

        with (
            patch(
                "functualize.plugin.discover_domains",
                return_value=[ai_meta, state_meta],
            ),
            patch(
                "functualize.plugin.scan_domain_providers",
                return_value={},
            ),
        ):
            result = runner.invoke(app, ["builtin", "domains", "list"])

        assert result.exit_code == 0
        assert "AI / LLM (ai)" in result.output
        assert "State / Persistence (state)" in result.output

    def test_domains_with_single_provider_marked_active(self) -> None:
        """A single installed provider is marked as active."""
        ai_meta = _make_metadata(name="ai", display_name="AI / LLM")

        mock_ep = EntryPoint(
            name="pydantic",
            value="functualize_ai_pydantic:PydanticAIPlugin",
            group="functualize.ai_providers",
        )

        app = _create_app_with_domains()

        with (
            patch(
                "functualize.plugin.discover_domains",
                return_value=[ai_meta],
            ),
            patch(
                "functualize.plugin.scan_domain_providers",
                return_value={"pydantic": mock_ep},
            ),
        ):
            result = runner.invoke(app, ["builtin", "domains", "list"])

        assert result.exit_code == 0
        assert "pydantic (active)" in result.output

    def test_domains_with_multiple_providers(self) -> None:
        """Multiple providers are listed without active marker."""
        ai_meta = _make_metadata(name="ai", display_name="AI / LLM")

        mock_ep1 = EntryPoint(
            name="pydantic",
            value="functualize_ai_pydantic:PydanticAIPlugin",
            group="functualize.ai_providers",
        )
        mock_ep2 = EntryPoint(
            name="instructor",
            value="functualize_ai_instructor:InstructorPlugin",
            group="functualize.ai_providers",
        )

        app = _create_app_with_domains()

        with (
            patch(
                "functualize.plugin.discover_domains",
                return_value=[ai_meta],
            ),
            patch(
                "functualize.plugin.scan_domain_providers",
                return_value={"pydantic": mock_ep1, "instructor": mock_ep2},
            ),
        ):
            result = runner.invoke(app, ["builtin", "domains", "list"])

        assert result.exit_code == 0
        assert "instructor" in result.output
        assert "pydantic" in result.output
        # Neither should be marked active when multiple providers exist
        assert "(active)" not in result.output
        # Installed-but-unwired signpost tells the user how to activate one.
        assert "Not wired" in result.output
        assert 'provider = "<name>"' in result.output
        assert "[ai]" in result.output

    def test_domains_with_no_providers_installed(self) -> None:
        """Domains with no providers show '(none installed)'."""
        tasks_meta = _make_metadata(
            name="tasks",
            display_name="Tasks",
            config_section="tasks",
            entry_point_group="functualize.tasks_providers",
            events_prefix="tasks.",
        )

        app = _create_app_with_domains()

        with (
            patch(
                "functualize.plugin.discover_domains",
                return_value=[tasks_meta],
            ),
            patch(
                "functualize.plugin.scan_domain_providers",
                return_value={},
            ),
        ):
            result = runner.invoke(app, ["builtin", "domains", "list"])

        assert result.exit_code == 0
        assert "(none installed)" in result.output

    def test_domains_sorted_alphabetically(self) -> None:
        """Domains are displayed sorted by name."""
        tasks_meta = _make_metadata(
            name="tasks",
            display_name="Tasks",
            config_section="tasks",
            entry_point_group="functualize.tasks_providers",
            events_prefix="tasks.",
        )
        ai_meta = _make_metadata(name="ai", display_name="AI / LLM")

        app = _create_app_with_domains()

        # Pass in reverse order
        with (
            patch(
                "functualize.plugin.discover_domains",
                return_value=[tasks_meta, ai_meta],
            ),
            patch(
                "functualize.plugin.scan_domain_providers",
                return_value={},
            ),
        ):
            result = runner.invoke(app, ["builtin", "domains", "list"])

        assert result.exit_code == 0
        # AI should appear before Tasks in the output
        ai_pos = result.output.index("AI / LLM")
        tasks_pos = result.output.index("Tasks")
        assert ai_pos < tasks_pos
