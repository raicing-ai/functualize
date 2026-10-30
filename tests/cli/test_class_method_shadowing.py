"""A subclass that replaces an inherited method removes it — and only it.

`spec.md`: only a job class's *effective* public instance methods are jobs;
properties, ``staticmethod``s and ``classmethod``s are not. When a subclass
turns ``Base.start`` into one of those, ``start`` is not a job — but ``stop``,
which the subclass defines normally, still is.

The scan once judged a name's kind before recording it as seen, so the base's
function was admitted under the subclass's name. A ``property`` then made the
scan raise and lose every job in the module, ``pg.stop`` included; a
``staticmethod`` or ``classmethod`` registered a ``pg.start`` that failed with
``TypeError`` when run. Each kind is read back through `func`, cold and warm.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import surfaces

pytestmark = surfaces("func")

#: The override each case puts in place of the inherited `start`.
OVERRIDES = {
    "property": "    @property\n    def start(self) -> str:\n        return 'x'\n",
    "staticmethod": "    @staticmethod\n    def start() -> None:\n        print('static start ran')\n",
    "classmethod": "    @classmethod\n    def start(cls) -> None:\n        print('classmethod start ran')\n",
}


def _module(override: str) -> str:
    return (
        "from pydantic import BaseModel\n"
        "\n"
        "from functualize.job import job\n"
        "\n"
        "\n"
        "class Base(BaseModel):\n"
        "    host: str = 'localhost'\n"
        "\n"
        "    def start(self) -> None:\n"
        "        print('base start ran')\n"
        "\n"
        "\n"
        "@job(group='pg')\n"
        "class Child(Base):\n"
        f"{override}"
        "\n"
        "    def stop(self) -> None:\n"
        "        print('stop ran')\n"
    )


@pytest.fixture(params=sorted(OVERRIDES))
def project(request: pytest.FixtureRequest, project_tree) -> Path:
    return project_tree(
        pyproject='[project]\nname = "shadowing"\nversion = "0.1.0"\n'
        "dependencies = []\n",
        jobs={"pg.py": _module(OVERRIDES[request.param])},
    )


def _names(cli_run, cwd: Path) -> list[str]:
    result = cli_run(["builtin", "info", "jobs", "--json"], cwd=cwd)
    assert result.exit_code == 0, result.stderr
    return sorted(row["name"] for row in json.loads(result.stdout))


class TestAnOverriddenMethodIsNotAJob:
    def test_only_the_effective_method_is_listed_cold_and_warm(
        self, cli_run, project: Path
    ) -> None:
        cold = _names(cli_run, project)
        warm = _names(cli_run, project)

        assert cold == warm == ["pg.stop"]

    def test_the_scan_records_no_failure(self, cli_run, project: Path) -> None:
        result = cli_run(["builtin", "info", "--json"], cwd=project)

        assert result.exit_code == 0, result.stderr
        assert json.loads(result.stdout)["discovery_failures"] == []

    def test_the_sibling_method_runs(self, cli_run, project: Path) -> None:
        result = cli_run(["pg", "stop"], cwd=project)

        assert result.exit_code == 0, result.stderr
        assert "stop ran" in result.stdout

    def test_the_overridden_name_is_not_a_command(self, cli_run, project: Path) -> None:
        result = cli_run(["pg", "start"], cwd=project)

        assert result.exit_code != 0
        assert "Unknown command 'start'" in result.stderr
        assert "ran" not in result.stdout
