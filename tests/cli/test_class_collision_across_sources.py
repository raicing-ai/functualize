"""The strict collision when the two claimants come from two providers.

`contracts.md` § C5 and AC-13's third clause: the same job class arriving
through a directory scan and through a second source — or one of its methods
claimed by another provider's function — registers *nobody* under that name,
exactly as the collision does inside one scan. The rule itself is unit-tested in
`tests/discovery/test_provider_class_sources.py`; this file drives the shipped
path instead: `func`, booting a project whose second provider is added by a
plugin, the documented route.

The colliding name is per method, so a method no other source claims is the
control — it must keep running while its sibling does not.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import surfaces

pytestmark = surfaces("func")

#: The directory-scanned job class. `stop` is claimed by nobody else.
JOBS = """\
from pydantic import BaseModel

from functualize.job import job


@job(group="pg")
class Postgres(BaseModel):
    host: str = "localhost"

    def start(self) -> None:
        print("class start ran")

    def stop(self) -> None:
        print("class stop ran")
"""

#: A second provider whose one job is a function claiming `pg.start`.
FUNCTION_SOURCE = """\
from functualize.job import job
from functualize.plugin import Job, StaticProvider


@job(group="pg")
def start() -> None:
    print("function start ran")


class _SecondSource:
    name = "second-source"
    version = "1.0.0"
    description = "A second provider claiming pg.start"

    def __call__(self, app):
        app.extensions.add_job_provider(
            StaticProvider([Job(function=start, name="pg.start", group="pg")])
        )


plugin = _SecondSource()
"""

#: A second provider handing over the *same* class the directory scan finds:
#: the job module is loaded from its file, so the class is the one on disk.
CLASS_SOURCE = """\
import importlib.util
import sys
from pathlib import Path

from functualize.plugin import StaticProvider

_JOBS = Path(__file__).resolve().parent.parent / "jobs" / "pg.py"


def _postgres():
    spec = importlib.util.spec_from_file_location("second_source_pg", _JOBS)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.Postgres


class _SecondSource:
    name = "second-source"
    version = "1.0.0"
    description = "The directory's job class, through a static provider"

    def __call__(self, app):
        app.extensions.add_job_provider(StaticProvider([_postgres()]))


plugin = _SecondSource()
"""


def _project(project_tree, plugin: str) -> Path:
    return project_tree(
        pyproject='[project]\nname = "twosources"\nversion = "0.1.0"\n'
        "dependencies = []\n",
        jobs={"pg.py": JOBS},
        plugins={"second_source.py": plugin},
    )


def _strict_failures(cli_run, cwd: Path) -> dict[str, str]:
    result = cli_run(["builtin", "info", "--json"], cwd=cwd)
    assert result.exit_code == 0, result.stderr
    return {
        failure["message"].split("'")[1]: failure["message"]
        for failure in json.loads(result.stdout)["discovery_failures"]
        if failure["error_type"] == "ClassJobNameCollision"
    }


class TestAFunctionFromAnotherProvider:
    @pytest.fixture()
    def project(self, project_tree) -> Path:
        return _project(project_tree, FUNCTION_SOURCE)

    def test_the_contested_method_is_refused(self, cli_run, project: Path) -> None:
        result = cli_run(["pg", "start"], cwd=project)

        # The AC-6 shape: a usage error, not a run of either claimant.
        assert result.exit_code == 2, result.stderr
        assert "'Postgres.start'" in result.stderr
        assert "'start'" in result.stderr
        assert "pg.py" in result.stderr
        assert "second_source.py" in result.stderr
        assert "ran" not in result.stdout

    def test_info_lists_the_refusal(self, cli_run, project: Path) -> None:
        failures = _strict_failures(cli_run, project)

        assert set(failures) == {"pg.start"}
        assert "Neither is registered" in failures["pg.start"]

    def test_the_uncontested_sibling_still_runs(self, cli_run, project: Path) -> None:
        result = cli_run(["pg", "stop"], cwd=project)

        assert result.exit_code == 0, result.stderr
        assert "class stop ran" in result.stdout


class TestTheSameClassFromTwoSources:
    @pytest.fixture()
    def project(self, project_tree) -> Path:
        return _project(project_tree, CLASS_SOURCE)

    @pytest.mark.parametrize("method", ["start", "stop"])
    def test_every_method_is_refused(self, cli_run, project: Path, method: str) -> None:
        result = cli_run(["pg", method], cwd=project)

        assert result.exit_code == 2, result.stderr
        assert f"'Postgres.{method}'" in result.stderr
        assert "ran" not in result.stdout

    def test_info_lists_one_refusal_per_method(self, cli_run, project: Path) -> None:
        assert set(_strict_failures(cli_run, project)) == {"pg.start", "pg.stop"}
