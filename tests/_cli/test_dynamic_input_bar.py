"""C1b.2 — `DynamicInputBar` host widget.

Two properties matter here and they pull in opposite directions:

1. The single-line path must be **unchanged** — the ordinary command bar keeps
   the same widget instance under the same parent id.
2. A mode that brings its own widget must actually get it mounted.

The second is what the host exists for; the first is what it must not break.
"""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, Static

from functualize._cli.tui.dynamic_input_bar import DynamicInputBar
from functualize.plugin import DEFAULT_SIGIL, InputMode, InputModeRegistry


def _mode(sigil: str, name: str) -> InputMode:
    return InputMode(
        sigil=sigil,
        name=name,
        candidate_source=lambda text, cursor: [],
        is_ready=lambda text: bool(text),
        submit=lambda text: None,
        history_namespace=name,
    )


def _registry() -> InputModeRegistry:
    reg = InputModeRegistry()
    reg.register(_mode(DEFAULT_SIGIL, "command"))
    reg.register(_mode("!", "shell"))
    return reg


class _HostApp(App[None]):
    """Minimal harness — the host and nothing else."""

    def __init__(self, registry: InputModeRegistry) -> None:
        super().__init__()
        self.registry = registry
        self.default_widget = Input(id="smart-bar")
        self.bar = DynamicInputBar(registry, self.default_widget, id="input-bar")

    def compose(self) -> ComposeResult:
        yield self.bar


class TestDefaultPath:
    """The bar with no extra widgets registered behaves like the old Vertical."""

    async def test_default_widget_is_the_only_child(self) -> None:
        app = _HostApp(_registry())
        async with app.run_test():
            assert list(app.bar.children) == [app.default_widget]

    async def test_default_widget_is_the_same_instance(self) -> None:
        """Not a copy, not a rebuild — every existing call site holds this one."""
        app = _HostApp(_registry())
        async with app.run_test():
            assert app.bar.active_widget is app.default_widget

    async def test_plain_text_keeps_the_default_mode(self) -> None:
        app = _HostApp(_registry())
        async with app.run_test():
            assert app.bar.sync("deploy --env prod") is False
            assert app.bar.active_sigil == DEFAULT_SIGIL
            assert list(app.bar.children) == [app.default_widget]

    async def test_a_mode_without_a_widget_does_not_swap(self) -> None:
        """`!` is registered as a *mode* but brings no widget of its own.

        This is the common case, and the reason the host does not swap
        unconditionally: the user types `!` into the bar they are already
        focused on, so replacing that widget would drop focus mid-keystroke.
        """
        app = _HostApp(_registry())
        async with app.run_test():
            assert app.bar.sync("!ls -la") is True
            assert app.bar.active_sigil == "!"
            assert app.bar.active_mode.name == "shell"
            assert app.bar.active_widget is app.default_widget
            assert list(app.bar.children) == [app.default_widget]


class TestWidgetSwap:
    """A mode that *does* register a widget gets it mounted."""

    async def test_registered_widget_is_mounted_on_activation(self) -> None:
        app = _HostApp(_registry())
        async with app.run_test() as pilot:
            app.bar.register_widget("!", lambda: Static("shell", id="shell-widget"))
            app.bar.sync("!ls")
            await pilot.pause()

            assert app.bar.active_widget.id == "shell-widget"
            assert app.bar.query_one("#shell-widget") is not None

    async def test_default_widget_hides_rather_than_unmounts(self) -> None:
        """It stays in the DOM: call sites hold a reference to it."""
        app = _HostApp(_registry())
        async with app.run_test() as pilot:
            app.bar.register_widget("!", lambda: Static("shell", id="shell-widget"))
            app.bar.sync("!ls")
            await pilot.pause()

            assert app.default_widget in app.bar.children
            assert app.default_widget.display is False

    async def test_returning_to_default_restores_the_bar(self) -> None:
        app = _HostApp(_registry())
        async with app.run_test() as pilot:
            app.bar.register_widget("!", lambda: Static("shell", id="shell-widget"))
            app.bar.sync("!ls")
            await pilot.pause()
            app.bar.sync("deploy")
            await pilot.pause()

            assert app.bar.active_sigil == DEFAULT_SIGIL
            assert app.bar.active_widget is app.default_widget
            assert app.default_widget.display is True
            assert not app.bar.query("#shell-widget")

    async def test_re_entering_a_mode_does_not_raise_duplicate_ids(self) -> None:
        """The hazard the steering doc names, exercised directly.

        The factory builds a widget with a fixed id every time. If the host
        left the previous one mounted, the second activation would collide.
        """
        app = _HostApp(_registry())
        async with app.run_test() as pilot:
            app.bar.register_widget("!", lambda: Static("shell", id="shell-widget"))
            for _ in range(3):
                app.bar.sync("!ls")
                await pilot.pause()
                app.bar.sync("deploy")
                await pilot.pause()

            assert app.bar.active_widget is app.default_widget
            assert len(app.bar.query("#shell-widget")) == 0


class TestModeAndWidgetAgree:
    """Design-scrutiny D-01 (narrowed): resolved mode == displayed widget."""

    async def test_active_mode_matches_the_text_after_every_sync(self) -> None:
        app = _HostApp(_registry())
        async with app.run_test() as pilot:
            app.bar.register_widget("!", lambda: Static("shell", id="shell-widget"))

            for text, expected_mode, expected_widget in [
                ("deploy", "command", "smart-bar"),
                ("!ls", "shell", "shell-widget"),
                ("!", "shell", "shell-widget"),
                ("build", "command", "smart-bar"),
                ("", "command", "smart-bar"),
            ]:
                app.bar.sync(text)
                await pilot.pause()
                assert app.bar.active_mode.name == expected_mode, text
                assert app.bar.active_widget.id == expected_widget, text


class TestRegistrationGuards:
    async def test_widget_for_an_unregistered_mode_is_rejected(self) -> None:
        """A widget with no mode could never be reached, so it is a mistake."""
        app = _HostApp(_registry())
        async with app.run_test():
            with pytest.raises(ValueError, match="no mode registered"):
                app.bar.register_widget("?", lambda: Static("ask"))

    async def test_duplicate_widget_registration_is_rejected(self) -> None:
        app = _HostApp(_registry())
        async with app.run_test():
            app.bar.register_widget("!", lambda: Static("shell"))
            with pytest.raises(ValueError, match="already has a widget"):
                app.bar.register_widget("!", lambda: Static("other"))
