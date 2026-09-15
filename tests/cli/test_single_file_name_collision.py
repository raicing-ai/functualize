"""`func script.py job` runs the job in *that file*, whatever else is named the same.

`run-request-entry`/T11 made `engine.run()` resolve a job by **name**, and
`_handle_single_file` registers the named function so the lookup can find it.
Its guard was `if app.get_job(name) is None` — the name being *free* — and the
app single-file mode builds still discovers the surrounding project. So a file
whose function shares a name with a project job found that job already
registered, skipped registering its own, and ran somebody else's under the name
the user typed.

Found by `workflow-graph-semantics`/T7's gate, in
`examples/standalone/showcase`, where `scripts/hello.py` and `jobs/surfaces.py`
both define `greet`:

    func scripts/hello.py greet --name World
    TypeError: greet() got an unexpected keyword argument 'enthusiasm'

**That traceback was luck.** The two happened to declare different config
classes, so the flags never collapsed into a model and the call failed loudly.
Two jobs with compatible signatures would have run the wrong one in silence and
printed a plausible answer — which is why the first test here asserts *which
function ran* rather than that the command exited 0.
"""

from __future__ import annotations

from pathlib import Path

from tests.conftest import surfaces

#: The file the user names. Its `greet` takes a config model with two fields.
_TARGET = """\
from pydantic import BaseModel, Field

from functualize.job import job


class Greeting(BaseModel):
    name: str = Field(description="Who to greet")
    volume: int = Field(default=1, ge=1, le=3, description="How loudly")


@job
def greet(config: Greeting) -> str:
    message = f"TARGET {config.name}{'!' * config.volume}"
    print(message)
    return message
"""

#: A project job of the same name, with a *different* config model — the shape
#: that made the original break visible.
_PROJECT_JOB_DIFFERENT_SHAPE = """\
from pydantic import BaseModel, Field

from functualize.job import job


class Other(BaseModel):
    city: str = Field(default="oslo", description="Somewhere else entirely")


@job
def greet(config: Other) -> str:
    print(f"PROJECT {config.city}")
    return config.city
"""

#: A project job of the same name whose signature the target's flags *fit*.
#: Without the fix this one runs and succeeds, printing a wrong answer.
_PROJECT_JOB_COMPATIBLE = """\
from pydantic import BaseModel, Field

from functualize.job import job


class Greeting(BaseModel):
    name: str = Field(description="Who to greet")
    volume: int = Field(default=1, ge=1, le=3, description="How loudly")


@job
def greet(config: Greeting) -> str:
    print(f"PROJECT {config.name}")
    return config.name
"""


def _project(tmp_path: Path, job_source: str) -> Path:
    """A project whose discovered jobs include one called `greet`.

    The target lives in `scripts/`, mirroring the showcase this was found in —
    and deliberately *not* in the project root, where the working-directory
    scan would register it as a project job too and the collision would be a
    different one (two discovered jobs, not a script versus a project).
    """
    jobs = tmp_path / ".functualize" / "jobs"
    jobs.mkdir(parents=True)
    (jobs / "surfaces.py").write_text(job_source)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "hello.py").write_text(_TARGET)
    return tmp_path


@surfaces("func")
class TestTheNamedFileWins:
    def test_the_targets_own_job_runs_when_a_project_job_shares_its_name(
        self, cli_run, tmp_path: Path
    ) -> None:
        """The reported case. `PROJECT` in the output means the wrong one ran."""
        project = _project(tmp_path, _PROJECT_JOB_DIFFERENT_SHAPE)

        result = cli_run(["scripts/hello.py", "greet", "--name", "World"], cwd=project)

        combined = result.stdout + result.stderr
        assert result.exit_code == 0, combined
        assert "TARGET World!" in result.stdout, combined
        assert "PROJECT" not in combined, combined

    def test_it_is_not_merely_that_the_command_succeeds(
        self, cli_run, tmp_path: Path
    ) -> None:
        """The silent half, and the reason the assertion above names a function.

        Here the project's `greet` accepts exactly the flags the target
        declares, so before the fix the command exited **0** and printed a
        confident, wrong answer. Nothing about the exit code could have caught
        it.
        """
        project = _project(tmp_path, _PROJECT_JOB_COMPATIBLE)

        result = cli_run(["scripts/hello.py", "greet", "--name", "World"], cwd=project)

        combined = result.stdout + result.stderr
        assert result.exit_code == 0, combined
        assert "TARGET World!" in result.stdout, combined
        assert "PROJECT World" not in combined, combined

    def test_the_project_job_is_still_reachable_by_its_own_name(
        self, cli_run, tmp_path: Path
    ) -> None:
        """The file-qualified identity is for the *target*, not a takeover.

        A project whose own `greet` stopped working because somebody added a
        script would be the same defect pointing the other way.
        """
        project = _project(tmp_path, _PROJECT_JOB_DIFFERENT_SHAPE)

        result = cli_run(["greet", "--city", "bergen"], cwd=project)

        combined = result.stdout + result.stderr
        assert result.exit_code == 0, combined
        assert "PROJECT bergen" in result.stdout, combined


@surfaces("func")
def test_a_file_with_no_collision_keeps_its_bare_identity(
    cli_run, tmp_path: Path
) -> None:
    """Only the colliding case moves.

    The registry key is also the **env and config prefix**, so qualifying it
    unconditionally would silently change where every single-file job reads its
    settings from. `GREET_NAME` resolving proves the identity is still `greet`.
    """
    (tmp_path / "hello.py").write_text(_TARGET)

    result = cli_run(["hello.py", "greet"], cwd=tmp_path, env={"GREET_NAME": "FromEnv"})

    combined = result.stdout + result.stderr
    assert result.exit_code == 0, combined
    assert "TARGET FromEnv" in result.stdout, combined
