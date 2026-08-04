"""Unit tests for public accessors replacing private panel/panel_host reach-ins.

``app.py``/``KeyDispatcher`` shall not reach into
``panel._fields``, ``panel._reload_table``, ``panel_host._type_prefix``, or
(extended 2026-07-15) ``panel_host._current_index`` — public accessors
(``ConfigTablePanel.fields`` / ``reload_table()``, ``PanelHost.set_type_prefix()``,
``PanelHost.current_index``) shall be used instead.
"""

from __future__ import annotations

import re
from pathlib import Path

APP_PY = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "functualize"
    / "_cli"
    / "tui"
    / "app.py"
)

_REACH_IN_PATTERN = re.compile(
    r"panel\._fields|panel\._reload_table|panel_host\._type_prefix|panel_host\._current_index"
)


def test_app_py_has_no_private_panel_reach_ins() -> None:
    """app.py must not read/write private panel(_host) attributes."""
    content = APP_PY.read_text()
    matches = _REACH_IN_PATTERN.findall(content)
    assert matches == [], f"Found private reach-ins in app.py: {matches}"


def test_config_table_panel_exposes_public_fields() -> None:
    """ConfigTablePanel.fields exposes the current field list publicly."""
    from functualize._cli.tui.panels.config_table import ConfigTablePanel, FieldDef

    panel = ConfigTablePanel()
    field = FieldDef(name="foo", value="bar", source="default")
    panel.set_fields([field])
    assert panel.fields == [field]


def test_config_table_panel_reload_table_is_public() -> None:
    """ConfigTablePanel.reload_table() is a public wrapper over _reload_table."""
    from functualize._cli.tui.panels.config_table import ConfigTablePanel

    panel = ConfigTablePanel()
    assert hasattr(panel, "reload_table")
    # Should not raise even without a mounted DataTable.
    panel.reload_table()


def test_panel_host_set_type_prefix() -> None:
    """PanelHost.set_type_prefix() is the public setter for the type prefix."""
    from functualize._cli.tui.panel_host import PanelHost

    host = PanelHost(type_prefix="D")
    host.set_type_prefix("R")
    assert host._type_prefix == "R"


def test_panel_host_current_index_getter_setter() -> None:
    """PanelHost.current_index is a public read/write property (2026-07-15 extension)."""
    from functualize._cli.tui.panel_host import PanelHost

    host = PanelHost(type_prefix="D")
    assert host.current_index == 0
    host.current_index = 2
    assert host.current_index == 2
    assert host._current_index == 2
