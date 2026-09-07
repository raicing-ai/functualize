"""A job that is missing says why, where the user is actually looking.

A job module that cannot be imported is skipped, so its jobs never exist. The
user's model is *my job is broken*; the CLI's answer was *it never existed*:

    $ func fetch
    WARNING:functualize._discovery.cached_provider:Failed to import and extract
    from '/tmp/.../needs_dep.py': No module named 'totally_missing_pkg'
    Error: Unknown command 'fetch'.

The structured report behind this shipped earlier and already survives a warm
boot. What was missing was every place a user would look:

* the **default** rendering of `builtin info` did not show it — the plain and
  JSON ones did, including the comment explaining why failures print *above*
  the job list, which had reached two renderers and not the default;
* `builtin self doctor`, whose whole job is "what is wrong here", reported
  "1 discovered" and stopped;
* the unknown-command error did not connect the typed name to the failed file;
* and the one line that did explain it was a raw logger dump.

Three kinds of finding now share that list — a source that would not load, two
functions colliding on one job name, and a job whose parameters cannot be
satisfied — so each gap hid three classes of problem, not one.
"""

from __future__ import annotations

import json

import pytest

GOOD = 'def hello() -> None:\n    """Say hi."""\n    print("hi")\n'

IMPORT_ERROR = (
    'import totally_missing_pkg\n\n\ndef fetch() -> None:\n    """Fetch a thing."""\n'
)

SYNTAX_ERROR = 'def broken(x: int = 1) -> None\n    """Missing the colon."""\n'

NAME_COLLISION = (
    "def build_wheel() -> None:\n"
    '    """snake_case spelling."""\n'
    "\n"
    "\n"
    "def buildWheel() -> None:  # noqa: N802\n"
    '    """camelCase spelling."""\n'
)

UNSATISFIABLE = (
    "class Database:\n"
    '    """Nothing registers a provider for this."""\n'
    "\n"
    "\n"
    "def deploy(db: Database) -> None:\n"
    '    """Cannot run."""\n'
)


def _broken(project_tree):
    return project_tree(jobs={"greet.py": GOOD, "needs_dep.py": IMPORT_ERROR})


class TestTheDefaultRenderingReportsFailures:
    """A1-A4. Two renderers reported this and the default one did not, which
    is the rendering everybody gets."""

    def test_it_appears(self, cli_run, project_tree) -> None:
        result = cli_run(["builtin", "info"], cwd=_broken(project_tree))

        assert result.exit_code == 0, result.stderr
        assert "Discovery Failures" in result.stdout
        assert "needs_dep.py" in result.stdout

    def test_it_appears_above_the_job_list(self, cli_run, project_tree) -> None:
        """A2. The plain renderer's own comment: an explanation printed below
        the thing it explains gets scrolled past."""
        result = cli_run(["builtin", "info"], cwd=_broken(project_tree))

        assert result.stdout.index("Discovery Failures") < result.stdout.index(
            "Discovered Jobs"
        )

    def test_a_clean_project_shows_no_section(self, cli_run, project_tree) -> None:
        """A3. An empty section is its own kind of noise."""
        result = cli_run(["builtin", "info"], cwd=project_tree(jobs={"g.py": GOOD}))

        assert "Discovery Failures" not in result.stdout

    @pytest.mark.parametrize(
        ("name", "source"),
        [
            ("needs_dep.py", IMPORT_ERROR),
            ("broken.py", SYNTAX_ERROR),
            ("wheels.py", NAME_COLLISION),
            ("dep.py", UNSATISFIABLE),
        ],
    )
    def test_every_kind_renders(self, cli_run, project_tree, name, source) -> None:
        """A4. A renderer written against import failures alone prints an
        empty row for a collision or an unsatisfiable job, which are the two
        kinds that joined the list later."""
        root = project_tree(jobs={"greet.py": GOOD, name: source})

        result = cli_run(["builtin", "info"], cwd=root)

        assert result.exit_code == 0, result.stderr
        assert "Discovery Failures" in result.stdout

    def test_it_still_appears_on_a_second_run(self, cli_run, project_tree) -> None:
        """A12. A module that fails to import is retried every boot rather
        than cached as absent, which is what keeps this true warm."""
        root = _broken(project_tree)
        cli_run(["builtin", "info"], cwd=root)

        result = cli_run(["builtin", "info"], cwd=root)

        assert "Discovery Failures" in result.stdout

    def test_the_json_report_is_unchanged(self, cli_run, project_tree) -> None:
        """The rich panel is a rendering of an existing payload, not a second
        source of truth."""
        result = cli_run(["builtin", "info", "--json"], cwd=_broken(project_tree))

        report = json.loads(result.stdout)
        assert len(report["discovery_failures"]) == 1


@pytest.mark.surfaces("func")
class TestTheUnknownCommandExplainsItself:
    """A7-A10, on the `func` entry point.

    **Restricted to one surface, deliberately and with a known gap.** The
    explanation is one function (`explain_missing_job`) called from both
    reporters, because which surface you reached the program through does not
    change why one of its jobs is absent. But a project's own `main.py`
    invokes click in standalone mode, so an unrecognized name is rendered by
    click's own `UsageError` before either reporter runs — the hint reaches
    `func` and the adapter's fallback chain, and not that path.

    Marked rather than asserted loosely: an assertion relaxed enough to pass on
    both surfaces passed *vacuously* on the second one, matching the warning
    line instead of the explanation. Recorded in `.spec/STATUS.md`.
    """

    def test_it_names_the_file_and_the_reason(self, cli_run, project_tree) -> None:
        """A7. `fetch` is defined in the file that failed, and the CLI knew."""
        result = cli_run(["fetch"], cwd=_broken(project_tree))

        combined = result.stdout + result.stderr
        assert "Unknown command 'fetch'" in combined
        assert "failed to load, so the job it defines is missing" in combined
        assert "totally_missing_pkg" in combined

    def test_an_unattributable_name_gets_the_generic_note(
        self, cli_run, project_tree
    ) -> None:
        """A9."""
        result = cli_run(["typoo"], cwd=_broken(project_tree))

        combined = result.stdout + result.stderr
        assert "Unknown command 'typoo'" in combined
        assert "discovery problem" in combined

    def test_the_generic_note_does_not_say_failed_to_load(
        self, cli_run, project_tree
    ) -> None:
        """Three kinds share the list and only one is a load failure — naming
        the wrong one sends the reader to the wrong file."""
        root = project_tree(jobs={"greet.py": GOOD, "wheels.py": NAME_COLLISION})

        result = cli_run(["typoo"], cwd=root)

        combined = result.stdout + result.stderr
        assert "discovery problem" in combined
        assert "failed to load" not in combined

    def test_a_clean_project_is_unchanged(self, cli_run, project_tree) -> None:
        """A10. A plain typo must not grow a paragraph."""
        result = cli_run(["typoo"], cwd=project_tree(jobs={"g.py": GOOD}))

        combined = result.stdout + result.stderr
        assert "Unknown command 'typoo'" in combined
        assert "discovery problem" not in combined


class TestTheWarningLine:
    """A11."""

    def test_it_carries_no_logger_name_or_internal_path(
        self, cli_run, project_tree
    ) -> None:
        """It used to print `WARNING:functualize._discovery.cached_provider:`
        and an absolute path in front of the user on every command."""
        result = cli_run(["hello"], cwd=_broken(project_tree))

        combined = result.stdout + result.stderr
        assert "needs_dep.py not loaded" in combined
        assert "functualize._discovery" not in combined

    def test_the_job_still_runs(self, cli_run, project_tree) -> None:
        """A broken module stays non-fatal to the scan — that is the design,
        and the warning must not change it."""
        result = cli_run(["hello"], cwd=_broken(project_tree))

        assert result.exit_code == 0, result.stderr
        assert "hi" in result.stdout


class TestAttributionNeverImports:
    """A8, asserted on the helper rather than through the CLI.

    Importing is the thing that failed; doing it again on an error path to
    produce a hint would run half a module's side effects. Through the CLI this
    is not observable — every boot legitimately retries the failed import,
    which is what keeps the report alive on a warm boot — so a marker file
    written at import time appears either way. The helper is where the question
    has an answer.
    """

    def test_it_reads_the_source_without_executing_it(self, tmp_path) -> None:
        from functualize._cli.info import explain_missing_job

        broken = tmp_path / "needs_dep.py"
        broken.write_text(
            "import pathlib\n"
            "pathlib.Path(__file__).parent.joinpath('imported.log').write_text('x')\n"
            "import totally_missing_pkg\n"
            "\n"
            "\n"
            "def fetch() -> None:\n"
            '    """Fetch."""\n'
        )

        class _App:
            _unsatisfiable_jobs = ()
            _resolution_pipeline = None

        explanation = explain_missing_job(
            "fetch",
            _App(),
            _failures=[
                {
                    "module": "needs_dep",
                    "path": str(broken),
                    "error_type": "ModuleNotFoundError",
                    "message": "No module named 'totally_missing_pkg'",
                }
            ],
        )

        assert explanation is not None
        assert "needs_dep.py" in explanation
        assert not (tmp_path / "imported.log").exists()

    def test_a_file_that_will_not_parse_falls_back_to_the_generic_note(
        self, tmp_path
    ) -> None:
        """Attribution needs the source to parse. A syntax error is exactly the
        case where it cannot, and the generic note still has to fire."""
        from functualize._cli.info import explain_missing_job

        broken = tmp_path / "broken.py"
        broken.write_text("def fetch() -> None\n    pass\n")

        class _App:
            _unsatisfiable_jobs = ()
            _resolution_pipeline = None

        explanation = explain_missing_job(
            "fetch",
            _App(),
            _failures=[
                {
                    "module": "broken",
                    "path": str(broken),
                    "error_type": "SyntaxError",
                    "message": "expected ':'",
                }
            ],
        )

        assert explanation is not None
        assert "discovery problem" in explanation
