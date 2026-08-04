"""DynamicInputBar — the input row's host, one content region per active mode.

The input row used to be a bare ``Vertical`` wrapping a single ``SmartBar``.
That is fine while the bar does exactly one thing, but ``!`` (run a shell
command) and a future ``?`` (ask) are not variations on typing a command: they
change what completion offers, what "ready" means, and where history goes. This
widget is the seam where the *active* mode is decided and, if that mode brings
its own widget, where it gets mounted.

Two rules shape the design:

**A mode does not have to bring a widget.** The registry's modes live in
``_types/input_modes.py``, which cannot import Textual, so a mode carries
behavior only. A widget is registered *here*, against a sigil, and most modes
will never want one — ``!`` is still a single line of text, and the user types
``!`` *into the bar they are already focused on*. Swapping the widget out from
under that keystroke would drop focus and the cursor mid-word. So the default
widget stays mounted unless a mode explicitly registers its own factory.

**The resolved mode and the mounted widget must not disagree.** Everything
downstream — candidates, readiness, submit — is looked up from the mode the
registry resolves for the current text. If the host let those drift apart, the
bar would offer one mode's completions to another mode's widget. :meth:`sync`
is the only thing that moves either, which is what keeps them in step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Vertical

if TYPE_CHECKING:
    from collections.abc import Callable

    from textual.app import ComposeResult
    from textual.widget import Widget

    from functualize.plugin import InputMode, InputModeRegistry

__all__ = ["DynamicInputBar"]


class DynamicInputBar(Vertical):
    """Hosts the input row and swaps in the active mode's widget.

    Args:
        registry: Resolves text to an :class:`InputMode`. The host never
            registers modes itself — the shell owns that.
        default_widget: The widget for the default (command) mode. Mounted at
            compose time and never destroyed, so the ordinary path keeps the
            exact widget instance every existing call site already holds.
    """

    def __init__(
        self,
        registry: InputModeRegistry,
        default_widget: Widget,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._registry = registry
        self._default_widget = default_widget
        self._widget_factories: dict[str, Callable[[], Widget]] = {}
        self._active_sigil: str = ""
        self._mode_widget: Widget | None = None

    def compose(self) -> ComposeResult:
        """Mount the default mode's widget.

        This is the whole of the single-line path: one child, the same
        ``SmartBar`` instance as before, under the same ``#input-bar`` parent.
        """
        yield self._default_widget

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_widget(self, sigil: str, factory: Callable[[], Widget]) -> None:
        """Give ``sigil`` its own widget, built on first activation.

        A factory rather than an instance: a mode that is never entered should
        not cost a constructed widget, and re-entering a mode after leaving it
        needs a fresh one (Textual will not re-mount a removed widget).

        Raises:
            ValueError: ``sigil`` has no registered mode (a widget with no mode
                could never be reached), or already has a widget.
        """
        if sigil not in self._registry:
            raise ValueError(
                f"no mode registered for sigil {sigil!r}; register the mode "
                f"before its widget"
            )
        if sigil in self._widget_factories:
            raise ValueError(f"sigil {sigil!r} already has a widget registered")
        self._widget_factories[sigil] = factory

    # ------------------------------------------------------------------
    # Mode activation
    # ------------------------------------------------------------------

    @property
    def active_sigil(self) -> str:
        """Sigil of the mode currently active."""
        return self._active_sigil

    @property
    def active_mode(self) -> InputMode | None:
        """The mode currently active, or None if no default is registered."""
        return self._registry.get(self._active_sigil)

    @property
    def active_widget(self) -> Widget:
        """The widget the active mode is using.

        The default widget unless the active mode registered its own — see the
        module docstring on why most modes will not.
        """
        return (
            self._mode_widget if self._mode_widget is not None else self._default_widget
        )

    def sync(self, text: str) -> bool:
        """Point the host at the mode owning ``text``. Returns True if it changed.

        Called on every input change, so the common case — same mode as last
        keystroke — must do nothing at all, and does: the sigil comparison
        short-circuits before any DOM work.
        """
        mode = self._registry.resolve(text)
        sigil = mode.sigil if mode is not None else ""
        if sigil == self._active_sigil:
            return False
        self._activate(sigil)
        return True

    def _activate(self, sigil: str) -> None:
        """Swap to ``sigil``'s widget, if it has one.

        Mount and unmount both go through Textual's own calls rather than
        touching ``children`` — per the steering doc's HARD rules, DOM changes
        belong on the message pump. ``remove()`` before ``mount()`` is what
        keeps a re-entered mode from raising ``DuplicateIds``: the factory
        builds a fresh widget each time, but a stale one left mounted would
        collide with it on id.
        """
        if self._mode_widget is not None:
            self._mode_widget.remove()
            self._mode_widget = None

        factory = self._widget_factories.get(sigil)
        if factory is not None:
            widget = factory()
            self._mode_widget = widget
            self.mount(widget)
            self._default_widget.display = False
        else:
            self._default_widget.display = True

        self._active_sigil = sigil
