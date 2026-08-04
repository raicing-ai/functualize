"""The autocomplete ImportError placeholder must degrade, not crash.

When textual-autocomplete is missing, functualize_autocomplete falls back
to a placeholder. app.compose() yields it, so it must be a mountable
Widget — a plain object turns every TUI start into a MountError.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
import textwrap

import pytest

try:
    import textual  # noqa: F401

    HAS_TEXTUAL = True
except ImportError:
    HAS_TEXTUAL = False

pytestmark = [
    pytest.mark.skipif(not HAS_TEXTUAL, reason="textual not available"),
]


@pytest.fixture()
def placeholder_module():
    """Reload functualize_autocomplete with textual_autocomplete blocked."""
    import functualize._cli.tui.functualize_autocomplete as module

    blocked = {
        name: sys.modules.pop(name)
        for name in list(sys.modules)
        if name.startswith("textual_autocomplete")
    }
    # A None sys.modules entry makes `import textual_autocomplete` raise
    sys.modules["textual_autocomplete"] = None  # type: ignore[assignment]
    try:
        importlib.reload(module)
        yield module
    finally:
        del sys.modules["textual_autocomplete"]
        sys.modules.update(blocked)
        importlib.reload(module)


class TestPlaceholderClass:
    """Unit checks on the degraded placeholder."""

    def test_placeholder_is_a_widget(self, placeholder_module) -> None:
        from textual.widget import Widget

        instance = placeholder_module.FunctualizeAutoComplete("anything", extra=1)
        assert isinstance(instance, Widget)
        assert instance.display is False

    def test_placeholder_noop_surface(self, placeholder_module) -> None:
        instance = placeholder_module.FunctualizeAutoComplete()
        instance.suppress()
        instance.unsuppress()
        instance.enter_insert_mode(["a", "b"])
        instance.exit_insert_mode()
        instance.refresh_dropdown()
        instance.accept_highlighted()
        instance.action_hide()
        assert instance.option_list.option_count == 0


class TestAppMountsWithoutAutocomplete:
    """The full TUI mounts under Pilot with textual-autocomplete missing."""

    def test_inline_tui_mounts(self, tmp_path) -> None:
        script = textwrap.dedent(
            """
            import asyncio
            import sys

            # Block textual_autocomplete before any functualize import
            sys.modules["textual_autocomplete"] = None

            from functualize.app.core import FunctualizeApp
            from functualize._cli.tui.app import FunctualizeInlineTUI
            from functualize._cli.tui.functualize_autocomplete import (
                FunctualizeAutoComplete,
            )

            async def main() -> None:
                app = FunctualizeInlineTUI(FunctualizeApp(name="placeholder-test"))
                async with app.run_test() as pilot:
                    await pilot.pause()
                    ac = pilot.app.query_one(FunctualizeAutoComplete)
                    assert ac.display is False
                print("MOUNT_OK")

            asyncio.run(main())
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"TUI failed to mount without textual-autocomplete:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "MOUNT_OK" in result.stdout
