"""Every facade is reachable, typed, and built once.

`engine-sealed-construction` T8 and T9 split `RunContext` (800 → 256 executable)
and `FunctualizeApp` (632 → 298) by grouping members behind facades. Ten of
them. Each is reached through a lazily-built accessor, and each accessor is
three lines that nothing would notice the absence of: the members are exercised
by the rest of the suite *through* the accessor, so a broken one shows up as a
hundred unrelated failures rather than as one clear answer.

This file is the one clear answer. It also makes T11's orphan scan mean
something — every facade class is named here, so "referenced" is not just
"imported by the accessor that builds it".

**Built once.** A facade holds nothing but a back-reference, so rebuilding one
is harmless — but a job that does `rc.events.on_event(...)` twice and gets two
objects would be registering against two different things if that ever stopped
being true. The identity assertion is cheap and pins the intent.
"""

from __future__ import annotations

import pytest

from functualize._app.configuration_facade import ConfigurationFacade
from functualize._app.di_facade import DependencyFacade
from functualize._app.extensions_facade import ExtensionsFacade
from functualize._app.gates_facade import GatesFacade
from functualize._app.hooks_facade import HooksFacade
from functualize._app.workflow_facade import WorkflowScopeFacade
from functualize._engine.capabilities.discovery_facade import DiscoveryFacade
from functualize._engine.capabilities.observability_facade import ObservabilityFacade
from functualize._engine.capabilities.prompt_facade import PromptFacade
from functualize._engine.capabilities.runcontext import RunContext
from functualize._engine.capabilities.wiring_facade import WiringFacade
from functualize.app.core import FunctualizeApp

_APP_FACADES = [
    ("hooks", HooksFacade),
    ("extensions", ExtensionsFacade),
    ("configuration", ConfigurationFacade),
    ("gates", GatesFacade),
    ("di", DependencyFacade),
    ("workflows", WorkflowScopeFacade),
]

_RC_FACADES = [
    ("events", ObservabilityFacade),
    ("prompts", PromptFacade),
    ("discovery", DiscoveryFacade),
    ("wiring", WiringFacade),
]


@pytest.fixture
def app() -> FunctualizeApp:
    return FunctualizeApp(name="facades")


@pytest.fixture
def rc(app: FunctualizeApp) -> RunContext:
    import logging

    from functualize._config.job_config import JobConfigView

    return RunContext(
        name="probe",
        config=JobConfigView(resolution_chain=app.resolution_chain()),
        logger=logging.getLogger("probe"),
    )


class TestTheAppsFacades:
    @pytest.mark.parametrize(
        ("accessor", "facade"), _APP_FACADES, ids=[a for a, _ in _APP_FACADES]
    )
    def test_it_is_reachable_and_typed(
        self, app: FunctualizeApp, accessor: str, facade: type
    ) -> None:
        assert isinstance(getattr(app, accessor), facade)

    @pytest.mark.parametrize(
        ("accessor", "_facade"), _APP_FACADES, ids=[a for a, _ in _APP_FACADES]
    )
    def test_it_is_built_once(
        self, app: FunctualizeApp, accessor: str, _facade: type
    ) -> None:
        assert getattr(app, accessor) is getattr(app, accessor)

    def test_it_points_back_at_its_own_app(self, app: FunctualizeApp) -> None:
        """A facade holds one app, and it is the one you asked."""
        other = FunctualizeApp(name="other")

        assert app.hooks._app is app
        assert other.hooks._app is other


class TestTheRunContextsFacades:
    @pytest.mark.parametrize(
        ("accessor", "facade"), _RC_FACADES, ids=[a for a, _ in _RC_FACADES]
    )
    def test_it_is_reachable_and_typed(
        self, rc: RunContext, accessor: str, facade: type
    ) -> None:
        assert isinstance(getattr(rc, accessor), facade)

    @pytest.mark.parametrize(
        ("accessor", "_facade"), _RC_FACADES, ids=[a for a, _ in _RC_FACADES]
    )
    def test_it_is_built_once(
        self, rc: RunContext, accessor: str, _facade: type
    ) -> None:
        assert getattr(rc, accessor) is getattr(rc, accessor)


def test_the_moved_members_are_not_still_on_their_old_owner() -> None:
    """No aliases. Pre-alpha, and the constitution says delete rather than shim.

    Named one per facade rather than exhaustively — the point is that the move
    was a move, not an addition, and one survivor per group would prove it was
    not.
    """
    gone_from_app = [
        "on_job_failure",
        "register_surface",
        "config_files",
        "resolve_gate",
        "provide",
        "create_workflow_scope",
    ]
    gone_from_rc = ["emit", "prompt_confirm", "get_job_schema", "get_plugin_config"]

    assert not [n for n in gone_from_app if hasattr(FunctualizeApp, n)]
    assert not [n for n in gone_from_rc if hasattr(RunContext, n)]


def test_every_facade_class_is_named_here() -> None:
    """The falsifier for T11's orphan scan.

    A facade added without a row above is a class referenced only by the
    accessor that builds it — which is what "orphan" means for this shape.
    """
    import pathlib

    roots = [
        pathlib.Path(__file__).resolve().parents[2] / "src" / "functualize" / "_app",
        pathlib.Path(__file__).resolve().parents[2]
        / "src"
        / "functualize"
        / "_engine"
        / "capabilities",
    ]
    on_disk = {p.stem for root in roots for p in root.glob("*_facade.py")}
    covered = {
        "hooks_facade",
        "extensions_facade",
        "configuration_facade",
        "gates_facade",
        "di_facade",
        "workflow_facade",
        "observability_facade",
        "prompt_facade",
        "discovery_facade",
        "wiring_facade",
    }

    assert on_disk == covered, f"facade modules not covered here: {on_disk - covered}"
