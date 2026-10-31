"""A job class whose public methods are all inherited is discovered.

`spec.md` defines a job class's public methods as those defined on the class
*or on one of its bases*, and `contracts.md` § C2's canonical `PooledPostgres`
declares none of its own: `start` and `stop` come from `LocalPostgres`, here in
a sibling module. Discovery always walked the MRO; what dropped this shape was
the admission filter, which looked for a method in the class body and so never
imported the file — no job, no finding.

Every fact below is read back from `func`, so a regression in the filter, the
scan or the warm cache reads as a missing job rather than as a disagreement
with a helper.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import surfaces

#: The base, in its own module: the concrete class and its abstract parent.
#: Neither carries `@job`, so neither is a job class (F1-a, F1-b).
DATABASES = """\
from abc import abstractmethod

from pydantic import BaseModel


class Database(BaseModel):
    host: str = "localhost"

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...


class LocalPostgres(Database):
    def start(self) -> None:
        print(f"start ran on {self.host}")

    def stop(self) -> None:
        print(f"stop ran on {self.host}")
"""

#: `contracts.md` § C2's `PooledPostgres`, verbatim in shape: an opt-in, a
#: field, and no method of its own.
POOLED = """\
from databases import LocalPostgres

from functualize.job import job


@job(group="postgres_tuned")
class PooledPostgres(LocalPostgres):
    pool_size: int = 20
"""

#: A plain model: no method, no `@job`. Importing it has a visible side
#: effect, so "the filter did not admit it" is observable from outside.
MODELS = """\
from pathlib import Path

from pydantic import BaseModel

Path(__file__).with_name("models.imported").write_text("imported")


class Settings(BaseModel):
    host: str = "localhost"
"""


@pytest.fixture()
def project(project_tree) -> Path:
    return project_tree(
        pyproject='[project]\nname = "inherited"\nversion = "0.1.0"\n'
        "dependencies = []\n",
        jobs={"databases.py": DATABASES, "pooled.py": POOLED, "models.py": MODELS},
    )


def _names(cli_run, cwd: Path) -> list[str]:
    result = cli_run(["builtin", "info", "jobs", "--json"], cwd=cwd)
    assert result.exit_code == 0, result.stderr
    return sorted(row["name"] for row in json.loads(result.stdout))


def _jobs_dir(project: Path) -> Path:
    (pooled,) = project.rglob("pooled.py")
    return pooled.parent


class TestInheritedOnlyJobClass:
    def test_the_catalog_lists_the_inherited_methods(
        self, cli_run, project: Path
    ) -> None:
        assert _names(cli_run, project) == [
            "postgres-tuned.start",
            "postgres-tuned.stop",
        ]

    def test_the_catalog_is_the_same_on_a_warm_cache(
        self, cli_run, project: Path
    ) -> None:
        cold = _names(cli_run, project)
        warm = _names(cli_run, project)

        assert warm == cold == ["postgres-tuned.start", "postgres-tuned.stop"]

    def test_an_inherited_method_runs(self, cli_run, project: Path) -> None:
        result = cli_run(["postgres-tuned", "start"], cwd=project)

        assert result.exit_code == 0, result.stderr
        assert "start ran on localhost" in result.stdout

    @surfaces("func")
    def test_a_plain_model_module_is_still_not_imported(
        self, cli_run, project: Path
    ) -> None:
        """`func` only: it scans through the admission filter this widens.

        A `FunctualizeApp` built without a discovery config applies no
        pre-filter and imports every module, before this change and after it,
        so the question "did the filter admit it?" does not arise there.
        """
        _names(cli_run, project)

        assert not (_jobs_dir(project) / "models.imported").exists()
