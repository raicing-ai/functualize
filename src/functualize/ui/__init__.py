"""functualize.ui — Textual building blocks for job-owned UIs.

Public home of the batteries-included Textual base class that job authors
subclass for a ``tty: TTY`` job::

    from functualize.ui import TextualApp

    class ConfigEditorApp(TextualApp[None]):
        def on_func_event(self, message):
            ...   # render engine events on the loop thread

Requires the ``[cli]`` extra (Textual). Importing this package without it
raises a clear install hint rather than a bare ImportError.
"""

from __future__ import annotations

try:
    import textual as _textual  # noqa: F401
except ImportError as _exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(
        "functualize.ui requires the [cli] extras group (Textual). "
        "Install with: pip install functualize[cli]"
    ) from _exc

from functualize.ui._prompt_modal import MODAL_CSS, PromptModal
from functualize.ui.display import Display
from functualize.ui.stdout_surface import StdoutSurface, stdout_live_session
from functualize.ui.textual_app import FuncEvent, TextualApp

__all__ = [
    "MODAL_CSS",
    "Display",
    "FuncEvent",
    "PromptModal",
    "StdoutSurface",
    "TextualApp",
    "stdout_live_session",
]
