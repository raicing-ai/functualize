"""Display slot chrome rendering for the inline TUI.

Updates the display breadcrumb and footer widgets to reflect the
DisplaySlot's currently visible provider. The body is the DisplaySlot's own
mounted widget tree (it repaints itself), so no content extraction happens
here anymore.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widgets import Static

if TYPE_CHECKING:
    from functualize._cli.tui.app import FunctualizeInlineTUI


def update_display_chrome(app: FunctualizeInlineTUI) -> None:
    """Update display breadcrumb and footer from the DisplaySlot state."""
    try:
        provider = app._display_slot.current_provider
        if not provider:
            return
        visible_count = app._display_slot.visible_count
        idx = app._display_slot._visible_index + 1 if app._display_slot._visible else 0

        # Breadcrumb — with the drill-down sub-level when one is pushed.
        bc = app.query_one("#display-bc", Static)
        crumb = f"  [D:{idx}/{visible_count}] {provider.display_title}"
        sub_title = app._display_slot.current_view_title
        if sub_title:
            crumb += f" › {sub_title}"
        bc.update(crumb)

        # Footer — delegate to focus-aware display footer
        app._update_display_footer(app._focus_state.zone)
    except Exception as exc:
        # Guards a multi-step refresh (breadcrumb/footer widget lookups plus
        # provider access); not a single query_one call, so a broad catch
        # stays but is logged rather than silently dropped.
        app.log.warning(
            f"update_display_chrome: failed to refresh display chrome "
            f"({type(exc).__name__}): {exc}"
        )
