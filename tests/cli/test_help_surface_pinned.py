"""``func --help`` is a global-flags page, and stays one.

The top-level help lists exactly one command — ``builtin``. Not the discovered
jobs, not the job groups, not the commands a plugin registered. That is a
**decision**, taken 2026-09-08, not an accident of the lazy-boot design:
``--help`` is intercepted pre-boot (``_cli/main.py``, the ``"--help" in
sys.argv`` branch) and routed to a plain click group carrying only what
``register_builtin_commands`` mounts, which is the single ``builtin`` name.

The command index lives elsewhere and is reachable three ways: bare ``func``
(the TUI on a terminal, a job list when piped), ``func builtin info schema``
for the machine-readable form, and ``func <namespace>`` to drill into a group.

This test exists because the surrounding feature adds plugin commands to the
*command tree*, and the command tree feeds several surfaces that render command
lists. It would be an easy and plausible-looking mistake to let them reach this
one too. If a change makes ``func --help`` grow a row, this fails — and the fix
is to put the row on the surface that wanted it, not to relax the assertion.
"""

from __future__ import annotations

from tests.conftest import surfaces

# About the bare `func` entry point specifically: the pre-boot `--help`
# interception exists only there. A `FunctualizeApp`'s own click group is
# assembled by `CliAdapter`, mounts its jobs deliberately, and is a different
# contract — pinning it here would assert something this decision never said.
pytestmark = surfaces("func")


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


class TestTopLevelHelpListsOnlyBuiltin:
    def test_commands_block_is_exactly_builtin(self, cli_run, project_tree) -> None:
        """One row, and it is ``builtin`` — even with jobs present to tempt it."""
        project = project_tree(
            jobs={
                "tasks.py": (
                    "from functualize import job\n"
                    "\n"
                    "@job\n"
                    "def deploy() -> None:\n"
                    '    """Deploy the thing."""\n'
                )
            }
        )
        result = cli_run(["--help"], cwd=project)

        assert result.exit_code == 0
        rows = _commands_block(result.stdout)
        assert len(rows) == 1, f"expected one command row, got {rows}"
        assert rows[0].startswith("builtin"), rows[0]

    def test_discovered_jobs_are_absent(self, cli_run, project_tree) -> None:
        """A job that `func` can run is still not advertised here."""
        project = project_tree(
            jobs={
                "tasks.py": (
                    "from functualize import job\n"
                    "\n"
                    "@job\n"
                    "def deploy() -> None:\n"
                    '    """Deploy the thing."""\n'
                )
            }
        )
        result = cli_run(["--help"], cwd=project)

        assert result.exit_code == 0
        assert "deploy" not in _commands_block(result.stdout)

    def test_help_is_stable_across_two_invocations(self, cli_run, project_tree) -> None:
        """Cold and warm render identically.

        The second run reads the discovery cache the first one wrote. Since the
        help page is not supposed to reflect discovery at all, the two must be
        byte-identical — a divergence would mean discovery had leaked in.
        """
        project = project_tree(
            jobs={
                "tasks.py": (
                    "from functualize import job\n"
                    "\n"
                    "@job\n"
                    "def deploy() -> None:\n"
                    '    """Deploy the thing."""\n'
                )
            }
        )
        cold = cli_run(["--help"], cwd=project)
        warm = cli_run(["--help"], cwd=project)

        assert cold.exit_code == warm.exit_code == 0
        assert cold.stdout == warm.stdout
