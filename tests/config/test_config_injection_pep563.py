"""Config injection under `from __future__ import annotations` (PEP 563).

The engine finds a job's config parameter by looking for the one whose
annotation is the config model. Reading `inspect.Parameter.annotation` raw
works only while annotations are live objects — under PEP 563 every annotation
is a *string*, so an `isinstance(annotation, type)` test matches nothing, no
parameter is injected, and the job dies at call time with

    TypeError: report() missing 1 required positional argument: 'config'

which names the config parameter but says nothing about config. Discovery
already resolved hints for this exact reason; the executor's injection path
did not.

**This module deliberately does not use `from __future__ import annotations`
at the top.** The job functions under test carry it via their own module-level
compilation in `_module_with_future_annotations`, so both worlds are
exercised in one file. Adding the import here would make the "without"
half untestable.
"""

import textwrap
from collections.abc import Generator
from pathlib import Path
from types import ModuleType

import pytest

from functualize._app.state import AppState
from functualize.app.core import FunctualizeApp
from functualize.job import RunStatus

_JOB_MODULE = """
{future_import}

from pydantic import BaseModel, Field


class CityConfig(BaseModel):
    city: str = Field(default="Tokyo")
    days: int = 3


def report(config: CityConfig) -> str:
    return f"{{config.city}}/{{config.days}}"
"""


def _module_with_future_annotations(use_future: bool) -> ModuleType:
    """Compile a job module with or without PEP 563 enabled."""
    source = _JOB_MODULE.format(
        future_import="from __future__ import annotations" if use_future else ""
    )
    module = ModuleType(f"pep563_jobs_{use_future}")
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


def _run(module: ModuleType, **kwargs: object) -> object:
    app = FunctualizeApp(name="pep563")
    app.register_dynamic_job("report", module.report, config_class=module.CityConfig)
    return app.execute("report", **kwargs)


@pytest.mark.parametrize("use_future", [False, True], ids=["live", "pep563"])
class TestConfigInjection:
    """Every assertion runs both ways. A fix that works only for one form of
    annotation is the bug in the other direction."""

    def test_the_config_parameter_is_injected(self, use_future: bool) -> None:
        result = _run(_module_with_future_annotations(use_future))

        assert result.status is RunStatus.SUCCESS, (
            f"config injection failed with PEP 563 {'on' if use_future else 'off'}: "
            f"{result.exception!r}"
        )
        assert result.return_value == "Tokyo/3"

    def test_config_values_come_from_the_file(self, use_future: bool) -> None:
        """Not merely "an object was injected" — the *resolved* one."""
        (Path.cwd() / "config.base.toml").write_text(
            '[report]\ncity = "Osaka"\ndays = 5\n'
        )
        AppState.reset()

        result = _run(_module_with_future_annotations(use_future))

        assert result.return_value == "Osaka/5"

    def test_cli_values_still_override(self, use_future: bool) -> None:
        result = _run(_module_with_future_annotations(use_future), city="Kyoto")

        assert result.return_value == "Kyoto/3"


class TestUnresolvableAnnotations:
    """Hint resolution must degrade, not explode.

    A job module that imports its config type only under `TYPE_CHECKING` has
    an annotation that cannot be evaluated at runtime. That is a real pattern,
    and it must not turn into a hard failure of every job in the module.
    """

    def test_an_unresolvable_hint_does_not_crash_the_run(self) -> None:
        source = """
        from __future__ import annotations

        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            from nonexistent_module import Missing


        def report(value: Missing = None) -> str:
            return "ran"
        """
        module = ModuleType("pep563_unresolvable")
        exec(compile(textwrap.dedent(source), module.__name__, "exec"), module.__dict__)

        app = FunctualizeApp(name="pep563")
        app.register_dynamic_job("report", module.report)

        result = app.execute("report")

        assert result.status is RunStatus.SUCCESS
        assert result.return_value == "ran"


class TestRegressionGuard:
    def test_pep563_and_live_annotations_agree(self) -> None:
        """The single sentence this whole module exists to enforce: adding
        `from __future__ import annotations` to a job module must not change
        what the job does."""
        (Path.cwd() / "config.base.toml").write_text('[report]\ncity = "Nara"\n')
        AppState.reset()

        live = _run(_module_with_future_annotations(False))
        AppState.reset()
        pep563 = _run(_module_with_future_annotations(True))

        assert live.status is pep563.status is RunStatus.SUCCESS
        assert live.return_value == pep563.return_value == "Nara/3"


def test_the_config_model_is_also_set_on_runcontext() -> None:
    """The other injection site: `rc.job_config`. It resolves the model
    independently of the signature scan, so it must be checked separately."""
    source = """
    from __future__ import annotations

    from pydantic import BaseModel

    from functualize.job import RunContext


    class CityConfig(BaseModel):
        city: str = "Tokyo"


    def report(config: CityConfig, rc: RunContext) -> str:
        assert rc.job_config is config
        return "agreed"
    """
    module = ModuleType("pep563_rc")
    exec(compile(textwrap.dedent(source), module.__name__, "exec"), module.__dict__)

    app = FunctualizeApp(name="pep563")
    app.register_dynamic_job("report", module.report, config_class=module.CityConfig)

    result = app.execute("report")

    assert result.status is RunStatus.SUCCESS
    assert result.return_value == "agreed"
