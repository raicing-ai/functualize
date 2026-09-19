"""`PluginHost` describes the app that ships — AC-3, AC-1b.

Three claims, and the first two are separate on purpose.

**Runtime.** `isinstance(app, PluginHost)` is True. That proves the eleven
names exist and nothing more: a `@runtime_checkable` Protocol's `isinstance`
ignores signatures entirely, so an app whose `execute` took different arguments
would still pass it.

**Static.** mypy accepts handing a real `FunctualizeApp` to a `PluginHost`
parameter, which is the check that compares signature to signature. `tasks.md`
asked for both and said why: *"Runtime alone proves member presence, never
signatures."*

**Shape.** The port's members, and each view's, are pinned. A port grows by
someone adding a member, and the argument for every member here is a measured
client count -- so growth should be a line in this file that a reviewer sees,
not a quiet widening. This is also what keeps `substrate_override` and
`hook_registry` off it: both were argued out in `contracts.md` §1, and an
assertion is how that argument survives the next person who needs one of them.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from functualize._types.host import (
    ConfigurationView,
    DependencyView,
    ExtensionsView,
    GatesView,
    HooksView,
    PluginHost,
)
from functualize.app.core import FunctualizeApp

if TYPE_CHECKING:
    from collections.abc import Iterable

FIXTURE = Path(__file__).parent / "fixtures" / "plugin_host_conformance.py"

#: The eleven members of `contracts.md` §1, in that document's order.
PORT_MEMBERS = {
    "di",
    "extensions",
    "configuration",
    "gates",
    "hooks",
    "get_jobs",
    "get_job",
    "execute",
    "substrate",
    "install_substrate",
    "fresh_root",
}

#: Each view, sized to the plugin census in `contracts.md` §2.
VIEW_MEMBERS: dict[str, set[str]] = {
    "DependencyView": {"provide", "provide_named"},
    "ExtensionsView": {
        "register_plugin_command",
        "extension_state",
        "register_surface",
        "register_ambient_construct",
    },
    "ConfigurationView": {"resolve_model"},
    "GatesView": {"register_gate_preset", "register_gate_strategy"},
    "HooksView": {"on_ready"},
}

_VIEWS: dict[str, type[Any]] = {
    "DependencyView": DependencyView,
    "ExtensionsView": ExtensionsView,
    "ConfigurationView": ConfigurationView,
    "GatesView": GatesView,
    "HooksView": HooksView,
}


def _members(protocol: type[Any]) -> set[str]:
    """A Protocol's declared members, across the Pythons this project supports.

    `__protocol_attrs__` is 3.12+; `typing._get_protocol_attrs` is the 3.11
    spelling. `requires-python = ">=3.11"`, so both have to work -- and reading
    `__annotations__` instead would miss every method and property, which is
    all of them.
    """
    attrs = getattr(protocol, "__protocol_attrs__", None)
    if attrs is not None:
        return set(attrs)
    from typing import _get_protocol_attrs  # type: ignore[attr-defined]

    return set(_get_protocol_attrs(protocol))


class TestTheShippedAppSatisfiesThePort:
    def test_at_runtime(self) -> None:
        """Member presence -- and only that. See this file's docstring."""
        assert isinstance(FunctualizeApp(name="probe"), PluginHost)

    def test_under_mypy(self) -> None:
        """Signatures. The half `isinstance` is blind to.

        Warm `.mypy_cache` makes this about a second; cold it is ~15 s, and it
        is still not marked slow, because a gate that skips reads as a pass.
        """
        api = pytest.importorskip("mypy.api", reason="mypy is a dev dependency")
        out, _err, _code = api.run(["--strict", str(FIXTURE)])
        errors = [
            line for line in out.splitlines() if re.match(r"^.*?:\d+: error:", line)
        ]
        assert not errors, (
            "FunctualizeApp no longer satisfies PluginHost, signature for "
            "signature:\n" + "\n".join(errors)
        )


class TestThePortsShapeIsPinned:
    def test_the_port_has_exactly_its_eleven_members(self) -> None:
        assert _members(PluginHost) == PORT_MEMBERS

    def test_the_excluded_members_stay_excluded(self) -> None:
        """Each of these was argued off the port, with a reason, in `contracts.md`.

        `hook_registry` because four of its seven methods *fire* lifecycle
        events -- on the port, every plugin could fire them at every other.
        `execution_engine` because it had one real client after T4 collapsed
        the substrate chain. `run` because a plugin calling the CLI entrypoint
        re-enters delivery from inside delivery. `substrate_override` because
        the install slot is the engine's business, not a plugin's -- a plugin
        installs through `install_substrate` and reads through `substrate`.
        """
        forbidden = {
            "hook_registry",
            "execution_engine",
            "run",
            "workflows",
            "substrate_override",
            "_di_registry",
        }
        assert not _members(PluginHost) & forbidden

    @pytest.mark.parametrize("name", sorted(VIEW_MEMBERS))
    def test_each_view_is_sized_to_measured_plugin_use(self, name: str) -> None:
        assert _members(_VIEWS[name]) == VIEW_MEMBERS[name]

    def test_the_views_are_ten_members_against_the_facades_thirty_three(self) -> None:
        """The number the port's docstring claims, so the claim is checked."""
        total = sum(len(_members(v)) for v in _VIEWS.values())
        assert total == 10


class TestThePortNamesNoForbiddenLayer:
    """AC-1b: `_types` may not import `_app`, `TYPE_CHECKING` or otherwise.

    `exclude_type_checking_imports = true` in `pyproject.toml` means
    import-linter would not catch a deferred one, and
    `contributor/architecture/layer-contract-blind-spot.md` §7 refuses it in
    terms. So the check is here, on the text, rather than left to `lint-imports`.

    `tasks.md`'s gate was `rg -c "_app" host.py -> 0`, which **cannot** hold:
    every view docstring cites the facade it was copied from
    (`_app/gates_facade.py:31` and four others), and citing them is the point.
    The gate is about imports, so this test reads imports.
    """

    def _import_lines(self) -> Iterable[str]:
        source = Path(PluginHost.__module__.replace(".", "/") + ".py")
        root = Path(__file__).resolve().parents[2] / "src"
        text = (root / source).read_text()
        return [
            line.strip()
            for line in text.splitlines()
            if re.match(r"\s*(from|import)\s+\w", line)
        ]

    def test_it_imports_nothing_from_app(self) -> None:
        offenders = [ln for ln in self._import_lines() if "functualize._app" in ln]
        assert not offenders, offenders

    def test_it_imports_only_stdlib_and_types(self) -> None:
        """The whole point: a plugin names the port without importing the app."""
        offenders = [
            ln
            for ln in self._import_lines()
            if "functualize" in ln and "functualize._types" not in ln
        ]
        assert not offenders, offenders
