"""Tests for the FunctualizeTUI app."""

from textual.screen import Screen

from functualize.app.adapters.tui import FunctualizeTUI

# --- Mock screen classes for testing (originals deleted per dead code removal) ---


class MockJobMonitorScreen(Screen):
    """Mock screen for testing registration."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]


class MockConfigViewerScreen(Screen):
    """Mock screen for testing registration."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]


class MockLogViewerScreen(Screen):
    """Mock screen for testing registration."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]


class TestFunctualizeTUI:
    """Tests for the FunctualizeTUI class."""

    def test_bindings_include_ctrl_tab(self):
        """Ctrl+Tab binding is declared for screen cycling."""
        assert ("ctrl+tab", "cycle_screen", "Next Screen") in FunctualizeTUI.BINDINGS

    def test_register_screen_stores_screen(self):
        """register_screen adds the screen class and identifier to internal list."""
        app = FunctualizeTUI()
        app.register_screen(MockJobMonitorScreen, "job-monitor")
        assert len(app._registered_screens) == 1
        assert app._registered_screens[0] == (MockJobMonitorScreen, "job-monitor")

    def test_register_screen_prevents_duplicates(self):
        """register_screen does not add duplicate identifiers."""
        app = FunctualizeTUI()
        app.register_screen(MockJobMonitorScreen, "job-monitor")
        app.register_screen(MockJobMonitorScreen, "job-monitor")
        assert len(app._registered_screens) == 1

    def test_register_multiple_screens(self):
        """Multiple different screens can be registered."""
        app = FunctualizeTUI()
        app.register_screen(MockJobMonitorScreen, "job-monitor")
        app.register_screen(MockConfigViewerScreen, "config-viewer")
        app.register_screen(MockLogViewerScreen, "log-viewer")
        assert len(app._registered_screens) == 3

    def test_cycle_screen_no_screens_does_nothing(self):
        """action_cycle_screen does nothing when no screens are registered."""
        app = FunctualizeTUI()
        # Should not raise
        app.action_cycle_screen()

    def test_initial_screen_index_is_zero(self):
        """The initial screen index starts at 0."""
        app = FunctualizeTUI()
        assert app._current_screen_index == 0


class TestMockJobMonitorScreen:
    """Tests for mock JobMonitorScreen class."""

    def test_is_screen_subclass(self):
        """MockJobMonitorScreen is a Textual Screen subclass."""
        assert issubclass(MockJobMonitorScreen, Screen)

    def test_has_escape_binding(self):
        """MockJobMonitorScreen has an escape binding to pop screen."""
        bindings = MockJobMonitorScreen.BINDINGS
        assert ("escape", "app.pop_screen", "Back") in bindings


class TestMockConfigViewerScreen:
    """Tests for mock ConfigViewerScreen class."""

    def test_is_screen_subclass(self):
        """MockConfigViewerScreen is a Textual Screen subclass."""
        assert issubclass(MockConfigViewerScreen, Screen)

    def test_has_escape_binding(self):
        """MockConfigViewerScreen has an escape binding to pop screen."""
        bindings = MockConfigViewerScreen.BINDINGS
        assert ("escape", "app.pop_screen", "Back") in bindings


class TestMockLogViewerScreen:
    """Tests for mock LogViewerScreen class."""

    def test_is_screen_subclass(self):
        """MockLogViewerScreen is a Textual Screen subclass."""
        assert issubclass(MockLogViewerScreen, Screen)

    def test_has_escape_binding(self):
        """MockLogViewerScreen has an escape binding to pop screen."""
        bindings = MockLogViewerScreen.BINDINGS
        assert ("escape", "app.pop_screen", "Back") in bindings
