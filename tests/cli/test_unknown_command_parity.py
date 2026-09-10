"""#37 — a typo is explained on both entry points, not only on `func`.

When discovery knows why a typed name is not a command, the user gets to hear
it: `explain_missing_job` reads the failed module's source and says so. Both
reporters call it, because which surface you reached the program through does
not change why one of its jobs is missing
(`contributor/architecture/surface-boundary.md`).

The app's own entry point never reached its reporter. It was a plain
`click.Group`, so click raised `NoSuchCommand` during resolution — before the
fallback chain that calls `_show_command_not_found` — and standalone mode
rendered `Error: No such command 'fetch'.` with exit 2. `func` said why, and
exited 1.

The body runs **twice** — `cli_run` is parameterised over `func` and `app` —
and that is the whole test: the `app` half is the one that used to fail.
"""

from __future__ import annotations

GOOD = 'def hello() -> None:\n    """Say hi."""\n    print("hi")\n'

IMPORT_ERROR = (
    'import totally_missing_pkg\n\n\ndef fetch() -> None:\n    """Fetch a thing."""\n'
)

NAME_COLLISION = (
    "def build_wheel() -> None:\n"
    '    """snake_case spelling."""\n'
    "\n"
    "\n"
    "def buildWheel() -> None:  # noqa: N802\n"
    '    """camelCase spelling."""\n'
)


def _broken(project_tree):
    return project_tree(jobs={"greet.py": GOOD, "needs_dep.py": IMPORT_ERROR})


def test_it_names_the_failed_file_and_the_reason(cli_run, project_tree) -> None:
    """The explanation `func` produces, now produced on an app too."""
    result = cli_run(["fetch"], cwd=_broken(project_tree))

    combined = result.stdout + result.stderr
    assert "failed to load, so the job it defines is missing" in combined
    assert "totally_missing_pkg" in combined


def test_it_is_not_clicks_own_usage_error(cli_run, project_tree) -> None:
    """The before-symptom, asserted: click's message carries no explanation.

    `No such command` is what an app printed *instead of* the reporter's
    output, and it is a different sentence from the one `func` prints — so a
    test that only looked for the reporter's line could not tell the two
    apart.
    """
    result = cli_run(["fetch"], cwd=_broken(project_tree))

    assert "No such command" not in result.stdout + result.stderr


def test_an_unattributable_name_gets_the_generic_note(cli_run, project_tree) -> None:
    """A typo no failed module defines still reports that discovery failed."""
    result = cli_run(["typoo"], cwd=_broken(project_tree))

    assert "discovery problem" in result.stdout + result.stderr


def test_the_generic_note_does_not_claim_a_load_failure(cli_run, project_tree) -> None:
    """Three kinds share the failure list and only one is a load failure."""
    root = project_tree(jobs={"greet.py": GOOD, "wheels.py": NAME_COLLISION})

    result = cli_run(["typoo"], cwd=root)

    combined = result.stdout + result.stderr
    assert "discovery problem" in combined
    assert "failed to load" not in combined


def test_a_typo_exits_one(cli_run, project_tree) -> None:
    """`func`'s answer, on both: the run did not happen. Not click's usage 2.

    The number is the contract a wrapper script reads, so the two entry points
    answering it differently is the defect, not a cosmetic difference.
    """
    result = cli_run(["typoo"], cwd=project_tree(jobs={"greet.py": GOOD}))

    assert result.exit_code == 1


def test_a_clean_project_grows_no_paragraph(cli_run, project_tree) -> None:
    """Nothing failed, so there is nothing to explain."""
    result = cli_run(["typoo"], cwd=project_tree(jobs={"greet.py": GOOD}))

    combined = result.stdout + result.stderr
    assert "typoo" in combined
    assert "discovery problem" not in combined
    assert "failed to load" not in combined
