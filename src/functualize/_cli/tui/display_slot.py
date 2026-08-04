"""DisplaySlot widget for the above-header display panel area.

Manages a ring of DisplayProviders, showing one at a time. Handles:
- CWD-based visibility filtering via should_show(cwd, app)
- Priority-ordered ring navigation with Ctrl+U/I
- Per-provider refresh timers (minimum 0.5s interval)
- Error handling: log and skip, never crash
- Job-linked display behavior (auto-switch, indicator, off)

Threading contract (steering_textual_tui.md §2.5 — HARD rule): a provider's
``refresh()`` is arbitrary user code that may do I/O (``docker ps``, ``git``),
so it MUST NOT run on the event-loop thread — it would freeze the whole TUI.
Refreshes run on a thread worker, one in-flight per display (a slow provider
skips its own cycles rather than queueing), each bounded by a timeout so a
*hung* provider is isolated instead of pinning a worker forever. Any UI update
that follows is marshaled back onto the loop thread via ``marshal``.

``should_show`` deliberately stays on the loop thread: it runs for every
provider on every CWD change, so it must stay cheap by contract.

This module is in the ``_cli/`` layer — it imports ONLY from public API.
Textual imports are guarded behind try/except ImportError.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.timer import Timer

    from functualize.app.core import FunctualizeApp
    from functualize.plugin.protocols import DisplayProvider

try:
    from textual.containers import Vertical
    from textual.css.query import NoMatches
    from textual.message_pump import NoActiveAppError  # type: ignore[attr-defined]
    from textual.reactive import reactive
    from textual.widget import Widget
    from textual.widgets import Static
except ImportError as _exc:
    raise ImportError(
        "DisplaySlot requires the [cli] extras group. "
        "Install with: pip install functualize[cli]"
    ) from _exc

from functualize._cli.tui.display_affinity import (
    get_auto_switch_target,
)
from functualize._cli.tui.models.ring_models import DisplayRing, RegisteredDisplay
from functualize._cli.tui.thread_marshal import marshal

logger = logging.getLogger(__name__)

# Minimum allowed refresh interval in seconds.
_MIN_REFRESH_INTERVAL: float = 0.5

# Default seconds to wait for a provider's refresh() before abandoning it.
# A provider may override with a ``refresh_timeout`` attribute.
_DEFAULT_REFRESH_TIMEOUT: float = 10.0

# Worker group for display refreshes, so they are distinguishable from (and
# never exclusive with) the job-execution worker.
_REFRESH_WORKER_GROUP = "display-refresh"


class DisplaySlot(Widget):
    """Above-header display panel area.

    Shows one DisplayProvider at a time from a filtered, priority-ordered ring.
    Supports Ctrl+U (prev) / Ctrl+O (next) navigation between visible displays.
    """

    DEFAULT_CSS = """
    DisplaySlot {
        height: auto;
    }
    #display-slot-content {
        height: auto;
        min-height: 1;
        max-height: 8;
        overflow-y: auto;
        padding: 0 1;
    }
    """

    # Reactive: whether the slot is visible (at least one provider passes should_show).
    is_visible_slot: reactive[bool] = reactive(False)

    # Reactive: the display_id of the currently shown display.
    current_display_id: reactive[str] = reactive("")

    def __init__(
        self,
        app_instance: FunctualizeApp,
        cwd: Path,
        display_auto_switch: str = "indicator",
        textual_app: object | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._app_instance = app_instance
        self._cwd = cwd
        self._display_auto_switch = display_auto_switch

        # The inline TUI mounts this widget inside #display-section, but the
        # slot also supports detached construction (unit tests build it with
        # no DOM): ``set_interval`` timers fire either way (they are scheduled
        # on the loop, not the widget's pump), while ``self.app`` raises
        # NoActiveAppError when detached — so worker dispatch and cross-thread
        # marshaling accept the app handed in explicitly.
        self._textual_app = textual_app

        # Drill-down sub-views pushed over the current display's content
        # (PanelHost's push_view idiom, capped at one sub-level). The top of
        # this stack owns the keys via ``current_interactive_widget``.
        self._view_stack: list[tuple[str, Widget]] = []

        # The single Static hosting get_content()/loading text, tracked by
        # reference — deliberately WITHOUT a widget id. remove_children() is
        # asynchronous, so a fixed id would collide with its not-yet-removed
        # predecessor (DuplicateIds) on rapid navigation/refresh remounts.
        self._content_static: Static | None = None

        # Content swaps (navigation, refresh remounts, drill-down pushes) are
        # serialized through awaited, generation-guarded coroutines: mounting
        # right after a fire-and-forget remove_children() races the pending
        # removal and crashes with DuplicateIds when provider widgets carry
        # explicit ids. A newer generation invalidates any in-flight swap.
        self._content_generation: int = 0

        # The full ring of all registered displays (unfiltered).
        self._ring = DisplayRing()

        # Active refresh timers keyed by display_id.
        self._refresh_timers: dict[str, Timer] = {}

        # display_ids whose refresh() is currently in flight. A display that
        # has not returned yet skips its next cycle instead of stacking work —
        # this is what keeps one hung provider from starving the others.
        self._refreshing: set[str] = set()

        # Single-worker executors keyed by display_id. A provider's refresh()
        # runs here so a *hung* call can be abandoned on timeout (the future is
        # dropped; the thread is a daemon and dies with the process) while the
        # worker thread returns and clears the in-flight guard.
        self._refresh_executors: dict[str, ThreadPoolExecutor] = {}

        # display_ids that have never completed a refresh — rendered as
        # "loading…" until their first refresh returns.
        self._loading: set[str] = set()

        # The currently visible (filtered) displays, cached after recompute.
        self._visible: list[RegisteredDisplay] = []

        # Index into the _visible list (not the full ring).
        self._visible_index: int = 0

        # Job-linking state.
        self._current_job_name: str | None = None
        self._auto_switch_suppressed: bool = False

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        """Compose an empty container — content is mounted dynamically."""
        yield Vertical(id="display-slot-content")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_display(self, provider: DisplayProvider) -> None:
        """Register a DisplayProvider into the ring.

        Inserts sorted by display_priority (lower = first). Ties broken by
        registration order.
        """
        display = RegisteredDisplay(
            provider=provider,
            display_id=provider.display_id,
            priority=provider.display_priority,
        )
        self._ring.insert_display(display)
        self._recompute_visible()

    def unregister_display(self, display_id: str) -> None:
        """Remove a display from the ring by ID."""
        self._ring._displays = [
            d for d in self._ring._displays if d.display_id != display_id
        ]
        self._stop_timer(display_id)
        self._recompute_visible()

    def update_cwd(self, cwd: Path) -> None:
        """Update the current working directory and recompute visibility."""
        self._cwd = cwd
        self._recompute_visible()

    def update_job(self, job_name: str | None) -> None:
        """Notify the slot that the recognized job has changed.

        Triggers auto-switch behavior based on display_auto_switch setting.
        """
        if job_name == self._current_job_name:
            return

        self._current_job_name = job_name
        self._auto_switch_suppressed = False

        if job_name is None:
            # Job cleared — revert to should_show(cwd) ordering.
            self._recompute_visible()
            return

        # Attempt auto-switch if setting is "auto".
        self._apply_job_linking()

    def set_auto_switch_setting(self, value: str) -> None:
        """Update the display_auto_switch setting ('auto', 'indicator', 'off')."""
        self._display_auto_switch = value

    def navigate_next(self) -> None:
        """Navigate to the next visible display (Ctrl+I)."""
        if len(self._visible) <= 1:
            return
        self._auto_switch_suppressed = True
        self._visible_index = (self._visible_index + 1) % len(self._visible)
        self._show_current()

    def navigate_prev(self) -> None:
        """Navigate to the previous visible display (Ctrl+U)."""
        if len(self._visible) <= 1:
            return
        self._auto_switch_suppressed = True
        self._visible_index = (self._visible_index - 1) % len(self._visible)
        self._show_current()

    @property
    def has_visible_displays(self) -> bool:
        """Whether any displays are currently visible."""
        return len(self._visible) > 0

    @property
    def visible_count(self) -> int:
        """Number of currently visible displays."""
        return len(self._visible)

    @property
    def current_provider(self) -> DisplayProvider | None:
        """The currently shown DisplayProvider, or None."""
        if not self._visible:
            return None
        return cast(
            "DisplayProvider | None", self._visible[self._visible_index].provider
        )

    def set_textual_app(self, textual_app: object) -> None:
        """Supply the running Textual app used for workers and marshaling.

        Needed because this widget is deliberately detached (see ``__init__``),
        so ``self.app`` cannot resolve one.
        """
        self._textual_app = textual_app

    def _resolve_textual_app(self) -> object | None:
        """The Textual app to dispatch workers / marshal UI writes through."""
        if self._textual_app is not None:
            return self._textual_app
        try:
            return self.app
        except NoActiveAppError:
            # Detached widget with no app handed in (unit tests constructing
            # the slot directly) — callers fall back to running inline.
            return None

    def is_loading(self, display_id: str) -> bool:
        """Whether a display is still awaiting its first completed refresh.

        Chrome rendering uses this to show a placeholder instead of content
        the provider has not populated yet.
        """
        return display_id in self._loading

    # ------------------------------------------------------------------
    # Interactive content — the PanelHost idiom over display widgets
    # ------------------------------------------------------------------

    @property
    def current_interactive_widget(self) -> Widget | None:
        """The widget that owns the keys while the DISPLAY zone is focused.

        The top drill-down sub-view if one is pushed, else the first
        focusable widget of the current display's mounted content, else
        None (a legacy non-interactive display — keys stay inert).

        This is what the app's zone-aware ``active_panel`` returns for the
        DISPLAY zone, so ``KeyDispatcher._resolve_target`` routes j/k/Enter
        here through the existing dispatch path — no second key-routing
        mechanism.
        """
        if self._view_stack:
            return self._view_stack[-1][1]
        try:
            container = self.query_one("#display-slot-content", Vertical)
        except NoMatches:
            return None
        for child in container.children:
            if child.can_focus:
                return child
        return None

    @property
    def view_depth(self) -> int:
        """How many drill-down sub-views are stacked on the display."""
        return len(self._view_stack)

    @property
    def current_view_title(self) -> str | None:
        """Title of the pushed sub-view, for the breadcrumb sub-level."""
        if self._view_stack:
            return self._view_stack[-1][0]
        return None

    def push_view(self, widget: Widget, sub_title: str) -> None:
        """Push a drill-down sub-view over the current display's content.

        Mirrors ``PanelHost.push_view`` (which is what makes a drill-down's
        keys work: ``current_interactive_widget`` returns the top of this
        stack), capped at one sub-level. No-op when the slot is detached.
        The widget swap is awaited (see ``_content_generation``).
        """
        if self._view_stack:
            return
        try:
            container = self.query_one("#display-slot-content", Vertical)
        except NoMatches:
            return
        self._view_stack.append((sub_title, widget))
        self._content_generation += 1
        self.call_next(self._mount_view, container, widget, self._content_generation)

    async def _mount_view(
        self, container: Vertical, widget: Widget, generation: int
    ) -> None:
        """Awaited sub-view mount (loop thread)."""
        if generation != self._content_generation:
            return
        self._content_static = None
        await container.remove_children()
        if generation != self._content_generation:
            return
        container.mount(widget)
        if hasattr(widget, "focus"):
            widget.focus()

    def pop_view(self) -> bool:
        """Pop the sub-view and restore the display's base content.

        Returns True if a view was popped, False if none was pushed.
        """
        if not self._view_stack:
            return False
        # _show_current clears the stack and remounts the base content.
        self._show_current()
        return True

    # ------------------------------------------------------------------
    # Internal — visibility and display management
    # ------------------------------------------------------------------

    def _recompute_visible(self) -> None:
        """Recompute which displays are visible based on should_show(cwd, app)."""
        visible: list[RegisteredDisplay] = []
        for display in self._ring._displays:
            try:
                if display.provider.should_show(self._cwd, self._app_instance):
                    visible.append(display)
            except Exception:
                # Req 5: should_show errors treated as False, log warning.
                logger.warning(
                    "DisplayProvider '%s' raised in should_show(), treating as hidden",
                    display.display_id,
                    exc_info=True,
                )

        self._visible = visible

        # Clamp index if it exceeds the new visible count.
        if self._visible:
            self._visible_index = min(self._visible_index, len(self._visible) - 1)
        else:
            self._visible_index = 0

        # Update reactive visibility.
        self.is_visible_slot = len(self._visible) > 0

        if self._visible:
            self._show_current()
            self._sync_timers()
        else:
            self.current_display_id = ""
            self._clear_content()
            self._stop_all_timers()

    def _show_current(self) -> None:
        """Mount the currently indexed display's content.

        Rebuilding always returns to the display's base content: any pushed
        drill-down sub-view is dropped (navigation away from a display closes
        its drill-down, like PanelHost's ``clear_views`` on ring rebuild).
        The actual widget swap runs as an awaited coroutine (see
        ``_content_generation``).
        """
        if not self._visible:
            return

        current = self._visible[self._visible_index]
        self.current_display_id = current.display_id
        self._view_stack.clear()

        try:
            container = self.query_one("#display-slot-content", Vertical)
        except NoMatches:
            # Detached logic-holder (unit tests constructing the slot
            # directly) — nothing to mount into; not an error.
            return

        self._content_generation += 1
        self.call_next(
            self._remount_content, container, current, self._content_generation
        )

    async def _remount_content(
        self, container: Vertical, current: RegisteredDisplay, generation: int
    ) -> None:
        """Awaited content swap for the current display (loop thread).

        Waits for the previous children to actually leave the DOM before
        mounting, so provider widgets with explicit ids cannot collide with
        their not-yet-removed predecessors.
        """
        if generation != self._content_generation:
            return
        self._content_static = None
        await container.remove_children()
        if generation != self._content_generation:
            return

        provider = current.provider

        # A display whose first refresh() has not returned yet has no content
        # to show; a placeholder is honest where stale/empty content is not.
        if self.is_loading(current.display_id):
            self._content_static = Static(
                f"  {provider.display_title} [dim]loading…[/dim]"
            )
            container.mount(self._content_static)
            return

        # get_content() convention: a provider exposing the simple string
        # method renders as one updatable Static — refreshes update it in
        # place with no remount.
        get_content = getattr(provider, "get_content", None)
        if callable(get_content):
            try:
                self._content_static = Static(get_content())
                container.mount(self._content_static)
            except Exception:
                logger.error(
                    "DisplayProvider '%s' raised in get_content()",
                    current.display_id,
                    exc_info=True,
                )
                container.mount(
                    Static(f"[red]Display error: {current.display_id}[/red]")
                )
            return

        try:
            widgets = list(provider.compose_display())
            for widget in widgets:
                container.mount(widget)
        except Exception:
            logger.error(
                "DisplayProvider '%s' raised in compose_display()",
                current.display_id,
                exc_info=True,
            )
            # Show a fallback error indicator.
            container.mount(Static(f"[red]Display error: {current.display_id}[/red]"))
            return

        # If the user is focused in the display zone, hand focus to the fresh
        # interactive widget (the remount replaced the one they held).
        engaged = getattr(self._resolve_textual_app(), "display_zone_engaged", None)
        if callable(engaged):
            try:
                if engaged():
                    focus_target = self.current_interactive_widget
                    if focus_target is not None:
                        focus_target.focus()
            except Exception:
                logger.warning(
                    "display_zone_engaged() raised during remount", exc_info=True
                )

    def _clear_content(self) -> None:
        """Remove all children from the display content container."""
        self._content_static = None
        # Invalidate any in-flight content swap so it cannot mount into the
        # container after this clear.
        self._content_generation += 1
        try:
            container = self.query_one("#display-slot-content", Vertical)
            container.remove_children()
        except NoMatches:
            pass

    # ------------------------------------------------------------------
    # Internal — refresh timers
    # ------------------------------------------------------------------

    def _sync_timers(self) -> None:
        """Synchronize refresh timers with the currently visible displays.

        Starts timers for visible displays that need refresh, stops timers
        for displays no longer visible.
        """
        visible_ids = {d.display_id for d in self._visible}

        # Stop timers for displays no longer visible.
        for display_id in list(self._refresh_timers.keys()):
            if display_id not in visible_ids:
                self._stop_timer(display_id)

        # Start timers for visible displays that need one.
        for display in self._visible:
            if display.display_id in self._refresh_timers:
                continue  # Already has a timer.
            interval = getattr(display.provider, "refresh_interval", None)
            if interval is None:
                continue
            # Enforce minimum 0.5s interval.
            interval = max(interval, _MIN_REFRESH_INTERVAL)
            timer = self.set_interval(
                interval,
                self._make_refresh_callback(display.display_id),
                name=f"refresh-{display.display_id}",
            )
            self._refresh_timers[display.display_id] = timer

            # Refresh once immediately rather than showing whatever
            # compose_display() produced pre-refresh for a full interval (a
            # 30s-interval display used to sit stale for 30s). The display is
            # "loading" until that first pass returns — now safe to do, since
            # the refresh no longer blocks the loop.
            self._loading.add(display.display_id)
            self._do_refresh(display.display_id)

    def _make_refresh_callback(self, display_id: str) -> Callable[[], None]:
        """Create a refresh callback bound to a specific display_id."""

        def _callback() -> None:
            self._do_refresh(display_id)

        return _callback

    def _do_refresh(self, display_id: str) -> None:
        """Dispatch a provider refresh onto a thread worker.

        Called from a ``set_interval`` timer, i.e. on the event-loop thread —
        so it must not touch ``provider.refresh()`` itself (HARD rule §2.5).
        It only guards re-entry and hands the work off.
        """
        if display_id in self._refreshing:
            # Previous cycle still running: a slow provider skips rather than
            # queueing, so it can never build a backlog or starve its peers.
            logger.debug(
                "DisplayProvider '%s' refresh still in flight, skipping cycle",
                display_id,
            )
            return

        provider = self._find_provider(display_id)
        if provider is None:
            return

        # refresh() is optional — discovery requires only display_id/title/
        # priority/should_show/compose_display. A provider without one has
        # nothing to do (and must not crash the timer loop).
        if not callable(getattr(provider, "refresh", None)):
            self._loading.discard(display_id)
            return

        self._refreshing.add(display_id)
        textual_app = self._resolve_textual_app()
        runner = getattr(textual_app, "run_worker", None)
        if runner is None:
            # No running app (unit tests constructing the slot directly): run
            # inline so behaviour stays observable, accepting the block.
            self._refreshing.discard(display_id)
            self._refresh_worker(display_id, provider)
            return
        try:
            runner(
                lambda: self._refresh_worker(display_id, provider),
                name=f"display-refresh-{display_id}",
                group=_REFRESH_WORKER_GROUP,
                thread=True,
            )
        except Exception:
            self._refreshing.discard(display_id)
            logger.warning(
                "Could not dispatch refresh worker for display '%s'",
                display_id,
                exc_info=True,
            )

    def _find_provider(self, display_id: str) -> DisplayProvider | None:
        """Return the visible provider with this id, or None."""
        for d in self._visible:
            if d.display_id == display_id:
                return cast("DisplayProvider | None", d.provider)
        return None

    def _refresh_worker(self, display_id: str, provider: DisplayProvider) -> None:
        """Run ``provider.refresh()`` off the loop thread, bounded by a timeout.

        This is the thread-worker body. It never raises: a provider that errors
        or hangs logs and is skipped (Req 5.8, extended to timeouts), leaving
        every other display refreshing normally.
        """
        timeout = self._refresh_timeout(provider)
        try:
            executor = self._executor_for(display_id)
            future = executor.submit(provider.refresh)
            try:
                future.result(timeout=timeout)
            except FutureTimeoutError:
                # Abandon the call: the future is dropped and its (daemon)
                # thread is left to finish or hang on its own. The executor is
                # replaced so the next cycle is not stuck behind it.
                logger.warning(
                    "DisplayProvider '%s' refresh() exceeded %.1fs, abandoning "
                    "this cycle",
                    display_id,
                    timeout,
                )
                self._discard_executor(display_id)
                return
            except Exception:
                logger.error(
                    "DisplayProvider '%s' raised in refresh(), skipping cycle",
                    display_id,
                    exc_info=True,
                )
                return
        finally:
            # Clearing the guard on the loop thread keeps the set's mutations
            # serialized with the timer callbacks that read it.
            marshal(self._resolve_textual_app(), self._finish_refresh, display_id)

        # refresh() mutated provider state the chrome renders from — ask the
        # app to repaint, on the loop thread.
        marshal(self._resolve_textual_app(), self._on_refresh_complete, display_id)

    def _finish_refresh(self, display_id: str) -> None:
        """Clear the in-flight guard (loop thread)."""
        self._refreshing.discard(display_id)

    def _on_refresh_complete(self, display_id: str) -> None:
        """Repaint after a successful refresh (loop thread)."""
        was_loading = display_id in self._loading
        self._loading.discard(display_id)

        # Only the visible display's content is on screen; a background
        # display's refresh needs no repaint until it is navigated to.
        if self.current_display_id != display_id:
            return

        updater = getattr(self._resolve_textual_app(), "_update_display_chrome", None)
        if callable(updater):
            try:
                updater()
            except Exception:
                logger.warning(
                    "Failed to refresh display chrome for '%s'",
                    display_id,
                    exc_info=True,
                )
        self._refresh_mounted_content(display_id, was_loading)

    def _refresh_mounted_content(self, display_id: str, was_loading: bool) -> None:
        """Bring the mounted content up to date after a refresh (loop thread).

        - A drill-down sub-view owns the screen: leave it alone.
        - A ``get_content()`` provider: update its Static in place.
        - Otherwise: remount from ``compose_display()`` — unless the user is
          engaged with the display (DISPLAY zone focused in NORMAL mode),
          where a remount would steal focus/cursor state mid-interaction;
          content catches up on the next cycle after they leave.
        """
        if self._view_stack:
            return

        provider = self._find_provider(display_id)
        if provider is None:
            return

        get_content = getattr(provider, "get_content", None)
        if callable(get_content):
            static = self._content_static
            if static is None or not static.is_attached:
                self._show_current()
                return
            try:
                static.update(get_content())
            except Exception:
                logger.warning(
                    "DisplayProvider '%s' raised in get_content()",
                    display_id,
                    exc_info=True,
                )
            return

        if was_loading:
            self._show_current()
            return

        engaged = getattr(self._resolve_textual_app(), "display_zone_engaged", None)
        if callable(engaged):
            try:
                if engaged():
                    return
            except Exception:
                logger.warning(
                    "display_zone_engaged() raised; remounting anyway",
                    exc_info=True,
                )
        self._show_current()

    def _refresh_timeout(self, provider: DisplayProvider) -> float:
        """Per-provider refresh timeout, defaulting when unset or invalid."""
        raw: object = getattr(provider, "refresh_timeout", None)
        if not isinstance(raw, (int, float)):
            return _DEFAULT_REFRESH_TIMEOUT
        try:
            timeout = float(raw)
        except (TypeError, ValueError):
            return _DEFAULT_REFRESH_TIMEOUT
        return timeout if timeout > 0 else _DEFAULT_REFRESH_TIMEOUT

    def _executor_for(self, display_id: str) -> ThreadPoolExecutor:
        """Return (creating if needed) the single-worker executor for a display."""
        executor = self._refresh_executors.get(display_id)
        if executor is None:
            executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix=f"display-{display_id}"
            )
            self._refresh_executors[display_id] = executor
        return executor

    def _discard_executor(self, display_id: str) -> None:
        """Drop a display's executor without waiting for its hung call."""
        executor = self._refresh_executors.pop(display_id, None)
        if executor is not None:
            executor.shutdown(wait=False)

    def _stop_timer(self, display_id: str) -> None:
        """Stop and remove a refresh timer for a display."""
        timer = self._refresh_timers.pop(display_id, None)
        if timer is not None:
            timer.stop()
        self._discard_executor(display_id)
        self._refreshing.discard(display_id)

    def _stop_all_timers(self) -> None:
        """Stop all active refresh timers."""
        for display_id in list(self._refresh_timers.keys()):
            self._stop_timer(display_id)
        # Displays may have an executor without a live timer (e.g. after a
        # timeout discarded then recreated one); clear any stragglers.
        for display_id in list(self._refresh_executors.keys()):
            self._discard_executor(display_id)

    # ------------------------------------------------------------------
    # Internal — job-linked display behavior
    # ------------------------------------------------------------------

    def _apply_job_linking(self) -> None:
        """Apply job-linked auto-switch behavior based on setting.

        - "auto": switch to the related display with lowest priority.
        - "indicator": no auto-switch (caller handles indicator via HeaderItemProvider).
        - "off": no action.
        """
        if self._auto_switch_suppressed:
            return

        if self._display_auto_switch == "off":
            return

        if self._display_auto_switch == "indicator":
            # Indicator mode: the DisplaySlot doesn't auto-switch.
            # The header indicator is handled externally (HeaderItemProvider).
            return

        # "auto" mode: find the best related display and switch to it.
        target = get_auto_switch_target(
            [d.provider for d in self._visible],
            self._current_job_name,
            self._cwd,
            self._app_instance,
            self._display_auto_switch,
        )

        if target is None:
            return

        # Find the target in the visible list and switch to it.
        for i, display in enumerate(self._visible):
            if display.provider is target:
                self._visible_index = i
                self._show_current()
                break

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        """Render any providers that registered before the DOM existed.

        Registration happens in the app's ``on_mount`` and may precede this
        widget's own children finishing their mount — ``_show_current`` then
        hit ``NoMatches`` and skipped. Re-render once the tree is real.
        """
        self.call_after_refresh(self._render_initial)

    def _render_initial(self) -> None:
        if self._visible:
            self._show_current()

    def on_unmount(self) -> None:
        """Clean up all timers and refresh executors when unmounted."""
        self._stop_all_timers()
        self._refreshing.clear()
        self._loading.clear()
