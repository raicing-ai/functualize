"""`func` must tell an agent that the skills exist and where they are.

A skill directory nothing points at is a skill directory nobody loads. Two
surfaces carry the pointer and both are tested here: the ``--help`` epilog,
which is where a human trips over it, and ``builtin info``, which is where
every one of the skills instructs an agent to look first.

The paths are *computed*, never hardcoded — a documented path that stopped
being true is worse than no documentation, because it reads authoritative.
"""

from __future__ import annotations

from functualize._cli.builtins import BUILTIN_COMMANDS

from .conftest import SKILLS_ROOT


def test_skills_is_a_registered_builtin():
    """The registry is the single source of truth every other list derives from."""
    by_name = {c.name: c for c in BUILTIN_COMMANDS}
    assert "skills" in by_name
    subcommands = {s for s, _ in by_name["skills"].subcommands}
    assert subcommands == {"path", "list", "materialize", "install"}
    assert by_name["skills"].requires_subcommand


def test_help_epilog_points_at_the_skills(cli_run):
    """One line, in the epilog — `--help` prints on every mistyped command."""
    result = cli_run(["--help"])
    assert result.exit_code == 0
    assert "func builtin skills list" in result.stdout


def test_skills_path_prints_one_bare_path(cli_run):
    """`path` composes: `npx skills add "$(func builtin skills path)"`."""
    result = cli_run(["builtin", "skills", "path"])
    assert result.exit_code == 0
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines == [str(SKILLS_ROOT)]


def test_skills_list_names_every_shipped_skill(cli_run):
    """Names and descriptions come from the files, not from a hardcoded list."""
    result = cli_run(["builtin", "skills", "list"])
    assert result.exit_code == 0
    for skill_dir in sorted(p for p in SKILLS_ROOT.iterdir() if p.is_dir()):
        assert skill_dir.name in result.stdout


def test_skills_install_dry_run_targets_the_local_directory(cli_run):
    """Installing from the local directory is what pins the version.

    Pointing the skills CLI at a git ref would install whatever master says
    today, against whatever functualize the user actually has.
    """
    result = cli_run(["builtin", "skills", "install", "--dry-run"])
    assert result.exit_code == 0
    assert result.stdout.strip().endswith(str(SKILLS_ROOT))
    assert result.stdout.strip().startswith("npx skills add ")


def test_info_reports_the_skills_section(cli_run, project_tree):
    """`builtin info` is where the skills themselves send an agent first."""
    root = project_tree(jobs={"jobs.py": "def hello() -> None:\n    ...\n"})
    result = cli_run(["builtin", "info"], cwd=root)
    assert result.exit_code == 0
    assert "Agent Skills" in result.stdout
    assert str(SKILLS_ROOT) in result.stdout
