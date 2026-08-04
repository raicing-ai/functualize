"""Tests for pre-flight summary truncation cap.

Verifies:
- All plain params (P1+P2) are always shown regardless of cap (R3-AC5)
- Config params (P3-P5) are capped at 8 - len(plain_params) (R3-AC3)
- Truncation indicator line appears when fields exceed cap (R3-AC4)
- No truncation indicator when total fields ≤ 8

Requirements: R3-AC3, R3-AC4, R3-AC5
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from functualize._cli.tui.app import FunctualizeInlineTUI
from functualize._cli.tui.panels.config_table import ParamKind

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

    def __init__(self, width: int = 120) -> None:
        self.width = width


def _create_tui_and_render(
    job_name: str,
    fields: list[SimpleNamespace],
    docstring: str | None = None,
    smartbar_value: str | None = None,
    terminal_width: int = 120,
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


class TestTruncationCapBasic:
    """R3-AC3: Pre-flight summary displays at most 8 fields."""

    def test_no_truncation_when_at_or_below_cap(self) -> None:
        """When total fields ≤ 8, all are shown without truncation indicator."""
        fields = [
            _make_field_descriptor(f"field_{i}", default=f"val{i}") for i in range(8)
        ]
        log = _create_tui_and_render("deploy", fields, docstring="Deploy job")
        # Line 0 is the header, remaining are fields
        field_lines = log.lines[1:]
        # All 8 fields shown, no truncation line
        assert len(field_lines) == 8
        for i in range(8):
            # Options display the hyphenated CLI-flag spelling (field_i → field-i)
            assert any(f"field-{i}" in line for line in field_lines)
        # No truncation indicator
        assert not any("more" in line for line in field_lines)

    def test_truncation_when_above_cap(self) -> None:
        """When total fields > 8, config fields are truncated."""
        fields = [
            _make_field_descriptor(f"cfg_{i}", default=f"val{i}") for i in range(12)
        ]
        log = _create_tui_and_render("deploy", fields, docstring="Deploy job")
        # Header + 8 fields + truncation line = 10 lines
        field_lines = log.lines[1:]  # exclude header
        # Should show 8 config fields + truncation indicator
        assert len(field_lines) == 9  # 8 fields + 1 truncation line
        # Truncation line shows correct count
        assert "+4 more" in field_lines[-1]
        assert "Ctrl+R for all" in field_lines[-1]

    def test_exactly_8_fields_no_truncation(self) -> None:
        """Exactly 8 fields shows all without truncation."""
        fields = [
            _make_field_descriptor(f"param_{i}", default=f"v{i}") for i in range(8)
        ]
        log = _create_tui_and_render("job", fields, docstring="Job")
        field_lines = log.lines[1:]
        assert len(field_lines) == 8
        assert not any("more" in line for line in field_lines)


class TestPlainParamsNeverTruncated:
    """R3-AC5: Priority 1 and 2 fields are always shown, never truncated."""

    def test_all_plain_params_shown_even_when_exceeding_cap(self) -> None:
        """All plain params are shown even if they exceed the cap on their own."""
        # 10 plain params (way above cap=8) — all should still show
        fields = [
            _make_field_descriptor(
                f"plain_{i}",
                default=f"val{i}",
                param_kind=ParamKind.PLAIN,
            )
            for i in range(10)
        ]
        log = _create_tui_and_render("deploy", fields, docstring="Deploy")
        field_lines = log.lines[1:]
        # All 10 plain params shown (they're never truncated)
        for i in range(10):
            assert any(f"plain-{i}" in line for line in field_lines)
        # No truncation indicator (no config params to truncate)
        assert not any("more" in line for line in field_lines)

    def test_plain_params_shown_config_truncated(self) -> None:
        """Plain params always shown; config params truncated to fit cap."""
        # 3 plain params + 10 config params = 13 total
        # Cap = 8, plain = 3, so config cap = 8 - 3 = 5
        plain_fields = [
            _make_field_descriptor(
                f"plain_{i}",
                required=True,
                param_kind=ParamKind.PLAIN,
            )
            for i in range(3)
        ]
        config_fields = [
            _make_field_descriptor(
                f"config_{i}",
                default=f"val{i}",
                param_kind=ParamKind.CONFIG,
            )
            for i in range(10)
        ]
        fields = plain_fields + config_fields
        log = _create_tui_and_render("deploy", fields, docstring="Deploy")
        field_lines = log.lines[1:]

        # All 3 plain params shown
        for i in range(3):
            assert any(f"plain-{i}" in line for line in field_lines)

        # Only first 5 config params shown (cap = 8 - 3 = 5)
        for i in range(5):
            assert any(f"config-{i}" in line for line in field_lines)

        # Remaining 5 config params NOT shown in field lines
        for i in range(5, 10):
            assert not any(f"config-{i}" in line for line in field_lines[:-1])

        # Truncation indicator shows +5
        assert "+5 more" in field_lines[-1]

    def test_positional_plain_params_never_truncated(self) -> None:
        """Positional plain params (P1) are never truncated."""
        # 5 positional plain + 5 config = 10 total
        # Config cap = 8 - 5 = 3
        positional_fields = [
            _make_field_descriptor(
                f"pos_{i}",
                positional=True,
                required=True,
                param_kind=ParamKind.PLAIN,
            )
            for i in range(5)
        ]
        config_fields = [
            _make_field_descriptor(
                f"cfg_{i}",
                default=f"v{i}",
                param_kind=ParamKind.CONFIG,
            )
            for i in range(5)
        ]
        fields = positional_fields + config_fields
        log = _create_tui_and_render("job", fields, docstring="Job")
        field_lines = log.lines[1:]

        # All 5 positional plain params shown (positional names keep underscores —
        # they carry no flag, so no hyphenation)
        for i in range(5):
            assert any(f"pos_{i}" in line for line in field_lines)

        # Only first 3 config params shown (options hyphenate: cfg_i → cfg-i)
        for i in range(3):
            assert any(f"cfg-{i}" in line for line in field_lines)

        # Truncation: +2 more
        assert "+2 more" in field_lines[-1]


class TestTruncationIndicatorLine:
    """R3-AC4: Truncation indicator shows '... +{N} more — Ctrl+R for all'."""

    def test_truncation_line_format(self) -> None:
        """Truncation line has correct format with dim styling."""
        fields = [_make_field_descriptor(f"f_{i}", default=f"v{i}") for i in range(10)]
        log = _create_tui_and_render("job", fields, docstring="Job")
        truncation_line = log.lines[-1]
        assert "..." in truncation_line
        assert "+2 more" in truncation_line
        assert "Ctrl+R for all" in truncation_line
        assert "[dim]" in truncation_line

    def test_no_truncation_line_when_all_fit(self) -> None:
        """No truncation line when all fields fit within cap."""
        fields = [_make_field_descriptor(f"f_{i}", default=f"v{i}") for i in range(5)]
        log = _create_tui_and_render("job", fields, docstring="Job")
        # No line should contain the truncation indicator
        assert not any("more" in line for line in log.lines)
        assert not any("Ctrl+R for all" in line for line in log.lines)

    def test_truncation_count_accurate(self) -> None:
        """The +N count accurately reflects hidden config fields."""
        # 2 plain + 15 config = 17 total
        # Config cap = 8 - 2 = 6, hidden = 15 - 6 = 9
        plain = [
            _make_field_descriptor(f"p_{i}", param_kind=ParamKind.PLAIN, default="x")
            for i in range(2)
        ]
        config = [_make_field_descriptor(f"c_{i}", default=f"v{i}") for i in range(15)]
        fields = plain + config
        log = _create_tui_and_render("job", fields, docstring="Job")
        truncation_line = log.lines[-1]
        assert "+9 more" in truncation_line


class TestEdgeCases:
    """Edge cases for truncation logic."""

    def test_only_plain_params_no_truncation(self) -> None:
        """When all fields are plain, no truncation occurs regardless of count."""
        fields = [
            _make_field_descriptor(
                f"p_{i}",
                param_kind=ParamKind.PLAIN,
                default=f"v{i}",
            )
            for i in range(15)
        ]
        log = _create_tui_and_render("job", fields, docstring="Job")
        field_lines = log.lines[1:]
        # All 15 plain params shown
        assert len(field_lines) == 15
        assert not any("more" in line for line in field_lines)

    def test_zero_config_cap_all_plain_exceed(self) -> None:
        """When plain params alone >= 8, config cap is 0 — all config hidden."""
        # 9 plain + 3 config = 12 total
        # Config cap = max(0, 8 - 9) = 0
        plain = [
            _make_field_descriptor(
                f"p_{i}", param_kind=ParamKind.PLAIN, default=f"v{i}"
            )
            for i in range(9)
        ]
        config = [_make_field_descriptor(f"c_{i}", default=f"v{i}") for i in range(3)]
        fields = plain + config
        log = _create_tui_and_render("job", fields, docstring="Job")
        field_lines = log.lines[1:]

        # All 9 plain shown (options hyphenate: p_i → p-i)
        for i in range(9):
            assert any(f"p-{i}" in line for line in field_lines)

        # No config fields shown (they're all in "more")
        for i in range(3):
            assert not any(
                f"c-{i}" in line for line in field_lines if "more" not in line
            )

        # Truncation shows +3
        assert "+3 more" in field_lines[-1]

    def test_single_field_no_truncation(self) -> None:
        """A single field never triggers truncation."""
        fields = [_make_field_descriptor("only", default="val")]
        log = _create_tui_and_render("job", fields, docstring="Job")
        assert not any("more" in line for line in log.lines)
        assert any("only" in line for line in log.lines)
