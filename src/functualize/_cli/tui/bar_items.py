"""Plugin-provided header and status bar items (pure logic, no Textual).

Implements the consumption side of the ``HeaderItemProvider``,
``StatusBarItemProvider``, and ``BarRenderer`` protocols from
``functualize.plugin.protocols``:

- Items are collected from plugin instances, rendered per provider
  (None results skipped, provider exceptions logged and isolated),
  sorted by ``item_priority``, and joined with a double-space separator.
- A registered ``BarRenderer`` with a matching ``bar_type`` replaces the
  default join rendering; the last registered renderer wins.

The app passes the final string into the ``#header`` / ``#status-bar``
Statics — this module never touches widgets, so it is testable with
plain pytest.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from functualize.plugin.protocols import (
    BarRenderer,
    HeaderItemProvider,
    SessionState,
    StatusBarItemProvider,
)

if TYPE_CHECKING:
    from functualize.app.core import FunctualizeApp

logger = logging.getLogger(__name__)

_SEPARATOR = "  "


def _collect_items(
    plugins: list[Any],
    protocol: type,
    render: Any,
) -> list[tuple[str, str]]:
    """Collect (item_id, text) pairs from providers, priority-sorted.

    Args:
        plugins: Plugin instances to inspect.
        protocol: The runtime-checkable provider protocol to match.
        render: Callable(provider) -> str | None invoking the provider's
            render_item with the right arguments.

    Returns:
        (item_id, text) pairs sorted by item_priority (lower first),
        None renders skipped, provider exceptions logged and skipped.
    """
    collected: list[tuple[int, str, str]] = []
    for plugin in plugins:
        if not isinstance(plugin, protocol):
            continue
        provider: Any = plugin  # isinstance vs a dynamic protocol narrows to object
        try:
            text = render(provider)
        except Exception as exc:
            logger.warning(
                "Bar item provider %r failed: %s: %s",
                getattr(provider, "item_id", type(provider).__name__),
                type(exc).__name__,
                exc,
            )
            continue
        if text is None:
            continue
        collected.append((provider.item_priority, provider.item_id, str(text)))

    collected.sort(key=lambda entry: (entry[0], entry[1]))
    return [(item_id, text) for _, item_id, text in collected]


def find_bar_renderer(plugins: list[Any], bar_type: str) -> BarRenderer | None:
    """Return the last-registered BarRenderer for the bar type, or None."""
    renderer: BarRenderer | None = None
    for plugin in plugins:
        if isinstance(plugin, BarRenderer) and plugin.bar_type == bar_type:
            renderer = plugin
    return renderer


def _render_bar(
    plugins: list[Any],
    bar_type: str,
    items: list[tuple[str, str]],
    context: dict[str, object],
) -> str | None:
    """Render collected items with the default join or a BarRenderer.

    Returns None when there are no items and no renderer, so callers keep
    their built-in bar text untouched.
    """
    renderer = find_bar_renderer(plugins, bar_type)
    if renderer is not None:
        try:
            return renderer.render(items, context)
        except Exception as exc:
            logger.warning(
                "BarRenderer for %r failed: %s: %s — falling back to default",
                bar_type,
                type(exc).__name__,
                exc,
            )
    if not items:
        return None
    return _SEPARATOR.join(text for _, text in items)


def render_header_items(plugins: list[Any], app: FunctualizeApp) -> str | None:
    """Render plugin header bar content, or None when nothing contributes."""
    items = _collect_items(plugins, HeaderItemProvider, lambda p: p.render_item(app))
    return _render_bar(plugins, "header", items, {"app": app})


def render_status_items(
    plugins: list[Any],
    app: FunctualizeApp,
    state: SessionState | None = None,
) -> str | None:
    """Render plugin status bar content, or None when nothing contributes."""
    session_state = state if state is not None else SessionState()
    items = _collect_items(
        plugins,
        StatusBarItemProvider,
        lambda p: p.render_item(app, session_state),
    )
    return _render_bar(plugins, "status", items, {"app": app, "state": session_state})
