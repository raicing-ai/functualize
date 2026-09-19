"""The example's two claims, asserted rather than described.

The README says `billing/` loads two plugins and `shipping/` loads one. Both
run a real boot from the child directory — the mechanism under test is *where
the loader looks*, so a test that did not move the working directory would not
exercise it at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from functualize.app import FunctualizeApp

if TYPE_CHECKING:
    import pytest

_ROOT = Path(__file__).parent.parent


def _boot(monkeypatch: pytest.MonkeyPatch, child: str) -> FunctualizeApp:
    """Boot an app from one of the child directories, as a user would."""
    monkeypatch.chdir(_ROOT / child)
    return FunctualizeApp(name=child)


def test_billing_gets_both_the_shared_and_the_declared_plugin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Declared and convention compose — declaring one does not cost the other.

    `audit-log` comes from the shared root's `.functualize/plugins/`, found by
    walking up. `timing` comes from `../team_plugins`, which only this child
    declares.
    """
    loaded = _boot(monkeypatch, "billing").plugin_loader.loaded_plugins

    assert "audit-log" in loaded, "the shared convention plugin did not load"
    assert "timing" in loaded, "the declared directory did not load"


def test_shipping_gets_only_the_shared_plugin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The falsifier for the test above.

    Without this, `billing/` loading `timing` would prove nothing — the plugin
    could be arriving from somewhere ambient rather than from the declaration.
    `shipping/` declares nothing and sits under the same root, so it isolates
    exactly one variable.
    """
    loaded = _boot(monkeypatch, "shipping").plugin_loader.loaded_plugins

    assert "audit-log" in loaded, "the shared convention plugin did not load"
    assert "timing" not in loaded, (
        "a directory only billing/ declared leaked into a sibling app"
    )


def test_the_shared_plugin_is_found_from_a_nested_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The convention directory is the project root's, not the cwd's.

    Booting from `billing/jobs/` — two levels below the root — must still find
    it. This is the case the pre-0.3.x exact-match fallback could not handle,
    and the reason the example exists.
    """
    monkeypatch.chdir(_ROOT / "billing" / "jobs")
    loaded = FunctualizeApp(name="nested").plugin_loader.loaded_plugins

    assert "audit-log" in loaded
