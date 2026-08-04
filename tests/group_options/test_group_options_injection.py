"""Group options become a resolved instance on the job's parameter (S6a T-GO-4).

T-GO-3 *parsed* mid-path flags into a flat dict; this is the half that turns
that dict into a value the job can read. The ladder under test is the job
ladder with one substitution — the **group path** replaces the job name as the
config section and env prefix — so ``class DeployOptions(GroupOptions,
group="deploy")`` reads ``[deploy]`` and ``DEPLOY__ENV`` no matter which job
under ``deploy`` declares it.

Two properties are worth more than the rest and are asserted directly:

* **D-c** — a mid-path flag beats the environment, matching how a job's own
  flag does.
* **Injection is not CLI-conditional.** ``app.execute("deploy.web.run")`` has
  no command line at all, and must still see its group's file/env/default
  values. A group option that only materialized under the CLI would be a
  different feature.

Written **without** ``from __future__ import annotations`` at module level so
the PEP 563 parametrization below is real; the job modules carry (or omit) it
themselves. Reading ``param.annotation`` raw is the recurring bug this guards.
"""

import sys
import textwrap
from collections.abc import Generator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from functualize._app.state import AppState
from functualize.app.core import FunctualizeApp
from functualize.job import RunStatus

_JOB_MODULE = """
{future_import}

from typing import Annotated

from functualize.job import GroupOptions, Option


class DeployOptions(GroupOptions, group="deploy"):
    env: Annotated[str, Option("-e")] = "staging"
    dry_run: bool = False


class WebOptions(GroupOptions, group="deploy.web"):
    env: str = "staging"
    replicas: int = 1


def run(image: str = "nginx", opts: DeployOptions = None) -> str:
    return f"{{image}}/{{opts.env}}/{{opts.dry_run}}"


def nested(opts: WebOptions = None) -> str:
    return f"{{opts.env}}/{{opts.replicas}}"


def both(outer: DeployOptions = None, inner: WebOptions = None) -> str:
    return f"{{outer.env}}/{{inner.env}}"


def plain(name: str = "x") -> str:
    return name
"""


def _job_module(use_future: bool) -> ModuleType:
    """Compile the job module with or without PEP 563 enabled.

    Registered in ``sys.modules`` because pydantic resolves a PEP 563 model's
    string annotations through ``sys.modules[cls.__module__].__dict__``. A
    module object that exists only as a local is unreachable from there, and
    ``Annotated[str, Option(...)]`` fails to rebuild — an artifact of building
    the module by hand, not something a real imported job module can hit.
    """
    source = _JOB_MODULE.format(
        future_import="from __future__ import annotations" if use_future else ""
    )
    module = ModuleType(f"group_options_jobs_{use_future}")
    sys.modules[module.__name__] = module
    exec(compile(textwrap.dedent(source), module.__name__, "exec"), module.__dict__)
    return module


@pytest.fixture(autouse=True)
def _isolated_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None]:
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(project)
    AppState.reset()
    yield
    AppState.reset()


def _app(module: ModuleType) -> FunctualizeApp:
    app = FunctualizeApp(name="groupopts")
    app.register_dynamic_job("run", module.run)
    app.register_dynamic_job("nested", module.nested)
    app.register_dynamic_job("both", module.both)
    app.register_dynamic_job("plain", module.plain)
    return app


def _execute(
    app: FunctualizeApp,
    job_name: str,
    *,
    group_options: dict[str, Any] | None = None,
    **kwargs: Any,
) -> Any:
    """Run through the engine, optionally with a group-CLI layer.

    ``app.execute`` deliberately has no ``group_option_values`` parameter —
    a mid-path flag is a command-line concept, and the facade is not the
    command line. The dispatcher reaches the engine directly, so the tests
    that exercise the CLI layer do too.
    """
    entry = app.job_registry.get_job(job_name)
    return app._execution_engine.execute(
        job_name,
        entry.function,
        config_class=entry.config_class,
        kwargs=kwargs,
        group_option_values=group_options,
    )


@pytest.mark.parametrize("use_future", [False, True], ids=["live", "pep563"])
class TestGroupOptionsInjection:
    """Every assertion runs with annotations live and as PEP 563 strings."""

    def test_the_parameter_is_injected_with_declared_defaults(
        self, use_future: bool
    ) -> None:
        """Not `None`. The signature default exists only to keep the function
        callable in plain Python; the engine is what supplies the instance."""
        result = _execute(_app(_job_module(use_future)), "run")

        assert result.status is RunStatus.SUCCESS, repr(result.exception)
        assert result.return_value == "nginx/staging/False"

    def test_a_mid_path_flag_lands_on_the_instance(self, use_future: bool) -> None:
        result = _execute(
            _app(_job_module(use_future)), "run", group_options={"env": "prod"}
        )

        assert result.return_value == "nginx/prod/False"

    def test_a_bool_flag_arrives_as_a_bool(self, use_future: bool) -> None:
        """The walk yields `True` for a presence flag, not the string "True"."""
        result = _execute(
            _app(_job_module(use_future)), "run", group_options={"dry_run": True}
        )

        assert result.return_value == "nginx/staging/True"

    def test_the_group_section_of_the_config_file_is_read(
        self, use_future: bool
    ) -> None:
        """`[deploy]`, keyed by the *group* path — the job is named `run`."""
        (Path.cwd() / "config.base.toml").write_text('[deploy]\nenv = "fromfile"\n')
        AppState.reset()

        result = _execute(_app(_job_module(use_future)), "run")

        assert result.return_value == "nginx/fromfile/False"

    def test_env_beats_the_config_file(
        self, use_future: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (Path.cwd() / "config.base.toml").write_text('[deploy]\nenv = "fromfile"\n')
        monkeypatch.setenv("DEPLOY__ENV", "fromenv")
        AppState.reset()

        result = _execute(_app(_job_module(use_future)), "run")

        assert result.return_value == "nginx/fromenv/False"

    def test_a_mid_path_flag_beats_env(
        self, use_future: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """D-c, the decision this task resolved. If env won instead, a user
        could not override an exported default from the command line — which
        is the whole point of typing the flag."""
        monkeypatch.setenv("DEPLOY__ENV", "fromenv")
        AppState.reset()

        result = _execute(
            _app(_job_module(use_future)), "run", group_options={"env": "prod"}
        )

        assert result.return_value == "nginx/prod/False"

    def test_the_full_ladder_in_one_run(
        self, use_future: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """default < file < env < group-CLI, each layer visible on its own
        field so one assertion pins the whole order."""
        (Path.cwd() / "config.base.toml").write_text(
            '[deploy]\nenv = "fromfile"\ndry_run = true\n'
        )
        monkeypatch.setenv("DEPLOY__ENV", "fromenv")
        AppState.reset()
        module = _job_module(use_future)

        # `dry_run` reaches only the file layer; `env` is overridden all the
        # way up; `image` is the job's own parameter and is untouched by any
        # of it.
        result = _execute(_app(module), "run", group_options={"env": "prod"})

        assert result.return_value == "nginx/prod/True"

    def test_a_nested_group_scopes_env_by_its_full_path(
        self, use_future: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`deploy.web` -> `DEPLOY_WEB__ENV`. The dot cannot survive into an
        env key, and flattening it to `DEPLOY__ENV` would make a nested
        group's options indistinguishable from its parent's."""
        monkeypatch.setenv("DEPLOY_WEB__ENV", "web-env")
        monkeypatch.setenv("DEPLOY__ENV", "parent-env")
        AppState.reset()

        result = _execute(_app(_job_module(use_future)), "nested")

        assert result.return_value == "web-env/1"

    def test_a_nested_group_reads_its_own_config_section(
        self, use_future: bool
    ) -> None:
        (Path.cwd() / "config.base.toml").write_text(
            '[deploy]\nenv = "parent"\n\n[deploy.web]\nenv = "child"\nreplicas = 3\n'
        )
        AppState.reset()

        result = _execute(_app(_job_module(use_future)), "nested")

        assert result.return_value == "child/3"

    def test_two_declared_ancestors_see_one_value_for_a_shared_field(
        self, use_future: bool
    ) -> None:
        """§5 / C-D3: the merge is flat, so a job injecting both `deploy` and
        `deploy.web` options reads the same `env` from each. Two instances
        disagreeing about a field the user set once is the failure this
        forbids."""
        result = _execute(
            _app(_job_module(use_future)), "both", group_options={"env": "prod"}
        )

        assert result.return_value == "prod/prod"

    def test_a_job_without_group_options_is_untouched(self, use_future: bool) -> None:
        """Including when a group layer is present — an unrelated job must not
        acquire a parameter, and must not fail because one was offered."""
        result = _execute(
            _app(_job_module(use_future)), "plain", group_options={"env": "prod"}
        )

        assert result.status is RunStatus.SUCCESS, repr(result.exception)
        assert result.return_value == "x"

    def test_the_facade_resolves_the_same_non_cli_layers(
        self, use_future: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`app.execute` never passes a group-CLI layer, so this proves
        injection is not gated on one: an `invoke("deploy.web.run")` from
        Python resolves file/env/default exactly as the CLI run does."""
        (Path.cwd() / "config.base.toml").write_text("[deploy]\ndry_run = true\n")
        monkeypatch.setenv("DEPLOY__ENV", "fromenv")
        AppState.reset()
        app = _app(_job_module(use_future))

        via_facade = app.execute("run")
        via_engine = _execute(app, "run")

        assert via_facade.status is RunStatus.SUCCESS, repr(via_facade.exception)
        assert via_facade.return_value == "nginx/fromenv/True"
        assert via_facade.return_value == via_engine.return_value


class TestGroupOptionsParamScan:
    """The per-function scan behind the injection loop."""

    def test_the_scan_is_memoized_per_function(self) -> None:
        """It runs `get_type_hints` on every execution otherwise, on every job
        — including the overwhelming majority that declare no group options.
        """
        module = _job_module(False)
        app = _app(module)
        engine = app._execution_engine

        first = engine._group_options_params(module.run)
        second = engine._group_options_params(module.run)

        assert first == second
        assert first is second
        assert [name for name, _ in first] == ["opts"]

    def test_a_plain_job_scans_to_nothing(self) -> None:
        module = _job_module(False)
        engine = _app(module)._execution_engine

        assert engine._group_options_params(module.plain) == ()

    def test_the_scan_reports_the_declaring_class(self) -> None:
        module = _job_module(False)
        engine = _app(module)._execution_engine

        found = dict(engine._group_options_params(module.both))

        assert found["outer"].__group_path__ == "deploy"
        assert found["inner"].__group_path__ == "deploy.web"
