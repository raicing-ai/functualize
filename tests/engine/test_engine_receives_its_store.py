"""The engine receives its storage; it never goes looking for one (FUN-17 · T12).

Three claims, each with the edit that would falsify it:

- **Construction without storage is impossible** (spec AC-4). `runtime_store`
  and `substrate` are required keyword-only arguments, so the failure is a
  `TypeError` at the call rather than a `None` discovered during a run. The
  edit that falsifies this is giving either parameter a default — measured:
  re-adding `= None` turns four tests here red, and nothing else in the suite
  notices.
- **Boot's one selection is what the engine holds, by identity.** The store and
  the substrate the engine was handed were built over the same decision, on
  both boot paths, and a plugin that installs before step 6.5 reaches the
  engine through that one decision.
- **The module has no discovery left.** An AST scan of `_engine/executor.py`
  for the call and the attribute that used to resolve storage lazily, rather
  than a grep for the names — four docstrings in this repository discuss these
  mechanisms by name, and a grep answers with prose.

Why this file exists at all: the deletion is only a deletion if nothing can
grow back. The engine kept `.functualize/` reachable from a *read* for two
waves; a read is not a hot path, so nothing pointed at it.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from functualize import FunctualizeApp
from functualize._config.chain import ResolutionChain
from functualize._primitives.substrate import JsonFileSubstrate
from functualize.app.config import ConfigSources, JobSources, PluginSources

if TYPE_CHECKING:
    from functualize._types.protocols import StoreSubstrate

_REPO = Path(__file__).resolve().parents[2]
_ENGINE_MODULE = _REPO / "src" / "functualize" / "_engine" / "executor.py"

PLAIN_JOB = '''
def alpha() -> None:
    """A job."""
'''

#: The call and the attribute that used to answer "where do documents live?".
_RESOLVERS = frozenset({"substrate_for_project", "substrate_override"})


def _engine_args(**kwargs: Any) -> dict[str, Any]:
    """Everything `JobExecutionEngine` takes in every test in this file."""
    from functualize._engine.middleware import ExecutionMiddlewareChain
    from functualize._events.bus import EventBus
    from functualize._events.hooks import HookRegistry
    from functualize._primitives.di import DIRegistry

    return {
        "di_registry": DIRegistry(),
        "event_bus": EventBus(),
        "hook_registry": HookRegistry(),
        "middleware_chain": ExecutionMiddlewareChain(),
        **kwargs,
    }


def _bare_engine(**kwargs: Any) -> Any:
    """An engine built the way embedding builds one: nothing but its arguments."""
    from functualize._engine.executor import JobExecutionEngine

    return JobExecutionEngine(**_engine_args(**kwargs))


class _Host:
    """A host shaped to satisfy the resolution that used to live in the engine.

    Deliberately not a real `EngineHost`: the two attributes below are exactly
    what the deleted property read, and everything else about the port is
    irrelevant to whether the engine can find storage on its own.
    """

    def __init__(self, override: StoreSubstrate, root: Path) -> None:
        self.substrate_override = override
        self.fresh_root = root


class _InstallingPlugin:
    """A plugin whose only job is to install a substrate, at registration.

    The two things `PluginLoader` reads from an explicit plugin are `name` and
    the call itself; a fake is the point, because this file is about the engine
    receiving an install, not about any particular plugin.
    """

    name = "probe-installs-a-substrate"

    def __init__(self, substrate: StoreSubstrate) -> None:
        self._substrate = substrate

    def __call__(self, app: Any) -> None:
        """Install at registration — before step 6.5, which is the window."""
        app.install_substrate(self._substrate)


def _static_app(*plugins: Any) -> FunctualizeApp:
    """The static wiring path: explicit plugins register before step 6.5."""

    def alpha() -> None:
        """A job."""

    return FunctualizeApp(
        "receives",
        job_sources=JobSources(functions=[alpha]),
        config_sources=ConfigSources(config_resolution_chain=ResolutionChain([])),
        plugin_sources=PluginSources(
            entry_point_group="", explicit_plugins=list(plugins)
        ),
    )


def _standard_app(tmp_path: Path) -> FunctualizeApp:
    """The standard path: directory discovery, entry-point plugins."""
    directory = tmp_path / "jobs"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "alpha.py").write_text(PLAIN_JOB)
    return FunctualizeApp(
        "receives-standard", job_sources=JobSources(directories=[str(directory)])
    )


class TestConstructionWithoutStorageIsImpossible:
    """Spec AC-4: the engine cannot be built without being told where to write."""

    def test_an_engine_with_no_storage_cannot_be_built(self) -> None:
        """A `TypeError` at the call, not a `None` discovered on first write.

        The distinction is the whole of AC-4: a bind-once handle that was never
        bound fails at the first write, which for storage is a run in
        production. This fails at the line that wrote it.
        """
        with pytest.raises(TypeError, match="runtime_store"):
            _bare_engine()

    def test_the_substrate_is_named_too(self) -> None:
        """Both arguments are required, so a caller cannot satisfy half of it."""
        with pytest.raises(TypeError, match="substrate"):
            _bare_engine(
                runtime_store=object(),
            )
        with pytest.raises(TypeError, match="runtime_store"):
            _bare_engine(substrate=JsonFileSubstrate(Path("/nonexistent")))

    def test_fresh_root_is_not_an_answer(self, tmp_path: Path) -> None:
        """Pins away `self._substrate or substrate_for_project(self.fresh_root)`.

        This is the edit that would restore the old behaviour while every
        *other* test in the suite stayed green: an engine with a root would
        find a substrate again, and nothing that goes through boot would
        notice. Here the engine is handed the root the old resolution walked
        from, and is still unbuildable.
        """
        with pytest.raises(TypeError, match="runtime_store"):
            _bare_engine(fresh_root=tmp_path)

    def test_a_hosts_installed_override_is_boots_to_read(self, tmp_path: Path) -> None:
        """Pins away `getattr(host, "substrate_override", None) or ...`.

        Boot reads that slot at step 6.5 and hands the answer over. An engine
        that read it too would be a second decider — and the visible symptom is
        which plugin wins depending on when something first asked a store a
        question, which is the hook-order bug T11 exposed. The probe host
        carries a real override and a real root, and neither substitutes.
        """
        with pytest.raises(TypeError, match="runtime_store"):
            _bare_engine(
                fresh_root=tmp_path,
                host=_Host(JsonFileSubstrate(tmp_path / "installed"), tmp_path),
            )


class TestBootHandsOverItsOneSelection:
    """What the engine holds is what boot selected — one decision, both paths."""

    @pytest.mark.parametrize("path", ["static", "standard"])
    def test_the_store_and_the_substrate_agree(self, tmp_path: Path, path: str) -> None:
        """The two things boot hands over were built over the same decision.

        Not a tautology: boot computes the substrate and the store in one step,
        and an engine that resolved its own would hold two answers — the
        split brain this feature exists to prevent, one level up.
        """
        app = _static_app() if path == "static" else _standard_app(tmp_path)
        engine = app.execution_engine

        store = engine._runtime_store  # noqa: SLF001
        assert store is not None, "boot built the engine without a store"
        assert store.scope_store.substrate is engine.substrate
        assert engine._state_store().substrate is engine.substrate  # noqa: SLF001
        assert store.run_store.substrate is engine.substrate

    def test_an_install_before_the_selection_reaches_the_engine(
        self, tmp_path: Path
    ) -> None:
        """The install lane that survives, end to end.

        A plugin registering an explicit plugin installs *before* step 6.5 on
        this path, so the engine is handed the plugin's substrate. The point of
        the assertion is the third line: the engine did not go looking, and it
        did not have to.
        """
        installed = JsonFileSubstrate(tmp_path / "installed")
        app = _static_app(_InstallingPlugin(installed))

        assert app.substrate_override is installed, "the install was dropped"
        assert app.execution_engine.substrate is installed
        assert app.substrate is installed


class TestNoDiscoveryIsLeftInTheEngine:
    """The source, not the behaviour — a restored resolution must be visible."""

    def test_the_engine_names_neither_resolution(self) -> None:
        """Counted by walking the AST, so prose in a docstring cannot satisfy it.

        The deleted property's body was four lines; its docstring explained
        both mechanisms by name, and a `rg -c` gate counts those lines too. What
        must stay gone is a *reference*, which is what the AST gives.
        """
        tree = ast.parse(_ENGINE_MODULE.read_text())
        found: list[str] = []
        walked = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                walked += 1
                if node.id in _RESOLVERS:
                    found.append(f"executor.py:{node.lineno}: {node.id}")
            elif isinstance(node, ast.Attribute):
                walked += 1
                if node.attr in _RESOLVERS:
                    found.append(f"executor.py:{node.lineno}: .{node.attr}")

        assert walked > 1000, (
            f"the AST walk found only {walked} names in the engine module, so "
            f"it is not looking at what it thinks it is"
        )
        assert not found, (
            "the engine can reach storage again. Every path to where documents "
            "live must come from the constructor, handed over by boot step "
            "6.5:\n  " + "\n  ".join(found)
        )
