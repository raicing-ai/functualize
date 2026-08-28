"""Resolved values are coerced toward their declared type before validation.

Two defects met here, and they had the same root: `coerce_value` — the function
that implements every conversion config sources actually need — had **zero
production callers**. It was reachable only from its own recursion. So:

- `docs/guides/job-config.md` documented comma-separated lists for environment
  variables and config files. Nothing implemented it.
- `Secret[str]` gained a `coerce_value` branch during the secrets work, added
  to a function nothing called.

A `list[T]` field was worse than uncoerced: it resolved to `[]` regardless of
what any source said. `list[T]` becomes a click option with `multiple=True`,
and click hands those `()` when the flag is absent — `default=None` does not
apply to a multiple option — so `() is not None` made an unpassed flag win the
whole precedence ladder, including over the model's own default.

The gap: every config fixture in the suite used `str` and `int` fields. A
precedence ladder was thoroughly tested for the two shapes where nothing
needed converting.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from functualize.types import Secret

PYPROJECT = """\
[project]
name = "coercion-project"
version = "0.1.0"
"""

JOBS = """
from pydantic import BaseModel, Field

from functualize.job import RunContext
from functualize.job.decorators import job


class ListConfig(BaseModel):
    targets: list[str] = Field(default_factory=lambda: ["the-model-default"])
    ports: list[int] = Field(default_factory=list)


@job(extra_description="Has list fields")
def deploy(config: ListConfig, rc: RunContext) -> str:
    print(f"targets={config.targets!r}")
    print(f"ports={config.ports!r}")
    return "ok"
"""

CONFIG_FILE = """\
[deploy]
targets = "from-a, from-the-file"
"""


@pytest.fixture()
def list_project(project_tree):
    return project_tree(pyproject=PYPROJECT, jobs={"job_deploy.py": JOBS})


@pytest.fixture()
def list_project_with_file(project_tree):
    return project_tree(
        pyproject=PYPROJECT,
        jobs={"job_deploy.py": JOBS},
        extra_files={"config.base.toml": CONFIG_FILE},
    )


def _printed(stdout: str, field: str) -> str:
    for line in stdout.splitlines():
        if line.startswith(f"{field}="):
            return line.split("=", 1)[1].strip()
    return ""


class TestAListFieldReachesItsSources:
    def test_the_model_default_applies(self, cli_run, list_project):
        """The plainest case, and it did not work: every list resolved to `[]`."""
        result = cli_run(["deploy"], cwd=list_project)

        assert _printed(result.stdout, "targets") == "['the-model-default']", (
            "an unpassed list flag still outranks the model's own default"
        )

    def test_a_comma_separated_environment_variable_splits(self, cli_run, list_project):
        """The form `docs/guides/job-config.md` documents."""
        result = cli_run(["deploy"], cwd=list_project, env={"DEPLOY_TARGETS": "a,b,c"})

        assert _printed(result.stdout, "targets") == "['a', 'b', 'c']"

    def test_a_comma_separated_config_file_value_splits(
        self, cli_run, list_project_with_file
    ):
        result = cli_run(["deploy"], cwd=list_project_with_file)

        assert _printed(result.stdout, "targets") == "['from-a', 'from-the-file']"

    def test_the_inner_type_is_coerced(self, cli_run, list_project):
        """`list[int]` from a string must yield ints, not strings."""
        result = cli_run(["deploy"], cwd=list_project, env={"DEPLOY_PORTS": "80, 443"})

        assert _printed(result.stdout, "ports") == "[80, 443]"

    def test_passing_the_flag_still_wins(self, cli_run, list_project):
        """Guard the guard: treating `()` as absent must not ignore real values."""
        result = cli_run(
            ["deploy", "--targets", "x", "--targets", "y"],
            cwd=list_project,
            env={"DEPLOY_TARGETS": "ignored"},
        )

        assert _printed(result.stdout, "targets") == "['x', 'y']"


class TestABadValueIsStillReportedByPydantic:
    def test_coercion_does_not_swallow_the_error(self, cli_run, list_project):
        """`int("banana")` raises a bare ValueError naming nothing.

        Coercion is best-effort for exactly this reason: on failure the raw
        value goes to Pydantic, which names the field, the type and the input.
        """
        result = cli_run(
            ["deploy"], cwd=list_project, env={"DEPLOY_PORTS": "not-a-port"}
        )

        assert result.exit_code != 0
        combined = result.stdout + result.stderr
        assert "ports" in combined


class TestTheSecretWrapperIsApplied:
    """`coerce_value`'s `Secret` branch, now that something calls it."""

    def test_a_resolved_string_becomes_a_secret(self):
        from functualize._config.job_config import coerce_value

        wrapped = coerce_value("hunter2", Secret[str])

        assert isinstance(wrapped, Secret)
        assert wrapped.get_secret_value() == "hunter2"

    def test_an_existing_secret_is_left_alone(self):
        from functualize._config.job_config import coerce_value

        original = Secret("hunter2")
        assert coerce_value(original, Secret[str]) is original


class TestTheTypeGateIsHonestAboutSecret:
    def test_secret_str_is_accepted(self):
        from functualize._config.job_config import validate_job_config_types

        class Good(BaseModel):
            token: Secret[str]

        validate_job_config_types(Good)

    def test_secret_of_anything_else_is_refused(self):
        """`Secret` stores `str(value)`, so `Secret[int]` is a claim it cannot keep.

        It used to pass the gate — the wrapper unwraps to `str` — and the job
        then received a `Secret` holding `"123"` for a field the model reported
        as `int`.
        """
        from functualize._config.job_config import validate_job_config_types

        class Bad(BaseModel):
            port: Secret[int]

        with pytest.raises(TypeError, match=r"Secret\[int\]"):
            validate_job_config_types(Bad)
