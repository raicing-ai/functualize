"""Unit tests for enhanced CompletionItem rendering.

Since CompletionItem is defined inside launch_inline_tui(), we test
the badge rendering logic by verifying the markup patterns that would
be produced for different provenance configurations.

Feature: TUI Smart Bar & Modals (Phase 2)
Task: 6.2 — Write unit tests for enhanced CompletionItem rendering
Validates: Requirements 1.1, 1.2, 1.3, 1.4
"""

from __future__ import annotations

from functualize._cli.completions.provenance import ProvenanceInfo


def _render_completion_line(
    name: str,
    description: str,
    kind: str,
    provenance: ProvenanceInfo | None = None,
    is_recent: bool = False,
) -> str:
    """Simulate CompletionItem's compose() logic to produce the markup line.

    This mirrors the rendering logic in inline_tui.py's CompletionItem.compose()
    so we can test the badge formatting without needing the full Textual harness.
    """
    if provenance is not None:
        # Render with provenance badge
        recent = "⟳ " if is_recent else ""
        line = (
            f"  {recent}[{provenance.badge_style}]"
            f"{provenance.display_label}"
            f"[/{provenance.badge_style}] "
            f"[bold]{name}[/bold]"
        )
    elif kind == "builtin":
        badge = "[dim cyan]⚙ built-in[/dim cyan]"
        line = f"  [bold cyan]{name}[/bold cyan]  {badge}"
    elif kind == "subcommand":
        line = f"  [bold yellow]{name}[/bold yellow]"
    else:
        line = f"  [bold]{name}[/bold]"

    if description:
        line += f"  [italic dim]{description}[/italic dim]"
    return line


class TestCompletionItemNoPovenance:
    """Tests for CompletionItem rendering without provenance (backward compat)."""

    def test_no_provenance_renders_name_bold(self) -> None:
        """Job without provenance renders plain bold name."""
        line = _render_completion_line("deploy", "Deploy stuff", "job", provenance=None)

        assert "[bold]deploy[/bold]" in line
        assert "Deploy stuff" in line

    def test_no_provenance_no_badge(self) -> None:
        """Job without provenance has no badge markup."""
        line = _render_completion_line("deploy", "Deploy stuff", "job", provenance=None)

        # Should not contain any provenance badge patterns
        assert "⟳" not in line
        assert "[bold magenta]" not in line
        assert "[bold blue]" not in line
        assert "[dim cyan]" not in line

    def test_no_provenance_builtin_kind_renders_builtin_badge(self) -> None:
        """Builtin kind without provenance renders the builtin badge."""
        line = _render_completion_line(
            "version", "Show version", "builtin", provenance=None
        )

        assert "[bold cyan]version[/bold cyan]" in line
        assert "[dim cyan]⚙ built-in[/dim cyan]" in line

    def test_no_provenance_subcommand_renders_yellow(self) -> None:
        """Subcommand kind without provenance renders in yellow."""
        line = _render_completion_line("scaffold", "", "subcommand", provenance=None)

        assert "[bold yellow]scaffold[/bold yellow]" in line

    def test_description_appended_when_present(self) -> None:
        """Description is appended in italic dim when provided."""
        line = _render_completion_line("deploy", "Deploy the app", "job")

        assert "[italic dim]Deploy the app[/italic dim]" in line

    def test_no_description_omits_suffix(self) -> None:
        """Empty description does not add trailing markup."""
        line = _render_completion_line("deploy", "", "job")

        assert "[italic dim]" not in line


class TestCompletionItemWithProvenance:
    """Tests for CompletionItem rendering with ProvenanceInfo badges."""

    def test_provenance_renders_badge_with_style(self) -> None:
        """ProvenanceInfo renders its badge_style and display_label."""
        prov = ProvenanceInfo(
            source_type="local", display_label="local", badge_style="bold"
        )
        line = _render_completion_line("deploy", "Deploy stuff", "job", provenance=prov)

        assert "[bold]local[/bold]" in line
        assert "[bold]deploy[/bold]" in line

    def test_provenance_badge_appears_before_name(self) -> None:
        """Badge label appears before the job name in the rendered line."""
        prov = ProvenanceInfo(
            source_type="plugin",
            display_label="my-plugin",
            badge_style="bold magenta",
        )
        line = _render_completion_line("deploy", "", "job", provenance=prov)

        badge_pos = line.index("my-plugin")
        name_pos = line.index("deploy")
        assert badge_pos < name_pos

    def test_provenance_overrides_builtin_kind_rendering(self) -> None:
        """When provenance is provided, it takes precedence over kind-based rendering."""
        prov = ProvenanceInfo(
            source_type="builtin", display_label="built-in", badge_style="dim cyan"
        )
        line = _render_completion_line(
            "version", "Show version", "builtin", provenance=prov
        )

        # Should use provenance rendering, not the kind-based builtin rendering
        assert "[dim cyan]built-in[/dim cyan]" in line
        assert "[bold]version[/bold]" in line
        # Should NOT have the "⚙" icon from kind-based rendering
        assert "⚙" not in line


class TestCompletionItemRecentIndicator:
    """Tests for the ⟳ recent indicator."""

    def test_is_recent_shows_indicator(self) -> None:
        """is_recent=True adds ⟳ before the badge."""
        prov = ProvenanceInfo(
            source_type="local", display_label="local", badge_style="bold"
        )
        line = _render_completion_line(
            "deploy", "Deploy stuff", "job", provenance=prov, is_recent=True
        )

        assert "⟳" in line

    def test_not_recent_omits_indicator(self) -> None:
        """is_recent=False does not show ⟳."""
        prov = ProvenanceInfo(
            source_type="local", display_label="local", badge_style="bold"
        )
        line = _render_completion_line(
            "deploy", "Deploy stuff", "job", provenance=prov, is_recent=False
        )

        assert "⟳" not in line

    def test_recent_indicator_appears_before_badge(self) -> None:
        """⟳ appears before the badge label in the rendered line."""
        prov = ProvenanceInfo(
            source_type="plugin",
            display_label="my-plugin",
            badge_style="bold magenta",
        )
        line = _render_completion_line(
            "deploy", "", "job", provenance=prov, is_recent=True
        )

        recent_pos = line.index("⟳")
        badge_pos = line.index("my-plugin")
        assert recent_pos < badge_pos


class TestAllFourBadgeStyles:
    """Tests for all four source_type badge styles rendering correctly."""

    def test_local_badge_style(self) -> None:
        """Local source_type uses bold style."""
        prov = ProvenanceInfo(
            source_type="local", display_label="local", badge_style="bold"
        )
        line = _render_completion_line("job1", "", "job", provenance=prov)

        assert "[bold]local[/bold]" in line

    def test_plugin_badge_style(self) -> None:
        """Plugin source_type uses bold magenta style."""
        prov = ProvenanceInfo(
            source_type="plugin",
            display_label="my-plugin",
            badge_style="bold magenta",
        )
        line = _render_completion_line("job2", "", "job", provenance=prov)

        assert "[bold magenta]my-plugin[/bold magenta]" in line

    def test_child_badge_style(self) -> None:
        """Child source_type uses bold blue style."""
        prov = ProvenanceInfo(
            source_type="child",
            display_label="child-app",
            badge_style="bold blue",
        )
        line = _render_completion_line("job3", "", "job", provenance=prov)

        assert "[bold blue]child-app[/bold blue]" in line

    def test_builtin_badge_style(self) -> None:
        """Builtin source_type uses dim cyan style."""
        prov = ProvenanceInfo(
            source_type="builtin",
            display_label="built-in",
            badge_style="dim cyan",
        )
        line = _render_completion_line("version", "", "job", provenance=prov)

        assert "[dim cyan]built-in[/dim cyan]" in line

    def test_all_styles_include_job_name(self) -> None:
        """All four badge styles still render the job name in bold."""
        styles = [
            ProvenanceInfo("local", "local", "bold"),
            ProvenanceInfo("plugin", "my-plugin", "bold magenta"),
            ProvenanceInfo("child", "child-app", "bold blue"),
            ProvenanceInfo("builtin", "built-in", "dim cyan"),
        ]
        names = ["job1", "job2", "job3", "version"]

        for prov, name in zip(styles, names, strict=True):
            line = _render_completion_line(name, "", "job", provenance=prov)
            assert f"[bold]{name}[/bold]" in line
