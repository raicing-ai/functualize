"""SettingsFilesPanel — the files `func`'s own settings resolve through.

The Settings-side mirror of the Config Files panel: where that panel lists
the ``config.*`` files a job's config merges from, this one lists the files
``resolve_cli_config`` consults — project ``.functualize.toml`` /
``pyproject.toml [tool.functualize]`` layers plus the global
``~/.config/functualize/config.toml``.

It reuses ConfigFilesPanel wholesale (same table, keys, filtering); only the
drill-down destination differs, so the message type is redefined — Enter
pushes a Detail view over the *settings* chain, not a job's.

Unlike the job-config panel, the global file is listed even when it does not
exist yet: it is the one canonical "save globally" location, and a user who
doesn't know the convention can only discover it by seeing it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.message import Message

# The parent-walk _is_writable (writable-if-creatable) rather than the
# panel-side one, which only answers for files that already exist.
from functualize._cli.data.func_settings import _is_writable
from functualize._cli.tui.panels.config_files import (
    ConfigFileEntry,
    ConfigFilesPanel,
    _make_display_name,
)

if TYPE_CHECKING:
    from pathlib import Path

    from functualize._cli.data.func_settings import FuncSettingsStore

__all__ = ["SettingsFilesPanel", "build_settings_file_entries"]


class SettingsFilesPanel(ConfigFilesPanel):
    """Row-navigable list of `func` settings files.

    Inherits all navigation, filtering, and rendering from ConfigFilesPanel;
    redefines DrillDownRequested so the app routes Enter to the settings
    chain provider instead of a job's.
    """

    class DrillDownRequested(Message):
        """Posted when Enter is pressed on a settings-file row."""

        def __init__(self, file_entry: ConfigFileEntry) -> None:
            self.file_entry = file_entry
            super().__init__()

    class NewFileRequested(Message):
        """Posted when `n` is pressed — user wants to create a settings file."""

    def get_available_actions(self, focused: bool) -> list[tuple[str, str]]:
        """Footer hints — inherited, except the unfocused focus key.

        This panel lives on the General ring (Ctrl+E); the inherited hint
        advertises Ctrl+R, the Command ring.
        """
        if not focused:
            return [("Ctrl+E", "focus"), ("Shift+Tab", "cycle")]
        return super().get_available_actions(focused)


def build_settings_file_entries(
    store: FuncSettingsStore, cwd: Path
) -> list[ConfigFileEntry]:
    """Build panel rows from the store's file layers.

    Every layer contributes (there is no environment banding for settings),
    so an existing file is always ``active``. The missing global file is the
    one ``not found`` row we deliberately keep.
    """
    entries: list[ConfigFileEntry] = []
    for info in store.layers:
        exists = info.exists
        if not exists and info.kind != "global":
            continue
        entries.append(
            ConfigFileEntry(
                path=info.path,
                section=info.section_prefix,
                display_name=_make_display_name(info.path, cwd),
                status="active" if exists else "not_found",
                fields_from_file=store.defined_settings(info),
                environment_slot=None,
                writable=_is_writable(info.path),
            )
        )
    return entries
