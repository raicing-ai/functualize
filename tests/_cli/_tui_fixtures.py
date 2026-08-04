"""Shared real-app Pilot fixture for TUI tests.

Promotes the ``tui_app`` fixture recipe proven in
``tests/tui_audit/test_modal_key_leak.py`` into a single, reusable
location so multiple test files can spin up a real, XDG-isolated
``FunctualizeInlineTUI`` instance without duplicating the isolation
boilerplate (``XDG_DATA_HOME`` monkeypatch + ``chdir(tmp_path)`` + a
registered dynamic job).

Usage — import the fixture (and/or the factory) by name into a test
module::

    from tests._cli._tui_fixtures import make_tui_app, tui_app

pytest recognizes any ``@pytest.fixture``-decorated object present in a
test module's namespace as a fixture for that module, regardless of where
it was originally defined — no ``conftest.py`` registration is required
for this promotion.

Consumers (as of):
- ``tests/_cli/test_mode_transition_pilot.py`` (T-011/)
- ``tests/tui_audit/test_modal_key_leak.py`` (T-013 promotion origin)
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from functualize._cli.tui.app import FunctualizeInlineTUI
from functualize.app.core import FunctualizeApp


def make_tui_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_name: str = "testapp",
    jobs: dict[str, Callable[..., Any]] | None = None,
) -> FunctualizeInlineTUI:
    """Build a real, XDG-isolated ``FunctualizeInlineTUI`` instance.

    Args:
        tmp_path: pytest ``tmp_path`` fixture value — isolates
            ``$XDG_DATA_HOME`` and the current working directory so the TUI
            never touches the developer's real home/config.
        monkeypatch: pytest ``monkeypatch`` fixture value.
        app_name: name passed to ``FunctualizeApp(name=...)``.
        jobs: optional ``{job_name: callable}`` mapping to register as
            dynamic jobs. Defaults to a single no-op ``greet(name="world")``
            job (never executed — dynamic jobs currently yield no field
            defs, so this default is only suitable for SmartBar/keymap/modal
            flows, not panel-field flows; see
            ``contributor/guides/steering_textual_tui.md`` §4.2).

    Returns:
        A constructed (not yet mounted/run) ``FunctualizeInlineTUI``.
    """
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)

    func_app = FunctualizeApp(name=app_name)

    if jobs is None:

        def greet(name: str = "world") -> None:  # pragma: no cover - never run
            pass

        jobs = {"greet": greet}

    for job_name, fn in jobs.items():
        func_app.register_dynamic_job(job_name, fn)

    return FunctualizeInlineTUI(func_app)


@pytest.fixture()
def tui_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FunctualizeInlineTUI:
    """Default real-app fixture: a single ``greet`` dynamic job, XDG-isolated."""
    return make_tui_app(tmp_path, monkeypatch)
