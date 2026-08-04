"""Unit tests for entry point wiring in inline_tui.py.

Tests how launch_inline_tui() instantiates FunctualizeInlineTUI,
handles ImportError when Textual is missing, and returns exit codes.

**Validates: Requirements 19.1, 19.3, 19.4**
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

# =============================================================================
# Test 1: launch_inline_tui instantiates FunctualizeInlineTUI with provided app
# =============================================================================


class TestLaunchInstantiatesTUI:
    """Req 19.1: launch_inline_tui() instantiates FunctualizeInlineTUI with the provided app."""

    def test_instantiates_with_app(self) -> None:
        """launch_inline_tui passes the app to FunctualizeInlineTUI constructor."""
        mock_app = MagicMock()
        mock_tui_instance = MagicMock()
        mock_tui_instance.handoff_tokens = None
        mock_tui_instance.return_code = 0

        with patch(
            "functualize._cli.inline_tui.FunctualizeInlineTUI",
            create=True,
        ) as mock_class:
            # We need to patch the import inside the function
            mock_class.return_value = mock_tui_instance

            with patch.dict(
                "sys.modules",
                {
                    "functualize._cli.tui.app": MagicMock(
                        FunctualizeInlineTUI=mock_class
                    )
                },
            ):
                from functualize._cli.inline_tui import launch_inline_tui

                launch_inline_tui(mock_app)

                mock_class.assert_called_once_with(mock_app)

    def test_calls_run_inline_true(self) -> None:
        """launch_inline_tui calls .run(inline=True) on the TUI instance."""
        mock_app = MagicMock()
        mock_tui_instance = MagicMock()
        mock_tui_instance.handoff_tokens = None
        mock_tui_instance.return_code = 0

        mock_class = MagicMock(return_value=mock_tui_instance)

        with patch.dict(
            "sys.modules",
            {"functualize._cli.tui.app": MagicMock(FunctualizeInlineTUI=mock_class)},
        ):
            from functualize._cli.inline_tui import launch_inline_tui

            launch_inline_tui(mock_app)

            mock_tui_instance.run.assert_called_once_with(inline=True)


# =============================================================================
# Test 2: ImportError raised when Textual is missing
# =============================================================================


class TestImportErrorWhenTextualMissing:
    """Req 19.4: ImportError raised with correct message when Textual is missing."""

    def test_import_error_raised(self) -> None:
        """launch_inline_tui raises ImportError when tui.app cannot be imported."""
        import sys

        mock_app = MagicMock()

        # Remove the module from sys.modules if cached, then patch import to fail
        saved = sys.modules.pop("functualize._cli.tui.app", None)
        try:
            with patch.dict("sys.modules", {"functualize._cli.tui.app": None}):
                # Force re-import of inline_tui to get fresh function
                saved_inline = sys.modules.pop("functualize._cli.inline_tui", None)
                try:
                    import pytest

                    from functualize._cli.inline_tui import launch_inline_tui

                    with pytest.raises(ImportError, match=r"functualize\[cli\]"):
                        launch_inline_tui(mock_app)
                finally:
                    if saved_inline is not None:
                        sys.modules["functualize._cli.inline_tui"] = saved_inline
        finally:
            if saved is not None:
                sys.modules["functualize._cli.tui.app"] = saved

    def test_import_error_message_contains_install_instructions(self) -> None:
        """ImportError message directs user to install functualize[cli]."""
        import sys

        mock_app = MagicMock()

        saved = sys.modules.pop("functualize._cli.tui.app", None)
        try:
            with patch.dict("sys.modules", {"functualize._cli.tui.app": None}):
                saved_inline = sys.modules.pop("functualize._cli.inline_tui", None)
                try:
                    import pytest

                    from functualize._cli.inline_tui import launch_inline_tui

                    with pytest.raises(ImportError) as exc_info:
                        launch_inline_tui(mock_app)

                    assert "functualize[cli]" in str(exc_info.value)
                    assert "pip install" in str(exc_info.value)
                finally:
                    if saved_inline is not None:
                        sys.modules["functualize._cli.inline_tui"] = saved_inline
        finally:
            if saved is not None:
                sys.modules["functualize._cli.tui.app"] = saved


# =============================================================================
# Test 3: Exit code returned from the Textual app
# =============================================================================


class TestExitCodeReturned:
    """Req 19.3: Exit code is returned from the Textual app."""

    def test_returns_exit_code_42(self) -> None:
        """launch_inline_tui returns the TUI's return_code."""
        mock_app = MagicMock()
        mock_tui_instance = MagicMock()
        mock_tui_instance.handoff_tokens = None
        mock_tui_instance.return_code = 42

        mock_class = MagicMock(return_value=mock_tui_instance)

        with patch.dict(
            "sys.modules",
            {"functualize._cli.tui.app": MagicMock(FunctualizeInlineTUI=mock_class)},
        ):
            from functualize._cli.inline_tui import launch_inline_tui

            result = launch_inline_tui(mock_app)

            assert result == 42

    def test_returns_0_when_return_code_is_none(self) -> None:
        """launch_inline_tui returns 0 when TUI's return_code is None."""
        mock_app = MagicMock()
        mock_tui_instance = MagicMock()
        mock_tui_instance.handoff_tokens = None
        mock_tui_instance.return_code = None

        mock_class = MagicMock(return_value=mock_tui_instance)

        with patch.dict(
            "sys.modules",
            {"functualize._cli.tui.app": MagicMock(FunctualizeInlineTUI=mock_class)},
        ):
            from functualize._cli.inline_tui import launch_inline_tui

            result = launch_inline_tui(mock_app)

            assert result == 0

    def test_returns_0_when_return_code_is_zero(self) -> None:
        """launch_inline_tui returns 0 when TUI's return_code is 0."""
        mock_app = MagicMock()
        mock_tui_instance = MagicMock()
        mock_tui_instance.handoff_tokens = None
        mock_tui_instance.return_code = 0

        mock_class = MagicMock(return_value=mock_tui_instance)

        with patch.dict(
            "sys.modules",
            {"functualize._cli.tui.app": MagicMock(FunctualizeInlineTUI=mock_class)},
        ):
            from functualize._cli.inline_tui import launch_inline_tui

            result = launch_inline_tui(mock_app)

            assert result == 0
