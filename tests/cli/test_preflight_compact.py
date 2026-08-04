"""Tests for compact single-line pre-flight summary rendering.

Verifies:
- Single-line-per-field format (R2-AC1, R2-AC6)
- Kind label [arg] for positional plain params (R2-AC2)
- Source label omission for empty plain params (R2-AC3)
- Source label "cli"/"default" for plain params with values (R2-AC4)
- Description truncation with ellipsis (R2-AC5)
- CSS max-height change (R2-AC7)
- No docstring body, no type detail lines, no history lines (R2-AC6)

Requirements: R2-AC1, R2-AC2, R2-AC3, R2-AC4, R2-AC5, R2-AC6, R2-AC7
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from functualize._cli.tui.app import FunctualizeInlineTUI
from functualize._cli.tui.bar import BarReadiness
from functualize._cli.tui.panels.config_table import ParamKind
from functualize._cli.tui.preflight_summary import format_preflight_field_line

# =============================================================================
# Helpers
# =============================================================================


def _make_field_descriptor(
    name: str,
    *,
    required: bool = False,
    default: Any = None,
    positional: bool = False,
    short_flag: str | None = None,
    type_annotation: str = "str",
    description: str = "",
    choices: list[str] | None = None,
    param_kind: ParamKind = ParamKind.CONFIG,
) -> SimpleNamespace:
    """Create a mock field descriptor."""
    return SimpleNamespace(
        name=name,
        required=required,
        default=default,
        positional=positional,
        short_flag=short_flag,
        type_annotation=type_annotation,
        description=description,
        choices=choices,
        param_kind=param_kind,
    )


def _make_job_descriptor(
    name: str,
    fields: list[SimpleNamespace],
    docstring: str | None = None,
) -> SimpleNamespace:
    """Create a mock JobDescriptor with given fields and docstring."""
    return SimpleNamespace(
        name=name,
        config_fields=fields,
        parameters=fields,
        docstring=docstring,
        group=None,
        source_path=None,
    )


def _make_func_app(jobs: list[SimpleNamespace]) -> MagicMock:
    """Create a mock FunctualizeApp."""
    app = MagicMock()
    app.name = "test-app"
    app.get_jobs.return_value = jobs
    app.get_job.side_effect = lambda name: next(
        (j for j in jobs if j.name == name), None
    )
    return app


class _FakeRichLog:
    """Fake RichLog that captures write() calls for assertions."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.cleared: bool = False

    def clear(self) -> None:
        self.lines = []
        self.cleared = True

    def write(self, content: str) -> None:
        self.lines.append(content)


class _FakeSize:
    """Fake size object for terminal width."""

    def __init__(self, width: int = 80) -> None:
        self.width = width


def _create_tui_and_render(
    job_name: str,
    fields: list[SimpleNamespace],
    docstring: str | None = None,
    smartbar_value: str | None = None,
    terminal_width: int = 80,
    readiness: BarReadiness = BarReadiness.READY,
) -> _FakeRichLog:
    """Create a TUI instance, set up mocks, and call _render_preflight_summary.

    Returns the FakeRichLog with captured output lines.
    """
    job = _make_job_descriptor(job_name, fields, docstring=docstring)
    func_app = _make_func_app([job])

    with patch.object(FunctualizeInlineTUI, "__init__", lambda self, *a, **kw: None):
        tui = FunctualizeInlineTUI.__new__(FunctualizeInlineTUI)
        tui._func_app = func_app
        tui._smart_bar = MagicMock()
        tui._smart_bar.value = smartbar_value or f"{job_name} "
        tui._smart_bar.readiness = readiness

    log = _FakeRichLog()

    with patch.object(
        type(tui),
        "size",
        new_callable=lambda: property(lambda self: _FakeSize(terminal_width)),
    ):
        tui._render_preflight_summary(log)

    return log


# =============================================================================
# Tests
# =============================================================================


class TestSingleLineFormat:
    """R2-AC1, R2-AC6: Each field renders on a single line; no detail lines."""

    def test_field_renders_on_single_line(self) -> None:
        """A field with all metadata renders on exactly one line."""
        fields = [
            _make_field_descriptor(
                "region",
                default="us-east-1",
                description="Cloud region",
                param_kind=ParamKind.CONFIG,
            )
        ]
        log = _create_tui_and_render("deploy", fields, docstring="Deploy job")
        # Line 0: header, line 1: the field
        field_lines = [ln for ln in log.lines[1:] if "region" in ln]
        assert len(field_lines) == 1
        # The single line should contain type and description inline
        assert "str" in field_lines[0]
        assert "Cloud region" in field_lines[0]

    def test_no_type_detail_line(self) -> None:
        """No separate type/choices detail line below the field (R2-AC6)."""
        fields = [
            _make_field_descriptor(
                "env",
                choices=["dev", "staging", "prod"],
                default="dev",
                description="Environment",
                param_kind=ParamKind.CONFIG,
            )
        ]
        log = _create_tui_and_render("deploy", fields, docstring="Deploy job")
        # Should not have standalone type line
        type_only_lines = [
            ln for ln in log.lines if ln.strip().startswith("str") and "env" not in ln
        ]
        assert len(type_only_lines) == 0

    def test_no_history_line(self) -> None:
        """No history line below the field (R2-AC6)."""
        fields = [_make_field_descriptor("port", default=8080)]
        log = _create_tui_and_render("serve", fields, docstring="Serve")
        history_lines = [ln for ln in log.lines if "history:" in ln]
        assert len(history_lines) == 0

    def test_no_docstring_body(self) -> None:
        """Full docstring body is NOT rendered (R2-AC6)."""
        fields = [_make_field_descriptor("port", default=8080)]
        log = _create_tui_and_render(
            "serve",
            fields,
            docstring="Start the server\n\nMore details here.\nAnd more.",
        )
        all_text = "\n".join(log.lines)
        assert "More details here." not in all_text
        assert "And more." not in all_text

    def test_job_header_kept(self) -> None:
        """Job header line is still present (bold: job_name — first_line)."""
        fields = [_make_field_descriptor("port", default=8080)]
        log = _create_tui_and_render(
            "serve", fields, docstring="Start the development server"
        )
        header = log.lines[0]
        assert "[bold]" in header
        assert "serve" in header
        assert "Start the development server" in header
        assert "—" in header


class TestKindLabel:
    """R2-AC2: Kind label [arg] for positional plain params, empty otherwise."""

    def test_positional_plain_param_shows_arg_label(self) -> None:
        """Positional plain param shows [arg] label."""
        fields = [
            _make_field_descriptor(
                "target",
                positional=True,
                required=True,
                param_kind=ParamKind.PLAIN,
            )
        ]
        log = _create_tui_and_render("deploy", fields, docstring="Deploy job")
        field_line = next(ln for ln in log.lines if "target" in ln)
        assert "[arg]" in field_line

    def test_named_plain_param_no_arg_label(self) -> None:
        """Named (non-positional) plain param does NOT show [arg]."""
        fields = [
            _make_field_descriptor(
                "verbose",
                default="false",
                param_kind=ParamKind.PLAIN,
            )
        ]
        log = _create_tui_and_render("build", fields, docstring="Build job")
        field_line = next(ln for ln in log.lines if "verbose" in ln)
        assert "[arg]" not in field_line

    def test_config_param_no_arg_label(self) -> None:
        """Config param does NOT show [arg] even if positional."""
        fields = [
            _make_field_descriptor(
                "region",
                positional=True,
                default="us-east-1",
                param_kind=ParamKind.CONFIG,
            )
        ]
        log = _create_tui_and_render("deploy", fields, docstring="Deploy job")
        field_line = next(ln for ln in log.lines if "region" in ln)
        assert "[arg]" not in field_line


class TestSourceLabel:
    """R2-AC3, R2-AC4: Source label rules for plain params."""

    def test_empty_plain_param_omits_source(self) -> None:
        """Plain param with no value omits source label entirely (R2-AC3)."""
        fields = [
            _make_field_descriptor(
                "target",
                required=True,
                positional=True,
                param_kind=ParamKind.PLAIN,
            )
        ]
        log = _create_tui_and_render("deploy", fields, docstring="Deploy")
        field_line = next(ln for ln in log.lines if "target" in ln)
        # No parenthesized source
        assert "(cli)" not in field_line
        assert "(default)" not in field_line

    def test_plain_param_with_cli_value_shows_cli_source(self) -> None:
        """Plain param with CLI-provided value shows (cli) source (R2-AC4)."""
        fields = [
            _make_field_descriptor(
                "target",
                required=True,
                positional=True,
                param_kind=ParamKind.PLAIN,
            )
        ]
        log = _create_tui_and_render(
            "deploy", fields, docstring="Deploy", smartbar_value="deploy prod"
        )
        field_line = next(ln for ln in log.lines if "target" in ln)
        assert "(cli)" in field_line
        assert "prod" in field_line

    def test_plain_param_with_default_shows_default_source(self) -> None:
        """Plain param with default value shows (default) source (R2-AC4)."""
        fields = [
            _make_field_descriptor(
                "verbose",
                default="false",
                param_kind=ParamKind.PLAIN,
            )
        ]
        log = _create_tui_and_render("build", fields, docstring="Build")
        field_line = next(ln for ln in log.lines if "verbose" in ln)
        assert "(default)" in field_line
        assert "false" in field_line

    def test_config_param_with_value_shows_source(self) -> None:
        """Config param with value shows appropriate source."""
        fields = [
            _make_field_descriptor(
                "region",
                default="us-east-1",
                param_kind=ParamKind.CONFIG,
            )
        ]
        log = _create_tui_and_render("deploy", fields, docstring="Deploy")
        field_line = next(ln for ln in log.lines if "region" in ln)
        assert "(default)" in field_line


class TestDescriptionTruncation:
    """R2-AC5: Description truncated with ellipsis if line exceeds terminal width."""

    def test_short_description_not_truncated(self) -> None:
        """Description that fits within width is not truncated."""
        fields = [
            _make_field_descriptor(
                "port",
                default=8080,
                description="Port",
                type_annotation="int",
            )
        ]
        log = _create_tui_and_render(
            "serve", fields, docstring="Serve", terminal_width=80
        )
        field_line = next(ln for ln in log.lines if "port" in ln)
        assert "Port" in field_line
        assert "…" not in field_line

    def test_long_description_truncated_with_ellipsis(self) -> None:
        """Description that exceeds width is truncated with … (R2-AC5)."""
        long_desc = "A very long description that should be truncated " * 3
        fields = [
            _make_field_descriptor(
                "port",
                default=8080,
                description=long_desc,
                type_annotation="int",
            )
        ]
        log = _create_tui_and_render(
            "serve", fields, docstring="Serve", terminal_width=60
        )
        field_line = next(ln for ln in log.lines if "port" in ln)
        assert "…" in field_line
        # The line's plain-text content (ignoring markup) should not exceed width
        # (We just verify truncation happened — exact length depends on markup handling)

    def test_truncation_uses_terminal_width(self) -> None:
        """Truncation respects the provided terminal width."""
        desc = "X" * 200
        fields = [_make_field_descriptor("f", default="v", description=desc)]
        log_narrow = _create_tui_and_render(
            "j", fields, docstring="J", terminal_width=40
        )
        log_wide = _create_tui_and_render(
            "j", fields, docstring="J", terminal_width=300
        )

        narrow_line = next(ln for ln in log_narrow.lines if "f" in ln and "X" in ln)
        wide_line = next(ln for ln in log_wide.lines if "f" in ln and "X" in ln)

        assert "…" in narrow_line
        assert "…" not in wide_line


class TestFieldIndicators:
    """Verify indicators are correct in compact format."""

    def test_filled_indicator(self) -> None:
        """Field with value shows ● indicator."""
        fields = [_make_field_descriptor("port", default=8080)]
        log = _create_tui_and_render("serve", fields, docstring="Serve")
        field_line = next(ln for ln in log.lines if "port" in ln)
        assert "●" in field_line

    def test_required_empty_indicator(self) -> None:
        """Required empty field shows ○ indicator."""
        fields = [_make_field_descriptor("env", required=True)]
        log = _create_tui_and_render("deploy", fields, docstring="Deploy")
        field_line = next(ln for ln in log.lines if "env" in ln)
        assert "○" in field_line

    def test_optional_empty_indicator(self) -> None:
        """Optional empty field shows · indicator."""
        fields = [_make_field_descriptor("verbose")]
        log = _create_tui_and_render("build", fields, docstring="Build")
        field_line = next(ln for ln in log.lines if "verbose" in ln)
        assert "·" in field_line


class TestShortFlag:
    """Verify short flag display in compact format."""

    def test_short_flag_shown_inline(self) -> None:
        """Short flag appears as /x after name."""
        fields = [_make_field_descriptor("port", short_flag="p", default=8080)]
        log = _create_tui_and_render("serve", fields, docstring="Serve")
        field_line = next(ln for ln in log.lines if "port" in ln)
        assert "/p" in field_line


class TestCSSMaxHeight:
    """R2-AC7: max-height CSS for #preflight-summary is 12."""

    def test_css_max_height_is_12(self) -> None:
        """The DEFAULT_CSS contains max-height: 12 for #preflight-summary."""
        css = FunctualizeInlineTUI.DEFAULT_CSS
        assert "max-height: 12" in css
        # Verify it's for #preflight-summary context
        # Find the block
        idx = css.find("#preflight-summary")
        assert idx != -1
        block_end = css.find("}", idx)
        block = css[idx:block_end]
        assert "max-height: 12" in block


class TestFormatPreflightFieldLine:
    """Direct tests for the format_preflight_field_line helper."""

    def test_basic_format(self) -> None:
        """Basic field produces expected format."""
        fd = _make_field_descriptor(
            "region",
            default="us-east-1",
            description="Cloud region",
            type_annotation="str",
            param_kind=ParamKind.CONFIG,
        )
        line = format_preflight_field_line(fd, {}, avail_width=80)
        assert "●" in line
        assert "region" in line
        assert "us-east-1" in line
        assert "(default)" in line
        assert "str" in line
        assert "Cloud region" in line

    def test_positional_plain_with_cli_value(self) -> None:
        """Positional plain param with CLI value shows [arg] and (cli)."""
        fd = _make_field_descriptor(
            "target",
            required=True,
            positional=True,
            description="Deploy target",
            param_kind=ParamKind.PLAIN,
        )
        line = format_preflight_field_line(fd, {"target": "prod"}, avail_width=80)
        assert "[arg]" in line
        assert "prod" in line
        assert "(cli)" in line
        assert "●" in line

    def test_empty_required_plain_no_source(self) -> None:
        """Empty required plain param has no source label."""
        fd = _make_field_descriptor(
            "target",
            required=True,
            positional=True,
            param_kind=ParamKind.PLAIN,
        )
        line = format_preflight_field_line(fd, {}, avail_width=80)
        assert "○" in line
        assert "*" in line
        assert "(cli)" not in line
        assert "(default)" not in line


class TestCtrlSHint:
    """Requirement 4: Ctrl+S discoverability hint in the pre-flight summary."""

    def test_hint_shown_when_ready(self) -> None:
        """A READY job with fields shows the Ctrl+S hint as the last line."""
        fields = [_make_field_descriptor("port", default=8080)]
        log = _create_tui_and_render(
            "serve", fields, docstring="Serve", readiness=BarReadiness.READY
        )
        assert any("Ctrl+S save as shortcut" in ln for ln in log.lines)
        assert "Ctrl+S save as shortcut" in log.lines[-1]

    def test_hint_not_shown_when_pending(self) -> None:
        """A PENDING job (fields still incomplete) does not show the hint."""
        fields = [_make_field_descriptor("port", required=True)]
        log = _create_tui_and_render(
            "serve", fields, docstring="Serve", readiness=BarReadiness.PENDING
        )
        assert not any("Ctrl+S save as shortcut" in ln for ln in log.lines)

    def test_hint_not_shown_when_grey(self) -> None:
        """A GREY (unrecognized job) state shows nothing, including no hint."""
        fields = [_make_field_descriptor("port", default=8080)]
        log = _create_tui_and_render(
            "serve", fields, docstring="Serve", readiness=BarReadiness.GREY
        )
        assert not any("Ctrl+S save as shortcut" in ln for ln in log.lines)

    def test_hint_shown_for_zero_field_job_when_ready(self) -> None:
        """A bare/zero-fields job (e.g. healthcheck) still shows header + hint
        when READY, even though the field-table early-return would otherwise
        skip rendering entirely."""
        log = _create_tui_and_render(
            "healthcheck",
            [],
            docstring="Check service health",
            readiness=BarReadiness.READY,
        )
        assert any("healthcheck" in ln for ln in log.lines)
        assert any("Ctrl+S save as shortcut" in ln for ln in log.lines)

    def test_no_hint_for_zero_field_job_when_pending(self) -> None:
        """A zero-fields job that isn't READY renders nothing (unchanged
        behavior — the early return still applies when not READY)."""
        log = _create_tui_and_render(
            "healthcheck",
            [],
            docstring="Check service health",
            readiness=BarReadiness.PENDING,
        )
        assert log.lines == []


class TestResolvedSourceForUnfilledConfigParam:
    """unfilled config params show real resolved source_type."""

    def test_unfilled_config_param_shows_resolved_env_source(self) -> None:
        """Config param with no SmartBar value shows the resolved env source."""
        fd = _make_field_descriptor(
            "region",
            default="us-east-1",
            param_kind=ParamKind.CONFIG,
        )
        line = format_preflight_field_line(
            fd, {}, avail_width=80, resolved_source="env"
        )
        assert "(env)" in line
        assert "(default)" not in line

    def test_unfilled_config_param_shows_resolved_file_source(self) -> None:
        """Config param resolved from file shows (file), not a blind default."""
        fd = _make_field_descriptor(
            "region",
            param_kind=ParamKind.CONFIG,
        )
        line = format_preflight_field_line(
            fd, {}, avail_width=80, resolved_source="file"
        )
        assert "(file)" in line

    def test_cli_value_overrides_resolved_source(self) -> None:
        """A CLI value still wins over the resolved source."""
        fd = _make_field_descriptor("region", param_kind=ParamKind.CONFIG)
        line = format_preflight_field_line(
            fd, {"region": "eu-west-1"}, avail_width=80, resolved_source="file"
        )
        assert "(cli)" in line
        assert "(file)" not in line

    def test_no_resolved_source_falls_back_to_default(self) -> None:
        """Without a resolved source, behaviour is unchanged (default fallback)."""
        fd = _make_field_descriptor(
            "region",
            default="us-east-1",
            param_kind=ParamKind.CONFIG,
        )
        line = format_preflight_field_line(fd, {}, avail_width=80)
        assert "(default)" in line

    def test_render_summary_threads_resolved_source_from_pending(self) -> None:
        """_render_preflight_summary passes the pending resolved source_type."""
        from functualize._cli.data.pending_execution import PendingExecution
        from functualize._cli.data.resolved_value_compat import ResolvedValueCompat

        fields = [
            _make_field_descriptor(
                "region", default="us-east-1", param_kind=ParamKind.CONFIG
            )
        ]
        job = _make_job_descriptor("deploy", fields, docstring="Deploy job")
        func_app = _make_func_app([job])

        with patch.object(
            FunctualizeInlineTUI, "__init__", lambda self, *a, **kw: None
        ):
            tui = FunctualizeInlineTUI.__new__(FunctualizeInlineTUI)
            tui._func_app = func_app
            tui._smart_bar = MagicMock()
            tui._smart_bar.value = "deploy "
            tui._pending = PendingExecution(
                job_name="deploy",
                resolved_values={
                    "region": ResolvedValueCompat(value="us-east-1", source_type="env")
                },
            )

        log = _FakeRichLog()
        with patch.object(
            type(tui),
            "size",
            new_callable=lambda: property(lambda self: _FakeSize(80)),
        ):
            tui._render_preflight_summary(log)

        field_line = next(ln for ln in log.lines if "region" in ln)
        assert "(env)" in field_line
