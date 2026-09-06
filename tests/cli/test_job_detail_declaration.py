"""`job_detail` exposes the four fields `@job` declares about a job.

`@job(tags=…, examples=…, extra_description=…, category=…)` survives discovery
*and* the cache onto `descriptor.declaration`. `job_detail` — the payload the
CLI renders and the MCP tool list is built from — dropped all four.

That made the one direction that matters impossible. An agent can find a job;
it could not walk from that job to the judgment explaining when to use it,
because the judgment was on the descriptor and never in the payload.

The exact key set is asserted, not a subset. A fifth declaration field must
not be able to appear silently: this payload is a contract, and a consumer
that keys off it needs to know when it grows.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from functualize._cli.info import job_catalog, job_detail
from functualize.app import FunctualizeApp, JobSources

DETAIL_KEYS = {
    "name",
    "group",
    "summary",
    "docstring",
    "parameters",
    "dependencies",
    "requires_tty",
    "uses_live",
    "source_file",
    "module_path",
    "python_name",
    "inputSchema",
    # The four this task adds.
    "tags",
    "examples",
    "extra_description",
    "category",
}

CATALOG_KEYS = {"name", "group", "summary", "parameters", "requires_tty"}

JOBS = '''
from functualize.job import job


@job(
    tags=("deploy", "safe"),
    examples=("func deploy --env prod",),
    extra_description="Ships the built artifact to the named environment.",
    category="deployment",
)
def deploy(env: str = "dev") -> None:
    """Deploy the app."""


def by_convention(x: int = 1) -> None:
    """No decorator at all."""
'''


def _app(tmp_path: Path) -> FunctualizeApp:
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "m.py").write_text(textwrap.dedent(JOBS))
    return FunctualizeApp(
        "d", job_sources=JobSources(directories=[str(jobs)], lazy=False)
    )


class TestTheDeclaredJob:
    def test_the_four_fields_are_present_and_populated(self, tmp_path: Path) -> None:
        detail = job_detail(_app(tmp_path), "deploy")
        assert detail is not None
        assert detail["tags"] == ["deploy", "safe"]
        assert detail["examples"] == ["func deploy --env prod"]
        assert detail["extra_description"].startswith("Ships the built artifact")
        assert detail["category"] == "deployment"

    def test_they_are_lists_not_tuples(self, tmp_path: Path) -> None:
        """`JobDeclaration` stores tuples; the payload is JSON, and a tuple is
        not a JSON type. Serialising would coerce it, but a caller reading the
        dict directly would get a tuple where the schema says array."""
        detail = job_detail(_app(tmp_path), "deploy")
        assert detail is not None
        assert isinstance(detail["tags"], list)
        assert isinstance(detail["examples"], list)

    def test_the_payload_survives_json(self, tmp_path: Path) -> None:
        import json

        detail = job_detail(_app(tmp_path), "deploy")
        assert json.loads(json.dumps(detail))["tags"] == ["deploy", "safe"]


class TestTheConventionDiscoveredJob:
    """`declaration is None`. The four keys must be present and empty — not
    absent, and not a `KeyError` — so a consumer never branches on which kind
    of job it is looking at."""

    def test_the_keys_are_present(self, tmp_path: Path) -> None:
        detail = job_detail(_app(tmp_path), "by-convention")
        assert detail is not None
        assert {"tags", "examples", "extra_description", "category"} <= set(detail)

    def test_they_render_empty_rather_than_missing(self, tmp_path: Path) -> None:
        detail = job_detail(_app(tmp_path), "by-convention")
        assert detail is not None
        assert detail["tags"] == []
        assert detail["examples"] == []
        assert detail["extra_description"] is None
        assert detail["category"] is None


class TestTheExactKeySet:
    """The guard. A fifth declaration field cannot appear silently."""

    def test_job_detail_has_exactly_these_keys(self, tmp_path: Path) -> None:
        detail = job_detail(_app(tmp_path), "deploy")
        assert detail is not None
        assert set(detail) == DETAIL_KEYS

    def test_a_convention_job_has_the_same_key_set(self, tmp_path: Path) -> None:
        """Both shapes of job publish the same keys, which is the property
        that lets a consumer skip the branch."""
        detail = job_detail(_app(tmp_path), "by-convention")
        assert detail is not None
        assert set(detail) == DETAIL_KEYS

    def test_job_catalog_is_unchanged(self, tmp_path: Path) -> None:
        """The shallow listing stays shallow. Its own docstring says
        "deliberately shallow"; tags belong in the deep view, and widening the
        listing would cost every `func` invocation that renders it."""
        catalog = job_catalog(_app(tmp_path))
        assert catalog
        for entry in catalog:
            assert set(entry) == CATALOG_KEYS


class TestThroughTheCli:
    """Reachability, both call sites.

    `tasks.md` names `func builtin info schema <job>` as the path. It is not:
    `info schema` renders `command_schemas`, which walks the command tree and
    builds from `node.params()` — it never calls `job_detail`, and it has no
    `--json` flag because it is always JSON. `grep -n "job_detail"` finds
    exactly two callers, and these are them.
    """

    def test_info_jobs_carries_them(self, cli_run, project_tree) -> None:
        import json

        root = project_tree(jobs={"m.py": textwrap.dedent(JOBS)})
        result = cli_run(["builtin", "info", "jobs", "deploy", "--json"], cwd=root)
        assert result.exit_code == 0, result.stderr
        detail = json.loads(result.stdout)
        assert detail["tags"] == ["deploy", "safe"]
        assert detail["category"] == "deployment"
        assert set(detail) == DETAIL_KEYS

    def test_the_full_report_carries_them(self, cli_run, project_tree) -> None:
        import json

        root = project_tree(jobs={"m.py": textwrap.dedent(JOBS)})
        result = cli_run(["builtin", "info", "--json"], cwd=root)
        assert result.exit_code == 0, result.stderr
        jobs = {j["name"]: j for j in json.loads(result.stdout)["jobs"] if j}
        assert jobs["deploy"]["examples"] == ["func deploy --env prod"]
        assert jobs["by-convention"]["tags"] == []
