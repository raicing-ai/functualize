"""Tests for the ambient-construct mechanism (item 1a).

Ambient constructs are plugin-provided live constructs that render by default
for eligible jobs, with no job-author code. These tests cover registration,
predicate gating, the suppression levers, and the fresh-state-per-run
guarantee that registering a *factory* (not an instance) exists to provide.
"""

from __future__ import annotations

from typing import Any

import pytest

from functualize._engine.ambient import (
    has_eligible_ambient,
    resolve_ambient_constructs,
    suppressed_names,
)
from functualize.app.core import FunctualizeApp


class _Construct:
    name = "demo"

    def __init__(self) -> None:
        self.state: list[str] = []

    def __rich__(self) -> str:
        return "demo"


class _Descriptor:
    def __init__(self, **kwargs: Any) -> None:
        self.uses_invoke = kwargs.get("uses_invoke", False)
        self.suppress_live = kwargs.get("suppress_live")


@pytest.fixture()
def app() -> FunctualizeApp:
    """An app with no ambient constructs registered.

    Installed plugins auto-register theirs at boot (flow-viz does), so the
    registry is cleared here to test the mechanism itself rather than
    whatever happens to be installed.
    """
    instance = FunctualizeApp(name="ambientapp")
    instance._ambient_constructs = []
    return instance


# ─── Registration ─────────────────────────────────────────────────────


def test_registered_construct_resolves_for_a_job(app: FunctualizeApp) -> None:
    app.register_ambient_construct(_Construct)

    resolved = resolve_ambient_constructs(app, _Descriptor())

    assert len(resolved) == 1
    assert isinstance(resolved[0], _Construct)


def test_no_registrations_resolves_empty(app: FunctualizeApp) -> None:
    assert resolve_ambient_constructs(app, _Descriptor()) == []
    assert has_eligible_ambient(app, _Descriptor()) is False


def test_each_resolution_yields_a_fresh_instance(app: FunctualizeApp) -> None:
    """State from one run must never bleed into the next."""
    app.register_ambient_construct(_Construct)

    first = resolve_ambient_constructs(app, _Descriptor())[0]
    first.state.append("from-run-1")
    second = resolve_ambient_constructs(app, _Descriptor())[0]

    assert second.state == []
    assert first is not second


def test_registering_an_instance_is_rejected(app: FunctualizeApp) -> None:
    """An instance would share state across runs — reject it loudly."""
    with pytest.raises(TypeError, match="factory"):
        app.register_ambient_construct(_Construct())  # type: ignore[arg-type]


def test_registration_is_idempotent_by_name(app: FunctualizeApp) -> None:
    """A plugin loaded twice must not double-render its construct."""
    app.register_ambient_construct(_Construct)
    app.register_ambient_construct(_Construct)

    assert len(resolve_ambient_constructs(app, _Descriptor())) == 1


def test_name_defaults_to_the_factory_name_attribute(app: FunctualizeApp) -> None:
    app.register_ambient_construct(_Construct)

    assert suppressed_names(app, _Descriptor(suppress_live=["demo"])) == {"demo"}
    assert resolve_ambient_constructs(app, _Descriptor(suppress_live=["demo"])) == []


# ─── Predicates ───────────────────────────────────────────────────────


def test_predicate_gates_resolution(app: FunctualizeApp) -> None:
    app.register_ambient_construct(
        _Construct, predicate=lambda d: getattr(d, "uses_invoke", False)
    )

    assert resolve_ambient_constructs(app, _Descriptor(uses_invoke=False)) == []
    assert len(resolve_ambient_constructs(app, _Descriptor(uses_invoke=True))) == 1


def test_a_raising_predicate_is_treated_as_not_eligible(
    app: FunctualizeApp,
) -> None:
    """A buggy plugin predicate must not break job execution."""

    def boom(descriptor: Any) -> bool:
        raise RuntimeError("bad predicate")

    app.register_ambient_construct(_Construct, predicate=boom)

    assert resolve_ambient_constructs(app, _Descriptor()) == []


def test_a_raising_factory_costs_only_its_own_construct(
    app: FunctualizeApp,
) -> None:
    class _Broken:
        name = "broken"

        def __init__(self) -> None:
            raise RuntimeError("cannot build")

    app.register_ambient_construct(_Broken)
    app.register_ambient_construct(_Construct)

    resolved = resolve_ambient_constructs(app, _Descriptor())

    assert len(resolved) == 1
    assert isinstance(resolved[0], _Construct)


# ─── Suppression levers ───────────────────────────────────────────────


def test_job_declaration_suppresses(app: FunctualizeApp) -> None:
    """@job(suppress_live=[...]) → descriptor.suppress_live."""
    app.register_ambient_construct(_Construct)

    assert resolve_ambient_constructs(app, _Descriptor(suppress_live=["demo"])) == []


def test_job_declaration_accepts_a_bare_string(app: FunctualizeApp) -> None:
    app.register_ambient_construct(_Construct)

    assert resolve_ambient_constructs(app, _Descriptor(suppress_live="demo")) == []


def test_suppressing_a_different_name_leaves_it_mounted(
    app: FunctualizeApp,
) -> None:
    app.register_ambient_construct(_Construct)

    assert (
        len(resolve_ambient_constructs(app, _Descriptor(suppress_live=["other"]))) == 1
    )


def test_config_suppresses(
    app: FunctualizeApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[live] suppress = ["demo"] in project config."""

    class _Settings:
        def get(self, key: str, default: Any = None) -> Any:
            return ["demo"] if key == "live.suppress" else default

    monkeypatch.setattr(app, "settings", _Settings(), raising=False)
    app.register_ambient_construct(_Construct)

    assert resolve_ambient_constructs(app, _Descriptor()) == []


def test_config_suppress_accepts_a_comma_string(
    app: FunctualizeApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Settings:
        def get(self, key: str, default: Any = None) -> Any:
            return "demo, other" if key == "live.suppress" else default

    monkeypatch.setattr(app, "settings", _Settings(), raising=False)
    app.register_ambient_construct(_Construct)

    assert resolve_ambient_constructs(app, _Descriptor()) == []


# ─── has_eligible_ambient (the CLI's surface gate) ────────────────────


def test_has_eligible_ambient_tracks_predicate_and_suppression(
    app: FunctualizeApp,
) -> None:
    app.register_ambient_construct(
        _Construct, predicate=lambda d: getattr(d, "uses_invoke", False)
    )

    assert has_eligible_ambient(app, _Descriptor(uses_invoke=True)) is True
    assert has_eligible_ambient(app, _Descriptor(uses_invoke=False)) is False
    assert (
        has_eligible_ambient(app, _Descriptor(uses_invoke=True, suppress_live=["demo"]))
        is False
    )
