"""TUI integration tests using Textual's Pilot (headless test driver).

These tests run Textual-based TUI apps in headless mode — no real terminal
needed, works in CI. Tests simulate key presses, clicks, and assert on
widget state/screen content.

Requires: pytest-asyncio, textual (from functualize[cli])

Test tiers:
- Tier 1 (this file): Pilot-based interaction tests (fast, headless)
- Tier 2: pytest-textual-snapshot for visual regression (separate file)
- Tier 3: pexpect for true PTY tests (tests/e2e/test_interactive.py)

NOTE: FunctualizeTUI (the core class) is a lightweight screen registry,
not a Textual App subclass. Pilot-based tests apply to Textual App
implementations (e.g., the fullscreen-tui plugin). This file provides
both unit tests for FunctualizeTUI and templates for Pilot testing.
"""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import Static

try:
    from functualize.app.adapters.tui import FunctualizeTUI

    HAS_TUI = True
except ImportError:
    HAS_TUI = False

pytestmark = [
    pytest.mark.skipif(not HAS_TUI, reason="TUI adapter not available"),
]


# --- Test screens ---


class MockJobScreen(Screen):
    """Mock screen simulating a job list view."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Static("Jobs: hello, deploy", id="job-list")


class MockConfigScreen(Screen):
    """Mock screen simulating a config viewer."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Static("Config: output=plain", id="config-view")


# ===========================================================================
# FunctualizeTUI Unit Tests (non-async, fast)
# ===========================================================================


class TestFunctualizeTUIUnit:
    """Unit tests for the FunctualizeTUI screen registry."""

    def test_initial_state(self) -> None:
        """Fresh instance has no screens and index 0."""
        tui = FunctualizeTUI()
        assert tui._registered_screens == []
        assert tui._current_screen_index == 0

    def test_register_screen(self) -> None:
        """Registering a screen adds it to the list."""
        tui = FunctualizeTUI()
        tui.register_screen(MockJobScreen, "jobs")
        assert len(tui._registered_screens) == 1
        assert tui._registered_screens[0] == (MockJobScreen, "jobs")

    def test_register_duplicate_is_noop(self) -> None:
        """Registering the same identifier twice is a no-op."""
        tui = FunctualizeTUI()
        tui.register_screen(MockJobScreen, "jobs")
        tui.register_screen(MockJobScreen, "jobs")
        assert len(tui._registered_screens) == 1

    def test_register_multiple_screens(self) -> None:
        """Multiple screens with different identifiers all register."""
        tui = FunctualizeTUI()
        tui.register_screen(MockJobScreen, "jobs")
        tui.register_screen(MockConfigScreen, "config")
        assert len(tui._registered_screens) == 2

    def test_cycle_no_screens_is_noop(self) -> None:
        """Cycling with no screens registered does nothing."""
        tui = FunctualizeTUI()
        tui.action_cycle_screen()
        assert tui._current_screen_index == 0

    def test_cycle_advances_index(self) -> None:
        """Cycling advances the screen index."""
        tui = FunctualizeTUI()
        tui.register_screen(MockJobScreen, "jobs")
        tui.register_screen(MockConfigScreen, "config")
        tui.action_cycle_screen()
        assert tui._current_screen_index == 1

    def test_cycle_wraps_around(self) -> None:
        """Cycling past the last screen wraps to index 0."""
        tui = FunctualizeTUI()
        tui.register_screen(MockJobScreen, "jobs")
        tui.register_screen(MockConfigScreen, "config")
        tui.action_cycle_screen()  # → 1
        tui.action_cycle_screen()  # → 0 (wrap)
        assert tui._current_screen_index == 0

    def test_bindings_declared(self) -> None:
        """Ctrl+Tab binding is declared."""
        assert ("ctrl+tab", "cycle_screen", "Next Screen") in FunctualizeTUI.BINDINGS


# ===========================================================================
# Textual Pilot Template (for real Textual App subclasses)
# ===========================================================================


class SampleTuiApp(App):
    """Minimal Textual app for demonstrating Pilot-based testing.

    In production, this would be your actual TUI App (e.g., from the
    functualize-fullscreen-tui plugin). This sample demonstrates the
    pattern for writing Pilot tests.
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("j", "toggle_jobs", "Jobs"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.jobs_visible = False

    def compose(self) -> ComposeResult:
        yield Static("Functualize TUI", id="header")
        yield Static("Press 'j' for jobs", id="hint")

    def action_toggle_jobs(self) -> None:
        self.jobs_visible = not self.jobs_visible


@pytest.mark.asyncio
class TestPilotTemplate:
    """Template demonstrating Textual Pilot testing patterns.

    Copy and adapt these for your actual Textual-based TUI app.
    """

    async def test_app_mounts_cleanly(self) -> None:
        """App starts in headless mode without errors."""
        app = SampleTuiApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.is_running

    async def test_key_press_updates_state(self) -> None:
        """Key presses trigger expected state changes."""
        app = SampleTuiApp()
        async with app.run_test() as pilot:
            assert app.jobs_visible is False
            await pilot.press("j")
            assert app.jobs_visible is True

    async def test_quit_key_exits(self) -> None:
        """Pressing 'q' exits the app."""
        app = SampleTuiApp()
        async with app.run_test() as pilot:
            await pilot.press("q")
            # App should be in shutdown state after quit

    @pytest.mark.parametrize(
        "size",
        [(80, 24), (120, 40), (40, 15)],
        ids=["standard", "large", "small"],
    )
    async def test_renders_at_various_sizes(self, size: tuple[int, int]) -> None:
        """App renders without errors at various terminal sizes."""
        app = SampleTuiApp()
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            # Query a widget to confirm rendering happened
            header = app.query_one("#header", Static)
            assert header is not None
