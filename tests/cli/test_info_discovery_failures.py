"""`func builtin info` reports what discovery could not read.

The defect this closes: a job module that fails to load contributed no jobs
and logged one line to stderr. By the time an operator asks "why is my job
missing?", that line has scrolled past — so `info` showed a short list and no
explanation, and the only way to find the cause was to reproduce the boot with
the logger turned up.

4.1 retains the failures on the provider. This is where they become visible.

Two spellings differ between the artifacts, deliberately: `contracts.md` §3
calls the key `import_failures`, written before the scope widened to cover
parse failures too. `tasks.md` 4.1 renames it `discovery_failures`, which is
what shipped — `import_failures` would be actively wrong for a `SyntaxError`,
which never reaches the import path.

The gate in `tasks.md` also used to read `func builtin info --output json`,
which is unexecutable: `Error: No such option '--output'`. The shipped flag is
`--json`. `--output` is the spelling *proposed* by
`shape-intents/output-flag-normalization.md`, which is unimplemented; if that
lands, this command moves with every other, not ahead of them.
"""

from __future__ import annotations

import json

import pytest

GOOD = (
    '"""Demo jobs."""\n'
    "\n"
    "\n"
    "def healthy(rows: int = 3) -> None:\n"
    '    """A job that loads."""\n'
)

SYNTAX_ERROR = 'def broken(x: int = 1) -> None\n    """Missing the colon."""\n'

IMPORT_ERROR = (
    "import nonexistent_module_xyz\n"
    "\n"
    "\n"
    "def unreachable() -> None:\n"
    '    """Never registered."""\n'
)


def _report(cli_run, cwd) -> dict:
    result = cli_run(["builtin", "info", "--json"], cwd=cwd)
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


class TestTheKeyIsAlwaysThere:
    def test_a_clean_tree_reports_an_empty_list(self, cli_run, project_tree) -> None:
        """Present and `[]`, never absent — a consumer must not need a guard,
        and an absent key reads as "this build is too old to know", which is a
        different statement from "nothing is wrong"."""
        report = _report(cli_run, project_tree(jobs={"jobs.py": GOOD}))
        assert report["discovery_failures"] == []

    def test_the_key_survives_a_tree_with_no_jobs_at_all(
        self, cli_run, project_tree
    ) -> None:
        report = _report(cli_run, project_tree(jobs={}))
        assert report["discovery_failures"] == []


class TestABrokenModuleIsReported:
    def test_an_import_failure_names_the_module_and_the_exception(
        self, cli_run, project_tree
    ) -> None:
        root = project_tree(jobs={"jobs.py": GOOD, "importer.py": IMPORT_ERROR})
        report = _report(cli_run, root)

        failures = report["discovery_failures"]
        assert len(failures) == 1
        entry = failures[0]
        assert entry["module"] == "importer"
        assert entry["path"].endswith("importer.py")
        assert entry["error_type"] == "ModuleNotFoundError"
        assert "nonexistent_module_xyz" in entry["message"]

    def test_a_parse_failure_is_reported_too(self, cli_run, project_tree) -> None:
        """STATUS #12, at the surface. A module with a plain typo never reaches
        the import path, so an import-only report would have shown `[]` here —
        which reads as "nothing is wrong"."""
        root = project_tree(jobs={"jobs.py": GOOD, "broken.py": SYNTAX_ERROR})
        report = _report(cli_run, root)

        failures = report["discovery_failures"]
        assert [f["error_type"] for f in failures] == ["SyntaxError"]
        assert failures[0]["path"].endswith("broken.py")

    def test_the_payload_carries_exactly_the_four_documented_keys(
        self, cli_run, project_tree
    ) -> None:
        root = project_tree(jobs={"importer.py": IMPORT_ERROR})
        entry = _report(cli_run, root)["discovery_failures"][0]
        assert set(entry) == {"module", "path", "error_type", "message"}

    def test_the_healthy_jobs_are_still_listed(self, cli_run, project_tree) -> None:
        """A broken module must stay non-fatal. Reporting the failure is worth
        nothing if it costs the rest of the tree."""
        root = project_tree(jobs={"jobs.py": GOOD, "importer.py": IMPORT_ERROR})
        report = _report(cli_run, root)
        assert "healthy" in {job["name"] for job in report["jobs"] if job}
        assert report["discovery_failures"]


class TestThePlainRendering:
    """`--json` is for agents; a human runs bare `info`. Both must say it."""

    def test_plain_output_names_the_file_and_the_error(
        self, cli_run, project_tree, monkeypatch
    ) -> None:
        monkeypatch.setenv("FUNCTUALIZE_CLI_OUTPUT", "plain")
        root = project_tree(jobs={"jobs.py": GOOD, "importer.py": IMPORT_ERROR})
        result = cli_run(["builtin", "info"], cwd=root)

        assert result.exit_code == 0
        assert "discovery failures (1)" in result.stdout
        assert "importer.py" in result.stdout
        assert "ModuleNotFoundError" in result.stdout

    def test_plain_output_says_nothing_when_there_is_nothing_to_say(
        self, cli_run, project_tree, monkeypatch
    ) -> None:
        monkeypatch.setenv("FUNCTUALIZE_CLI_OUTPUT", "plain")
        root = project_tree(jobs={"jobs.py": GOOD})
        result = cli_run(["builtin", "info"], cwd=root)
        assert "discovery failures" not in result.stdout

    def test_the_failures_are_printed_above_the_job_list(
        self, cli_run, project_tree, monkeypatch
    ) -> None:
        """This is the explanation for a job list that looks too short. An
        explanation printed below the thing it explains gets scrolled past."""
        monkeypatch.setenv("FUNCTUALIZE_CLI_OUTPUT", "plain")
        root = project_tree(jobs={"jobs.py": GOOD, "importer.py": IMPORT_ERROR})
        out = cli_run(["builtin", "info"], cwd=root).stdout
        assert out.index("discovery failures") < out.index("jobs (")


class TestTheReaderIsRobust:
    """`discovery_failures()` reaches through two private attributes by
    attribute access — `_cli` may not import `_discovery`, and B5 may not add
    public API. So it must degrade rather than raise when either is absent."""

    def test_it_returns_empty_for_an_app_with_no_pipeline(self) -> None:
        from functualize._cli.info import discovery_failures

        class _Bare:
            pass

        assert discovery_failures(_Bare()) == []  # type: ignore[arg-type]

    def test_providers_without_the_attribute_contribute_nothing(self) -> None:
        """`StaticProvider`, and anything a plugin adds, do not scan."""
        from functualize._cli.info import discovery_failures
        from functualize._discovery.providers import StaticProvider
        from functualize.app import FunctualizeApp, JobSources

        def alpha() -> None:
            """Alpha."""

        app = FunctualizeApp(
            "a", job_sources=JobSources(job_providers=[StaticProvider([alpha])])
        )
        assert discovery_failures(app) == []


@pytest.mark.parametrize("modules", [{"a.py": SYNTAX_ERROR, "b.py": IMPORT_ERROR}])
def test_both_stages_arrive_under_one_key(cli_run, project_tree, modules) -> None:
    """The point of one key rather than two: a consumer never has to know
    which stage rejected what."""
    report = _report(cli_run, project_tree(jobs={"jobs.py": GOOD, **modules}))
    kinds = {f["error_type"] for f in report["discovery_failures"]}
    assert kinds == {"SyntaxError", "ModuleNotFoundError"}


TWO_SPELLINGS = (
    '"""Two functions, one job name."""\n'
    "\n"
    "\n"
    "def build_wheel() -> None:\n"
    '    """Build the wheel (snake_case spelling)."""\n'
    "\n"
    "\n"
    "def buildWheel() -> None:  # noqa: N802\n"
    '    """Build the wheel (camelCase spelling)."""\n'
)


class TestAJobNameCollisionIsReportedHereToo:
    """A collision is the same user-visible fact as a failed import — a job
    the user wrote is not in the CLI — so it is published through the same key
    rather than a second report type.
    """

    def test_it_appears_with_its_own_error_type(self, cli_run, project_tree) -> None:
        """A5. `error_type` is not an exception class name here, because
        nothing is raised; every other value in the field is one."""
        root = project_tree(jobs={"wheels.py": TWO_SPELLINGS})

        report = _report(cli_run, root)

        collisions = [
            f
            for f in report["discovery_failures"]
            if f["error_type"] == "JobNameCollision"
        ]
        assert len(collisions) == 1
        assert "build-wheel" in collisions[0]["message"]

    def test_the_job_list_is_not_shortened_further(self, cli_run, project_tree) -> None:
        """One claimant still registers. Reporting must not cost the survivor."""
        root = project_tree(jobs={"wheels.py": TWO_SPELLINGS})

        report = _report(cli_run, root)

        assert [j["name"] for j in report["jobs"]] == ["build-wheel"]

    def test_it_is_still_reported_on_a_second_invocation(
        self, cli_run, project_tree
    ) -> None:
        """A6, the criterion that shaped the design. Import failures survive a
        warm boot only because a module that fails to import is retried every
        boot. A file that parses is cached and never re-read, so a collision
        had to be re-derivable from the cache — which is why both claimants
        are now persisted rather than one overwriting the other on write."""
        root = project_tree(jobs={"wheels.py": TWO_SPELLINGS})
        _report(cli_run, root)

        warm = _report(cli_run, root)

        assert [
            f
            for f in warm["discovery_failures"]
            if f["error_type"] == "JobNameCollision"
        ]

    def test_the_cli_still_works(self, cli_run, project_tree) -> None:
        """A12. The alternative design raised at boot, which takes down every
        command — including the two an operator would reach for to find out
        what is wrong."""
        root = project_tree(jobs={"wheels.py": TWO_SPELLINGS})

        assert cli_run(["builtin", "info"], cwd=root).exit_code == 0
        assert cli_run(["build-wheel"], cwd=root).exit_code == 0

    def test_a_clean_tree_reports_no_collision(self, cli_run, project_tree) -> None:
        root = project_tree(jobs={"jobs.py": GOOD})

        report = _report(cli_run, root)

        assert report["discovery_failures"] == []
