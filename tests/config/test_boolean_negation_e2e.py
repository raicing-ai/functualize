"""A boolean set `true` in a config file can be turned off from the CLI.

Capability coverage, per `CONSTITUTION.md`: a test that calls the param builder
directly proves the flag is *rendered*, not that it *resolves*. The whole defect
was that the ladder's CLI > env > file promise was three-quarters true for
booleans, and only a run through the public entry point can observe that.

Driven through `cli_run`, the in-process runner that exercises the real
boot → resolve → route → execute stack (`.spec/TESTING.md`).
"""

from __future__ import annotations

_JOBS = """
from pydantic import BaseModel, Field

from functualize.job import Log, job


class RunConfig(BaseModel):
    verbose: bool = Field(default=False, description="Chatty output")


@job
def report(log: Log, config: RunConfig) -> None:
    print(f"VERBOSE={config.verbose}")
"""

_CONFIG = """
[report]
verbose = true
"""


class TestTheLadderIsWholeForBooleans:
    """A1 and A7 — the three cells that make the promise true."""

    def _project(self, project_tree):
        # Job config values live in `config.base.toml`; `.functualize.toml` is
        # settings-only. Putting the section in the wrong file resolves nothing
        # and looks exactly like a broken default.
        return project_tree(
            jobs={"r.py": _JOBS}, extra_files={"config.base.toml": _CONFIG}
        )

    def test_the_negative_flag_overrides_a_config_true(
        self, cli_run, project_tree
    ) -> None:
        """The defect. Before this feature no spelling could do it."""
        root = self._project(project_tree)

        result = cli_run(["report", "--no-verbose"], cwd=root)

        assert result.exit_code == 0, result.stderr
        assert "VERBOSE=False" in result.stdout

    def test_the_positive_flag_still_works(self, cli_run, project_tree) -> None:
        root = self._project(project_tree)

        result = cli_run(["report", "--verbose"], cwd=root)

        assert result.exit_code == 0, result.stderr
        assert "VERBOSE=True" in result.stdout

    def test_neither_flag_resolves_from_the_config_file(
        self, cli_run, project_tree
    ) -> None:
        """A7 — the control.

        A pair declared with the wrong default would report a value nobody
        typed, at the highest precedence there is. This is the cell that
        catches it: absence must still fall through to the file's `true`.
        """
        root = self._project(project_tree)

        result = cli_run(["report"], cwd=root)

        assert result.exit_code == 0, result.stderr
        assert "VERBOSE=True" in result.stdout
