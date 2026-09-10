"""The engine is complete at construction, and nothing writes into it (F3 · T3).

Four claims, each with the edit that would falsify it:

- **Nothing outside `_engine/` assigns a private attribute of an engine.** Five
  post-hoc writes used to make the engine complete: two back-references, the
  config chain, and the invoke depth. This scans the source for the shape, in
  the way `test_typer_isolation.py` does for CLI imports, so a restored write
  fails the suite rather than being noticed in an audit.
- **The host is real.** The app satisfies `EngineHost`, so what `build_engine`
  hands the engine can answer every question the engine asks it.
- **The registry is not shared.** `registered_jobs()` is a read-only view, and
  materialization is *reported* to the host instead of written into a dict the
  engine was handed by reference.
- **The config chain is read live.** `refresh()` rebuilds the chain in place;
  it no longer reaches into the engine, and the engine still sees the new one.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from functualize import FunctualizeApp
from functualize._config.chain import ResolutionChain
from functualize._config.sources import DefaultSource
from functualize._types.protocols import EngineHost
from functualize.app.config import ConfigSources, JobSources, PluginSources

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
_PLUGINS = _REPO / "plugins"

PLAIN_JOB = '''
def alpha() -> None:
    """A job."""
'''

#: Names a reference to an engine is bound to, as a receiver.
_ENGINE_NAMES = frozenset({"engine", "_engine", "execution_engine"})


def _receiver_name(node: ast.expr) -> str | None:
    """The tail name of an attribute chain — `a.b._c` reads as `b`."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _assigned_private_attrs(node: ast.stmt) -> list[ast.Attribute]:
    """Every attribute target of an assignment statement."""
    targets: list[ast.expr] = []
    if isinstance(node, ast.Assign):
        targets = list(node.targets)
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        targets = [node.target]
    return [t for t in targets if isinstance(t, ast.Attribute)]


def _engine_writes_outside_the_engine() -> list[str]:
    """`engine._x = …` anywhere in `src/` or `plugins/`, outside `_engine/`.

    AST, not a regex. A pattern for this shape also matches the prose that
    mentions it, and it cannot tell `engine._x = y` from `engine._x == y`;
    three gates on this branch were kept red by a comment that quoted what it
    explained.

    Reads are deliberately not matched: the rest of the package legitimately
    observes engine state (`app.execution_engine.get_job`), and the claim here
    is only that nothing *finishes* the engine from outside.
    """
    violations: list[str] = []
    roots = [(path, _SRC) for path in _SRC.rglob("*.py")] + [
        (path, _PLUGINS) for path in _PLUGINS.rglob("*.py")
    ]
    for path, _ in roots:
        relative = path.relative_to(_REPO)
        if "_engine" in relative.parts:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                continue
            for target in _assigned_private_attrs(node):
                if not target.attr.startswith("_"):
                    continue
                if _receiver_name(target.value) in _ENGINE_NAMES:
                    violations.append(f"{relative}:{target.lineno}: {target.attr}")
    return violations


def _job_directory(tmp_path: Path) -> Path:
    directory = tmp_path / "jobs"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "alpha.py").write_text(PLAIN_JOB)
    return directory


def _static_app() -> FunctualizeApp:
    def alpha() -> None:
        """A job."""

    return FunctualizeApp(
        "static",
        job_sources=JobSources(functions=[alpha]),
        config_sources=ConfigSources(config_resolution_chain=ResolutionChain([])),
        plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
    )


def _standard_app(tmp_path: Path) -> FunctualizeApp:
    return FunctualizeApp(
        "standard", job_sources=JobSources(directories=[str(_job_directory(tmp_path))])
    )


class TestNothingWritesIntoTheEngine:
    def test_no_engine_private_attribute_is_assigned_outside_the_engine(self) -> None:
        violations = _engine_writes_outside_the_engine()

        assert not violations, (
            "The engine is finished by its owners after it is built. Every one "
            "of these is a dependency the engine should have been constructed "
            "with, or read from its host:\n  " + "\n  ".join(violations)
        )


class TestTheHostIsReal:
    def test_both_boot_paths_hand_the_engine_an_engine_host(
        self, tmp_path: Path
    ) -> None:
        """The port is not decoration: the object the engine holds answers it.

        `build_engine` is the only construction site, and this is what says the
        thing it is given is what the engine will ask.
        """
        static_app = _static_app()
        standard_app = _standard_app(tmp_path)

        for app in (static_app, standard_app):
            assert isinstance(app, EngineHost)
            assert app.execution_engine.host is app


class TestTheRegistryIsNotShared:
    def test_registered_jobs_is_a_read_only_view(self, tmp_path: Path) -> None:
        """AC-4. The engine used to be handed the registry's private dict by
        reference; the replacement is a mapping it cannot write into."""
        app = _standard_app(tmp_path)

        with pytest.raises(TypeError):
            app.registered_jobs()["injected"] = None  # type: ignore[index]

    def test_materializing_an_entry_updates_the_registry_the_app_holds(
        self, tmp_path: Path
    ) -> None:
        """AC-4, behaviourally: the two sides converge on the same entry.

        The engine keeps its own copy for resolution; the app registry holds
        the copy the rest of the framework reads. A shared dict made that
        automatic and unassertable — a call makes it contractual.
        """
        from functualize._discovery.lazy_wrapper import LazyJobFunction
        from functualize._types.descriptors import JobDescriptor, RegisteredJob

        app = _standard_app(tmp_path)
        module = tmp_path / "lazymod_probe.py"
        module.write_text(PLAIN_JOB)
        import sys

        sys.path.insert(0, str(tmp_path))
        try:
            entry = RegisteredJob(
                name="alpha",
                function=LazyJobFunction(
                    JobDescriptor(
                        name="alpha",
                        group=None,
                        module_path="lazymod_probe",
                        source_file=str(module),
                    )
                ),
                config_class=None,
                group=None,
                module_path="lazymod_probe",
            )
            app.job_registry._registered_jobs[entry.name] = entry
            app.execution_engine.register_job(entry)

            resolved = app.execution_engine.get_job("alpha")
        finally:
            sys.path.remove(str(tmp_path))
            sys.modules.pop("lazymod_probe", None)

        assert not isinstance(resolved.function, LazyJobFunction)
        assert app.job_registry._registered_jobs["alpha"] is resolved


class TestTheChainIsReadLive:
    def test_a_rebuilt_chain_is_visible_to_the_engine_without_a_write(self) -> None:
        """AC-5. `refresh()` rebuilds the chain in place. The engine used to be
        written into at that moment — at runtime, from a refresh — so this says
        the read is live instead."""
        app = _static_app()
        engine = app.execution_engine

        app._resolution_chain = ResolutionChain(
            [DefaultSource({"shell": {"program": "rebuilt-sh"}})]
        )

        assert engine._resolve_shell_setting("program") == "rebuilt-sh"


class TestTheInvokeDepthIsReadFromTheHost:
    def test_the_config_resolved_depth_reaches_the_engine(self) -> None:
        """`general.max_invoke_depth` is resolved *after* the engine exists, so
        the value cannot be a constructor argument — it used to be written into
        the engine's private field by the boot step that resolved it."""
        from functualize._app import boot

        app = _static_app()
        app._resolution_chain = ResolutionChain(
            [DefaultSource({"general": {"max_invoke_depth": 3}})]
        )

        boot._resolve_max_invoke_depth(app)

        assert app.max_invoke_depth == 3
        assert app.execution_engine.max_invoke_depth == 3
