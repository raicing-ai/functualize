"""Unit test asserting message handler families are typed, not ``event: Any``.

Message handler methods in ``app.py``
(``on_config_table_panel_*``, ``on_diff_view_widget_*``,
``on_config_files_panel_*``, ``on_settings_panel_*``,
``on_job_browser_panel_*``, ``on_source_chain_detail_view_*``) shall type
their ``event`` parameter with the real message class from the emitting
widget, not ``event: Any``.
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

_HANDLER_FAMILIES = (
    "on_config_table_panel_",
    "on_diff_view_widget_",
    "on_config_files_panel_",
    "on_settings_panel_",
    "on_job_browser_panel_",
    "on_source_chain_detail_view_",
)

_HANDLER_DEF_RE = re.compile(
    r"def (on_\w+)\(\s*self,\s*event:\s*([^)]+?)\s*\)\s*->\s*None:", re.DOTALL
)


def test_handler_families_do_not_use_event_any() -> None:
    """No `on_*` handler in the 5 families types `event` as `Any`."""
    content = APP_PY.read_text()
    offending = []
    for match in _HANDLER_DEF_RE.finditer(content):
        name, event_type = match.group(1), match.group(2).strip()
        if name.startswith(_HANDLER_FAMILIES) and event_type == "Any":
            offending.append(name)
    assert offending == [], f"Handlers still typed as `event: Any`: {offending}"


def test_all_five_handler_families_are_present_and_typed() -> None:
    """Sanity check: every known handler across the families exists and is typed."""
    content = APP_PY.read_text()
    found = {
        match.group(1): match.group(2).strip()
        for match in _HANDLER_DEF_RE.finditer(content)
        if match.group(1).startswith(_HANDLER_FAMILIES)
    }
    expected_handlers = {
        "on_job_browser_panel_job_selected",
        "on_config_table_panel_insert_requested",
        "on_config_table_panel_override_reset",
        "on_config_table_panel_drill_down_requested",
        "on_diff_view_widget_load_session_requested",
        "on_diff_view_widget_back_requested",
        "on_config_files_panel_file_saved",
        "on_config_files_panel_drill_down_requested",
        "on_settings_panel_insert_requested",
        # These three were the gap: each panel posted the message and nothing
        # consumed it, so the edit went nowhere. This set previously listed
        # only the handlers that existed, which turned the gap into an
        # expectation instead of a failure.
        "on_settings_panel_setting_changed",
        "on_settings_panel_drill_down_requested",
        "on_source_chain_detail_view_insert_requested",
        "on_source_chain_detail_view_saved",
    }
    assert expected_handlers <= found.keys()
    for name in expected_handlers:
        assert found[name] != "Any", f"{name} still typed as Any"


def test_every_posted_message_has_a_handler() -> None:
    """No panel Message class is posted into the void.

    The original defect was structural, not a typo: panels implemented the
    message protocol correctly and only the first hop was ever wired, so
    `SettingChanged` and `ConfigFilesPanel.InsertRequested` were posted and
    silently dropped. Enumerating handlers by hand (above) cannot catch the
    *next* one; this derives the requirement from the code instead.
    """
    import inspect

    from functualize._cli.tui import app as app_module
    from functualize._cli.tui.settings_panel import SettingsPanel
    from functualize._cli.tui.source_chain_detail import SourceChainDetailView

    try:
        from textual.message import Message
    except ImportError:  # pragma: no cover - cli extras always present in CI
        return

    def _snake(name: str) -> str:
        return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()

    tui_cls = app_module.FunctualizeInlineTUI
    missing: list[str] = []
    for owner in (SettingsPanel, SourceChainDetailView):
        for attr, value in vars(owner).items():
            if not (inspect.isclass(value) and issubclass(value, Message)):
                continue
            handler = f"on_{_snake(owner.__name__)}_{_snake(attr)}"
            if not hasattr(tui_cls, handler):
                missing.append(f"{owner.__name__}.{attr} -> {handler}")

    assert missing == [], f"Messages posted with no handler: {missing}"
