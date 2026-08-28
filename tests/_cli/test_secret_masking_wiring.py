"""The masking flag must actually *reach* the surfaces that mask.

`tests/_cli/test_secret_masking_surfaces.py` proves the three formatters mask
when told to. It cannot prove anything tells them to: it builds its own
`SimpleNamespace(secret=True)` and hands it straight to the formatter, so the
whole chain in front of the formatter is untested. That chain is where the
value travels:

    Pydantic model
      -> model_json_schema()            (`Secret.__get_pydantic_json_schema__`)
      -> FieldDescriptor.secret         (`extract_field_descriptors`)
      -> the discovery cache            (`_field_to_dict` / `_field_from_dict`)
      -> FieldDef.secret                (`build_command_panels`)
      -> the rendered cell              (ConfigTablePanel, SourceChainDetailView)
      -> SmartBar.password              (InsertModeController.enter_insert)

Replacing the one line in `build_command_panels` that copies the flag onto
`FieldDef` left 2181 tests passing while every TUI surface rendered
credentials in cleartext. These tests exist so that link, and every other link
above, is load-bearing.

The rule the suite got wrong: **a masking test must start where the declaration
starts.** These begin at a real `BaseModel` — never at a hand-made stand-in
whose missing attribute is indistinguishable from a broken wiring.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, Field

from functualize._cli.tui.app import FunctualizeInlineTUI
from functualize._cli.tui.bar import BarReadiness
from functualize._cli.tui.chain_resolution import build_command_panels
from functualize._cli.tui.focus import FocusState
from functualize._discovery.schema_extractor import extract_field_descriptors
from functualize._types.descriptors import _field_from_dict, _field_to_dict
from functualize.app.utils import MASK
from functualize.types import Secret

REAL = "hunter2-real-credential-value"


class DeclaringModel(BaseModel):
    """One model carrying every way a field can and cannot be a secret."""

    token: Secret[str] = Field(default=Secret(REAL), description="The public way")
    legacy: str = Field(
        default=REAL,
        description="A field that must stay a plain str",
        json_schema_extra={"secret": True},
    )
    sort_key: str = Field(default="created_at", description="Not a secret")
    api_url: str = Field(default="https://api.example.com", description="Not a secret")


#: Names that must mask, and names that must not. Kept as one table so a test
#: cannot quietly cover only the positive half.
SECRET_FIELDS = ("token", "legacy")
PLAIN_FIELDS = ("sort_key", "api_url")


def _descriptors_through_the_cache() -> list[Any]:
    """Real descriptors, round-tripped through the cache serializer.

    Not `extract_field_descriptors` alone: the TUI reads the *cached* copy on a
    warm boot, so a flag that is derived correctly and then dropped on the way
    to disk would leak exactly where it matters and pass a test that skipped
    this step.
    """
    return [
        _field_from_dict(_field_to_dict(fd))
        for fd in extract_field_descriptors(DeclaringModel)
    ]


def _tui_for(descriptors: list[Any], smartbar_value: str) -> FunctualizeInlineTUI:
    """A TUI whose job descriptor carries the real, cache-round-tripped fields."""
    job = SimpleNamespace(
        name="sync",
        config_fields=descriptors,
        # Distinct object so `has_config_class` is True — a config job, which
        # is what a declared secret always is.
        parameters=list(descriptors[:1]),
        docstring="Sync with the remote API",
        group=None,
        source_path=None,
    )
    func_app = MagicMock()
    func_app.name = "test-app"
    func_app.get_jobs.return_value = [job]
    func_app.get_job.side_effect = lambda name: job if name == "sync" else None
    func_app.config_files.return_value = []

    with patch.object(FunctualizeInlineTUI, "__init__", lambda self, *a, **kw: None):
        tui = FunctualizeInlineTUI.__new__(FunctualizeInlineTUI)
        tui._func_app = func_app
        tui._smart_bar = MagicMock()
        tui._smart_bar.value = smartbar_value
        tui._smart_bar.readiness = BarReadiness.PENDING
        tui._panel_id_seq = 0
        tui._pending = None
        tui._snapshot_store = MagicMock()
        tui._focus_state = FocusState()
    return tui


def _fields_by_name(panels: list[tuple[str, Any]]) -> dict[str, Any]:
    return {f.name: f for f in panels[0][1]._fields}


# ===========================================================================
# Link 1 — declaration to descriptor, and descriptor through the cache
# ===========================================================================


class TestTheFlagSurvivesToTheCache:
    @pytest.mark.parametrize("name", SECRET_FIELDS)
    def test_a_declared_secret_arrives_marked(self, name):
        by_name = {fd.name: fd for fd in _descriptors_through_the_cache()}
        assert by_name[name].secret is True, (
            f"{name!r} is declared secret in the model but the descriptor the "
            "TUI reads does not say so"
        )

    @pytest.mark.parametrize("name", PLAIN_FIELDS)
    def test_a_plain_field_arrives_unmarked(self, name):
        """`sort_key` is what every name-based heuristic masked by mistake."""
        by_name = {fd.name: fd for fd in _descriptors_through_the_cache()}
        assert by_name[name].secret is False


# ===========================================================================
# Link 2 — descriptor to FieldDef, through the real panel builder
# ===========================================================================


class TestTheFlagReachesThePanel:
    """This is the link whose removal left the whole suite green."""

    @pytest.mark.parametrize("name", SECRET_FIELDS)
    def test_build_command_panels_marks_the_secret_field(self, name):
        tui = _tui_for(_descriptors_through_the_cache(), "sync")
        fields = _fields_by_name(build_command_panels(tui))
        assert fields[name].secret is True, (
            f"the descriptor's secret flag did not reach FieldDef for {name!r} "
            "— every TUI surface renders this credential in cleartext"
        )

    @pytest.mark.parametrize("name", PLAIN_FIELDS)
    def test_build_command_panels_leaves_plain_fields_alone(self, name):
        tui = _tui_for(_descriptors_through_the_cache(), "sync")
        fields = _fields_by_name(build_command_panels(tui))
        assert fields[name].secret is False


# ===========================================================================
# Link 3 — FieldDef to the rendered cell, through the real panel widget
# ===========================================================================


class TestTheRenderedCells:
    @pytest.mark.parametrize("name", SECRET_FIELDS)
    def test_the_config_table_cell_is_masked(self, name):
        """A value typed on the bar reaches the table as `source="cli"`.

        The bar is where a credential most plausibly appears, and unlike a
        model default it is not dropped on the way through the cache.
        """
        tui = _tui_for(_descriptors_through_the_cache(), f"sync --{name} {REAL}")
        panels = build_command_panels(tui)
        panel = panels[0][1]
        field = _fields_by_name(panels)[name]
        cells = panel._format_field_cells(field)

        assert field.value == REAL, "the fixture did not put a value in the cell"
        assert REAL not in " ".join(str(c) for c in cells), (
            f"the Config Table rendered {name!r} in cleartext"
        )
        assert MASK in cells

    @pytest.mark.parametrize("name", PLAIN_FIELDS)
    def test_a_plain_cell_shows_its_value(self, name):
        """Without this the masking above could be 'mask everything'."""
        typed = "typed-plain-value"
        tui = _tui_for(_descriptors_through_the_cache(), f"sync --{name} {typed}")
        panels = build_command_panels(tui)
        panel = panels[0][1]
        field = _fields_by_name(panels)[name]
        cells = panel._format_field_cells(field)

        assert field.value == typed
        assert MASK not in cells
        assert typed in cells

    @pytest.mark.parametrize("name", SECRET_FIELDS)
    def test_the_drill_down_masks_every_source_row(self, name):
        """The detail view masks losing sources too — it must know which rows.

        Rendered through the widget's own cell builder rather than by reading
        the flag back off the row: the flag existing proves nothing about what
        reaches the screen.
        """
        from functualize._cli.tui.source_chain_detail import (
            SourceChainDetailView,
            _DetailRow,
        )

        tui = _tui_for(_descriptors_through_the_cache(), "sync")
        field = _fields_by_name(build_command_panels(tui))[name]

        losing = _DetailRow(
            key_name=name,
            source_id="file",
            label="config.base.toml",
            value=REAL,
            is_set=True,
            effective=REAL,
            status="overridden",
            writable=True,
            type_hint="str",
            choices=None,
            description="",
            secret=field.secret,
        )
        view = SourceChainDetailView.__new__(SourceChainDetailView)
        view._staged_removals = set()
        view._staged_edits = {}

        rendered = view._display_value(losing)
        assert REAL not in rendered, (
            f"the drill-down rendered an overridden source's value for {name!r} "
            "— a losing source is exactly as sensitive as the winning one"
        )
        assert rendered == MASK

    def test_the_drill_down_shows_a_plain_row(self):
        """Guard the guard."""
        from functualize._cli.tui.source_chain_detail import (
            SourceChainDetailView,
            _DetailRow,
        )

        tui = _tui_for(_descriptors_through_the_cache(), "sync")
        field = _fields_by_name(build_command_panels(tui))["sort_key"]

        row = _DetailRow(
            key_name="sort_key",
            source_id="file",
            label="config.base.toml",
            value="created_at",
            is_set=True,
            effective="created_at",
            status="winning",
            writable=True,
            type_hint="str",
            choices=None,
            description="",
            secret=field.secret,
        )
        view = SourceChainDetailView.__new__(SourceChainDetailView)
        view._staged_removals = set()
        view._staged_edits = {}

        assert view._display_value(row) == "created_at"


# ===========================================================================
# Link 4 — FieldDef to the bar, through the real INSERT-mode controller
# ===========================================================================


@pytest.mark.asyncio
class TestTheBarMasksWhatInsertModeGivesIt:
    """`enter_edit_mode(secret=True)` works. Something has to pass that True."""

    @staticmethod
    async def _bar_after_entering(field_name: str):
        from textual.app import App, ComposeResult

        from functualize._cli.tui.bar import SmartBar
        from functualize._cli.tui.insert_mode import InsertModeController

        class _Harness(App[None]):
            def compose(self) -> ComposeResult:
                yield SmartBar(id="bar")

        app = _Harness()
        async with app.run_test():
            bar = app.query_one("#bar", SmartBar)
            bar.value = "sync"

            tui = _tui_for(_descriptors_through_the_cache(), "sync")
            field = _fields_by_name(build_command_panels(tui))[field_name]

            focus_state = FocusState()
            # INSERT is only reachable from NORMAL. Without this the controller
            # returns False and the bar is never touched — a test that then
            # read `bar.password` would be asserting on an untouched default.
            assert focus_state.enter_normal()

            controller = InsertModeController(focus_state, bar)
            assert controller.enter_insert(field), (
                "INSERT mode was not entered, so this test proves nothing"
            )
            return bar.password

    @pytest.mark.parametrize("name", SECRET_FIELDS)
    async def test_editing_a_secret_masks_the_bar(self, name):
        assert await self._bar_after_entering(name) is True, (
            "INSERT mode did not ask the bar to mask — the credential is "
            "echoed on screen as it is typed"
        )

    @pytest.mark.parametrize("name", PLAIN_FIELDS)
    async def test_editing_a_plain_field_does_not_mask(self, name):
        assert await self._bar_after_entering(name) is False
