"""Every TUI surface that renders a config value must mask a secret one.

There are three, and they are reached in two keystrokes: the pre-flight summary
under the SmartBar, the Config Table panel (Ctrl+R), and the source-chain
drill-down (Enter). Each one previously rendered credentials in cleartext,
including values the TUI had itself fetched from the environment.

These tests exist to fail if the masking is removed. That is not rhetorical —
the masking shipped once with no test guarding it, and deleting the branch left
the whole suite green (`contributor/guides/wiring-discipline.md`).

Masking follows the **model's** answer (`FieldDescriptor.secret`, carried through
the discovery cache), never the field's name: a field called `sort_key` shows its
value, and a field called `credential` does not.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from functualize._cli.tui.preflight_summary import format_preflight_field_line
from functualize.app.utils import MASK

REAL = "hunter2-real-credential-value"


def _fd(name: str, *, secret: bool = False, default=None, required: bool = False):
    """A field descriptor stand-in carrying only what the formatter reads."""
    return SimpleNamespace(
        name=name,
        secret=secret,
        default=default,
        required=required,
        description="",
        type_annotation="str",
        positional=False,
        short_flag=None,
        param_kind=None,
    )


# ===========================================================================
# Surface 1 — the pre-flight summary (the panel read before Ctrl+Enter)
# ===========================================================================


class TestPreflightSummary:
    def test_masks_a_value_typed_on_the_bar(self):
        line = format_preflight_field_line(
            _fd("credential", secret=True), {"credential": REAL}
        )
        assert REAL not in line
        assert MASK in line

    def test_masks_a_nonempty_default(self):
        """Nothing typed: the default alone used to render on screen."""
        line = format_preflight_field_line(
            _fd("api_key", secret=True, default="dev-key-in-the-default"), {}
        )
        assert "dev-key-in-the-default" not in line
        assert MASK in line

    def test_does_not_mask_a_plain_field(self):
        line = format_preflight_field_line(_fd("sort_key", default="created_at"), {})
        assert "created_at" in line
        assert MASK not in line

    def test_unset_secret_shows_neither_mask_nor_value(self):
        """A mask on an unset field would claim a credential is configured."""
        line = format_preflight_field_line(
            _fd("credential", secret=True, default=""), {}
        )
        assert MASK not in line

    @pytest.mark.parametrize(
        "name", ["credential", "pat", "bearer", "session", "auth", "passphrase"]
    )
    def test_secret_names_the_old_regex_missed(self, name):
        line = format_preflight_field_line(_fd(name, secret=True), {name: REAL})
        assert REAL not in line

    @pytest.mark.parametrize(
        "name", ["sort_key", "keywords", "partition_key", "monkey_patch"]
    )
    def test_plain_names_the_old_regex_falsely_masked(self, name):
        line = format_preflight_field_line(_fd(name, default="visible"), {})
        assert "visible" in line


# ===========================================================================
# Surface 2 — the Config Table panel (Ctrl+R)
# ===========================================================================


class TestConfigTablePanel:
    def test_masks_a_secret_value(self):
        from functualize._cli.tui.panels.config_table import ConfigTablePanel, FieldDef

        field = FieldDef(name="credential", value=REAL, source="env", secret=True)
        cells = ConfigTablePanel._format_field_cells(field)
        assert REAL not in "".join(cells)
        assert MASK in cells[2]

    def test_does_not_mask_a_plain_value(self):
        from functualize._cli.tui.panels.config_table import ConfigTablePanel, FieldDef

        field = FieldDef(name="sort_key", value="created_at", source="default")
        cells = ConfigTablePanel._format_field_cells(field)
        assert cells[2] == "created_at"

    def test_unset_secret_stays_empty(self):
        from functualize._cli.tui.panels.config_table import ConfigTablePanel, FieldDef

        field = FieldDef(name="credential", value="", source="", secret=True)
        cells = ConfigTablePanel._format_field_cells(field)
        assert cells[2] == ""


# ===========================================================================
# Surface 3 — the source-chain drill-down (Enter on a row)
# ===========================================================================


class TestSourceChainDetail:
    @staticmethod
    def _row(*, secret: bool, value: str, effective: str = ""):
        from functualize._cli.tui.source_chain_detail import _DetailRow

        return _DetailRow(
            key_name="credential",
            source_id="env",
            label="Env",
            value=value,
            is_set=bool(value),
            effective=effective or value,
            status="winning",
            writable=False,
            type_hint="str",
            choices=None,
            description="",
            secret=secret,
        )

    def test_masks_the_winning_source(self):
        from functualize._cli.tui.source_chain_detail import SourceChainDetailView

        row = self._row(secret=True, value=REAL)
        assert SourceChainDetailView._mask_or(row, row.value) == MASK

    def test_masks_a_losing_source_too(self):
        """A losing source's value is exactly as sensitive as the winner's."""
        from functualize._cli.tui.source_chain_detail import SourceChainDetailView

        row = self._row(secret=True, value="losing-but-still-a-credential")
        assert "losing" not in SourceChainDetailView._mask_or(row, row.value)

    def test_plain_row_renders_its_value(self):
        from functualize._cli.tui.source_chain_detail import SourceChainDetailView

        row = self._row(secret=False, value="created_at")
        assert SourceChainDetailView._mask_or(row, row.value) == "created_at"

    def test_unset_row_reads_as_unset_not_as_masked(self):
        from functualize._cli.tui.source_chain_detail import SourceChainDetailView

        row = self._row(secret=True, value="")
        assert SourceChainDetailView._mask_or(row, row.value) == "—"
