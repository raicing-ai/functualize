"""``func --help`` lists the project's top-level commands beside ``builtin``.

The page used to list exactly one command, ``builtin``: a decision taken
2026-09-08 and pinned here, which kept discovery out of the help page. The
approved command-path shape reverses it (N3). A reader of ``func --help`` in a
project now sees the first word of every path that runs — each top-level job
and each top-level group — alongside the reserved ``builtin`` subtree.

What this file pins instead is that the page is an *inventory*, not a second
opinion: its rows are the top-level nodes of the command tree the shell, the
TUI and an app's own CLI walk, so a row cannot name something that does not
run, and a path that runs cannot be missing from it. It also keeps the old
file's other promises: cold and warm render identically, and a broken project
still gets its help page.
"""

from __future__ import annotations

from tests.conftest import surfaces

# About the bare `func` entry point specifically: the pre-boot `--help`
# interception exists only there. A `FunctualizeApp`'s own click group is
# assembled by `CliAdapter`, mounts its jobs deliberately, and is a different
# contract.
pytestmark = surfaces("func")

JOBS = {
    "tasks.py": (
        "from functualize.job import job\n"
        "\n"
        "@job\n"
        "def deploy() -> None:\n"
        '    """Deploy the thing."""\n'
    ),
    "suite.py": (
        'JOB_GROUP = "suite"\n\n'
        "def inventory() -> None:\n    pass\n\n"
        "def versions() -> None:\n    pass\n"
    ),
    "web.py": 'JOB_GROUP = "infra.web"\n\ndef run() -> None:\n    pass\n',
}


def _commands_block(help_text: str) -> list[str]:
    """The lines under ``Commands:``, up to the next blank-line boundary."""
    lines = help_text.splitlines()
    if "Commands:" not in lines:  # pragma: no cover - always rendered
        raise AssertionError(f"no 'Commands:' block in help output:\n{help_text}")
    start = lines.index("Commands:")
    out: list[str] = []
    for line in lines[start + 1 :]:
        if not line.strip():
            break
        out.append(line.strip())
    return out


def _names(help_text: str) -> list[str]:
    return [row.split()[0] for row in _commands_block(help_text)]


class TestTopLevelHelpIsTheCommandInventory:
    def test_rows_are_builtin_plus_each_top_level_job_and_group(
        self, cli_run, project_tree
    ) -> None:
        """One row per first path word; nested groups appear only at the root."""
        result = cli_run(["--help"], cwd=project_tree(jobs=JOBS))

        assert result.exit_code == 0, result.stderr
        assert _names(result.stdout) == ["builtin", "deploy", "infra", "suite"]
        rows = dict(row.split(None, 1) for row in _commands_block(result.stdout))
        assert rows["deploy"] == "Deploy the thing."
        assert "--log-level" in result.stdout, "global options must stay"

    def test_rows_match_the_paths_the_bare_listing_prints(
        self, cli_run, project_tree
    ) -> None:
        """Parity: every listed path starts with a row, and every row runs."""
        project = project_tree(jobs=JOBS)
        helped = cli_run(["--help"], cwd=project)
        listed = cli_run([], cwd=project)

        assert helped.exit_code == listed.exit_code == 0
        # Plugin namespaces close the listing as `<ns> — N commands (run …)`;
        # root help lists the project's jobs and groups, not installed plugins.
        first_words = {
            line.split()[0]
            for line in listed.stdout.splitlines()
            if "(run 'func " not in line
        }
        assert set(_names(helped.stdout)) == first_words | {"builtin"}

    def test_help_is_stable_across_two_invocations(self, cli_run, project_tree) -> None:
        """Cold and warm render identically.

        The second run reads the discovery cache the first one wrote. The rows
        come from discovery now, so a divergence would mean the two boots
        disagree about the project's shape.
        """
        project = project_tree(jobs=JOBS)
        cold = cli_run(["--help"], cwd=project)
        warm = cli_run(["--help"], cwd=project)

        assert cold.exit_code == warm.exit_code == 0
        assert cold.stdout == warm.stdout

    def test_builtin_help_is_not_given_the_project_rows(
        self, cli_run, project_tree
    ) -> None:
        result = cli_run(["builtin", "--help"], cwd=project_tree(jobs=JOBS))

        assert result.exit_code == 0
        assert "deploy" not in _names(result.stdout)
        assert "suite" not in _names(result.stdout)


class TestBrokenProjectsKeepTheirHelp:
    def test_a_module_that_fails_to_load_leaves_the_rest(
        self, cli_run, project_tree
    ) -> None:
        jobs = {**JOBS, "broken.py": "def oops(:\n"}
        result = cli_run(["--help"], cwd=project_tree(jobs=jobs))

        assert result.exit_code == 0, result.stderr
        assert "builtin" in _names(result.stdout)
        assert "deploy" in _names(result.stdout)

    def test_a_project_that_cannot_boot_still_prints_the_page(
        self, cli_run, project_tree
    ) -> None:
        """A job claiming the reserved name stops the boot, not the help."""
        jobs = {**JOBS, "reserved.py": "def builtin() -> None:\n    pass\n"}
        result = cli_run(["--help"], cwd=project_tree(jobs=jobs))

        assert result.exit_code == 0, result.stderr
        assert "--log-level" in result.stdout
        assert "builtin" in _names(result.stdout)
