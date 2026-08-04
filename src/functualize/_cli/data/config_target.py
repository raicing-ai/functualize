"""Config target model for persistence destinations.

Relocated from ``_cli/archive/panel_ring_models.py`` to its canonical
location in the data layer, where it is consumed by
``config_target_discovery.py``, ``settings_panel.py``, and
``config_table_widget.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Config target
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigTarget:
    """A writable persistence destination for config overrides.

    Represents one entry in the target selector shown during inline edit
    ('E' flow) — a specific file, or an environment variable.

    The ``type`` field carries two independent, non-overlapping vocabularies
    (deliberately not modelled as one shared enum):

    - job-config persistence targets: ``"file" | "env"`` — where a job-config
      override is written (see ``config_target_discovery`` / the
      ``default_override_target`` setting).
    - settings-panel-only marker: ``"unsaved"`` — a TUI setting that was edited
      but not persisted to disk (in-memory only for this process). This is
      conceptually distinct from job-config value provenance and never appears
      in the job-config persistence flow.
    """

    type: str  # "file" | "env" (job-config) OR "unsaved" (settings-panel only)
    label: str
    detail: str | None = None  # e.g., resolved path
    path: Path | None = None

    def display_label(self) -> str:
        """Format for display in the target selector list."""
        if self.detail:
            return f"{self.label} ({self.detail})"
        return self.label
