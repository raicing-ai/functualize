"""Path suggestion model for filesystem completion.

Relocated from ``_cli/archive/panel_ring_models.py`` to its canonical
location in the data layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Path suggestion
# ---------------------------------------------------------------------------


@dataclass
class PathSuggestion:
    """A filesystem path completion suggestion.

    Used by both Config Table inline edit and SmartBar value completions
    for path-typed fields.
    """

    path: Path
    is_directory: bool
    display: str  # Formatted for display (relative or absolute)
