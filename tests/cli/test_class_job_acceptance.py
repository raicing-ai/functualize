"""The class-job path through both CLI entry points, end to end.

`tests/engine/test_class_job_receiver.py` holds the engine still: it reads the
`ExecutionContext` a run produces and never builds a command line. This file is
the other half — the criteria of `spec.md` § Acceptance criteria, driven through
`func` and through a project's own `FunctualizeApp`, over the fixture project
those criteria name: `.functualize/jobs/pg.py` holding the `Postgres` job class
of `contracts.md` § C1, `config.base.toml` with ``[pg] host = "db.internal"``,
and one vault entry for ``password``.

Every fact below is read from a public surface — `builtin info jobs`,
`builtin info`, `builtin why`, `builtin vault`, what the job itself prints, the
shell-completion tree, and `app.get_jobs()` — so a defect in the merge, the
section, the rebind or the warm path surfaces here rather than in a test that
agrees with the implementation about where the answer came from.

The one exception is `visibility`: no surface consumes it in this repository
(the MCP server that does lives outside it), so "the class visibility is in
effect" is read off the descriptor's `JobDeclaration`, the type that carries it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from functualize._config.vault_keys import ENV_VAR as VAULT_KEY_ENV
from functualize._config.vault_keys import generate_key
from tests.conftest import surfaces

CONSTRUCTION_LOG_ENV = "CLASS_JOB_CONSTRUCTION_LOG"
VAULT_VALUE = "hunter2-from-the-vault"

#: The C1 fixture, plus the counters AC-4 needs and a docstring per method so
#: the listing has something to show.
JOBS = '''\
import os
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel

from functualize.job import Guards, Shell, job
from functualize.types import Secret

CONSTRUCTION_LOG_ENV = "CLASS_JOB_CONSTRUCTION_LOG"


class Database(BaseModel):
    """A non-job base: no ``@job`` of its own, so it is not discovered."""

    JOB_TAGS: ClassVar[tuple[str, ...]] = ("database",)
    host: str = "localhost"
    port: int = 5432


@job(group="pg", tags=["class-tag"], visibility="internal")
class Postgres(Database):
    JOB_TAGS: ClassVar[tuple[str, ...]] = ("shared", "local")

    password: Secret[str]

    def __init__(self, **data: object) -> None:
        # A dunder, so it stays a method and not a job — a public counter hook
        # would be discovered as one, which is the rule under test elsewhere.
        super().__init__(**data)
        log = os.environ.get(CONSTRUCTION_LOG_ENV)
        if log:
            with Path(log).open("a", encoding="utf-8") as handle:
                handle.write("constructed\\n")

    def start(self, sh: Shell) -> None:
        """Start the cluster."""
        print(
            f"start host={self.host} port={self.port} "
            f"password={self.password.get_secret_value()}"
        )

    @job(tags=["method-tag"], guards=Guards(preconditions=["true"]))
    def stop(self, sh: Shell, force: bool = False) -> None:
        """Stop the cluster."""
        print(
            f"stop force={force} host={self.host} "
            f"password={self.password.get_secret_value()}"
        )

    def _present(self) -> bool:
        return True
'''

CONFIG_BASE = '[pg]\nhost = "db.internal"\nport = 6000\n'
CONFIG_PROD = '[pg]\nhost = "prod.internal"\n'


@pytest.fixture()
def project(project_tree) -> Path:
    """The acceptance project: one job module, two config files, one secret."""
    root = project_tree(
        pyproject='[project]\nname = "classjobs"\nversion = "0.1.0"\n'
        "dependencies = []\n",
        jobs={"pg.py": JOBS},
    )
    (root / "config.base.toml").write_text(CONFIG_BASE, encoding="utf-8")
    (root / "config.prod.toml").write_text(CONFIG_PROD, encoding="utf-8")
    (root / "secret.txt").write_text(VAULT_VALUE, encoding="utf-8")
    return root


@pytest.fixture()
def vault_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A vault this process can open; `xdg_dirs` keeps it out of the real one."""
    monkeypatch.setenv(VAULT_KEY_ENV, generate_key())


def _provision(cli_run, project: Path, env: dict[str, str] | None = None) -> None:
    """AC-11's precondition: one group-scoped entry for the class's secret.

    The entry lands in the *selected file slot*, so a test that selects an
    environment provisions under the same selection the run will use.
    """
    init = cli_run(
        ["builtin", "vault", "init", "--key-source", "env"], cwd=project, env=env
    )
    assert init.exit_code == 0, init.stderr
    put = cli_run(
        [
            "builtin",
            "vault",
            "put",
            "--group",
            "pg",
            "--field",
            "password",
            "--file",
            "secret.txt",
        ],
        cwd=project,
        env=env,
    )
    assert put.exit_code == 0, put.stderr


def _payload(result) -> dict:
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


class TestTheListing:
    """AC-1 — the two methods and nothing else from the module."""

    def test_info_jobs_lists_exactly_the_two_methods(
        self, cli_run, project: Path
    ) -> None:
        result = cli_run(["builtin", "info", "jobs", "--json"], cwd=project)

        assert result.exit_code == 0, result.stderr
        catalog = json.loads(result.stdout)
        assert [entry["name"] for entry in catalog] == ["pg.start", "pg.stop"]
        assert {entry["group"] for entry in catalog} == {"pg"}

    def test_help_lists_the_methods_under_the_group(
        self, cli_run, project: Path
    ) -> None:
        result = cli_run(["pg", "--help"], cwd=project)

        assert result.exit_code == 0, result.stderr
        assert "start" in result.stdout
        assert "stop" in result.stdout


class TestTheReceiver:
    """AC-2 and AC-3 — what the method sees, and where each value came from."""

    @surfaces("func")
    def test_start_reads_the_group_section(self, cli_run, project, vault_key) -> None:
        _provision(cli_run, project)

        result = cli_run(["pg", "start"], cwd=project)

        assert result.exit_code == 0, result.stderr
        assert "start host=db.internal port=6000" in result.stdout

    @surfaces("func")
    def test_the_vault_value_reaches_the_receiver(
        self, cli_run, project, vault_key
    ) -> None:
        _provision(cli_run, project)

        result = cli_run(["pg", "start"], cwd=project)

        assert result.exit_code == 0, result.stderr
        assert f"password={VAULT_VALUE}" in result.stdout

    @surfaces("func")
    def test_a_method_flag_binds(self, cli_run, project, vault_key) -> None:
        _provision(cli_run, project)

        result = cli_run(["pg", "stop", "--force"], cwd=project)

        assert result.exit_code == 0, result.stderr
        assert "stop force=True" in result.stdout

    @surfaces("func")
    def test_the_environment_overlay_reaches_the_receiver(
        self, cli_run, project, vault_key
    ) -> None:
        selected = {"FUNCTUALIZE_ENV": "prod"}
        _provision(cli_run, project, env=selected)

        result = cli_run(["pg", "start"], cwd=project, env=selected)

        assert result.exit_code == 0, result.stderr
        assert "host=prod.internal" in result.stdout

    @surfaces("func")
    def test_the_group_env_override_reaches_the_receiver(
        self, cli_run, project, vault_key
    ) -> None:
        _provision(cli_run, project)

        result = cli_run(["pg", "start"], cwd=project, env={"PG__HOST": "env.internal"})

        assert result.exit_code == 0, result.stderr
        assert "host=env.internal" in result.stdout


class TestIntrospectionConstructsNothing:
    """AC-4 — listing, help and completion never build an instance."""

    def test_listing_and_help_construct_nothing(
        self, cli_run, project: Path, tmp_path: Path, monkeypatch
    ) -> None:
        log = tmp_path / "constructed.log"
        monkeypatch.setenv(CONSTRUCTION_LOG_ENV, str(log))

        listed = cli_run(["builtin", "info", "jobs", "--json"], cwd=project)
        helped = cli_run(["pg", "--help"], cwd=project)

        assert listed.exit_code == 0, listed.stderr
        assert helped.exit_code == 0, helped.stderr
        assert not log.exists(), log.read_text(encoding="utf-8")

    def test_completion_offers_the_methods_without_constructing(
        self, project: Path, tmp_path: Path, monkeypatch
    ) -> None:
        from functualize._cli.completions.data import extract_completion_data
        from functualize.app import FunctualizeApp, JobSources

        log = tmp_path / "constructed.log"
        monkeypatch.setenv(CONSTRUCTION_LOG_ENV, str(log))
        jobs = project / ".functualize" / "jobs"
        app = FunctualizeApp(
            "classjobs", job_sources=JobSources(directories=[str(jobs)], lazy=False)
        )

        tree = extract_completion_data(app).command_tree

        assert "pg" in tree[""]
        assert set(tree["pg"]) == {"start", "stop"}
        assert not log.exists(), log.read_text(encoding="utf-8")


class TestTheWarmCache:
    """AC-7's class-job half — a warm boot answers exactly as the cold one."""

    @surfaces("func")
    def test_a_second_run_matches_the_first(self, cli_run, project, vault_key) -> None:
        _provision(cli_run, project)

        cold = cli_run(["pg", "start"], cwd=project)
        warm = cli_run(["pg", "start"], cwd=project)

        assert cold.exit_code == 0, cold.stderr
        assert warm.exit_code == 0, warm.stderr
        assert warm.stdout == cold.stdout

    def test_a_second_listing_matches_the_first(self, cli_run, project: Path) -> None:
        cold = cli_run(["builtin", "info", "jobs", "--json"], cwd=project)
        warm = cli_run(["builtin", "info", "jobs", "--json"], cwd=project)

        assert cold.exit_code == 0, cold.stderr
        assert json.loads(warm.stdout) == json.loads(cold.stdout)


class TestTheVaultEntry:
    """AC-11 — one group entry feeds both methods, and neither listing leaks it."""

    @surfaces("func")
    def test_one_entry_reaches_both_methods(self, cli_run, project, vault_key) -> None:
        _provision(cli_run, project)

        start = cli_run(["pg", "start"], cwd=project)
        stop = cli_run(["pg", "stop"], cwd=project)

        assert start.exit_code == 0, start.stderr
        assert stop.exit_code == 0, stop.stderr
        assert f"password={VAULT_VALUE}" in start.stdout
        assert f"password={VAULT_VALUE}" in stop.stdout

    @surfaces("func")
    def test_info_does_not_print_the_secret(self, cli_run, project, vault_key) -> None:
        _provision(cli_run, project)

        report = cli_run(["builtin", "info", "--json"], cwd=project)
        detail = cli_run(["builtin", "info", "jobs", "pg.start", "--json"], cwd=project)

        assert report.exit_code == 0, report.stderr
        assert detail.exit_code == 0, detail.stderr
        assert VAULT_VALUE not in report.stdout
        assert VAULT_VALUE not in detail.stdout

    @surfaces("func")
    def test_env_does_not_print_the_secret(self, cli_run, project, vault_key) -> None:
        _provision(cli_run, project)

        result = cli_run(["builtin", "env", "pg.start"], cwd=project)

        assert result.exit_code == 0, result.stderr
        assert VAULT_VALUE not in result.stdout


class TestTheDeclaration:
    """F2 (a) — the merged declaration, read through public payloads."""

    def test_tags_are_the_documented_merge(self, cli_run, project: Path) -> None:
        # Method's own @job(tags=), then the class's @job(tags=), then JOB_TAGS
        # outward along the MRO, nearest class first, duplicates kept at their
        # first position.
        report = _payload(cli_run(["builtin", "info", "--json"], cwd=project))
        entry = {job["name"]: job for job in report["jobs"]}

        assert entry["pg.stop"]["tags"] == [
            "method-tag",
            "class-tag",
            "shared",
            "local",
            "database",
        ]
        assert entry["pg.start"]["tags"] == [
            "class-tag",
            "shared",
            "local",
            "database",
        ]

    def test_the_methods_guards_are_in_effect(self, cli_run, project: Path) -> None:
        verdict = _payload(
            cli_run(["builtin", "why", "pg.stop", "--json"], cwd=project)
        )

        assert any(
            check.startswith("preconditions  true") for check in verdict["checks"]
        )

    def test_the_class_visibility_is_in_effect(self, project: Path) -> None:
        # No in-tree surface consumes `visibility` (the MCP server that does is
        # outside this repository), so the descriptor's declaration — the type
        # that carries it — is where the class's value can be observed at all.
        from functualize.app import FunctualizeApp, JobSources

        jobs = project / ".functualize" / "jobs"
        app = FunctualizeApp(
            "classjobs", job_sources=JobSources(directories=[str(jobs)], lazy=False)
        )

        declarations = {job.name: job.declaration for job in app.get_jobs()}
        assert declarations["pg.start"] is not None
        assert declarations["pg.start"].visibility == "internal"
        # ``stop`` carries its own @job(...), and ``visibility`` has no
        # "unset" value, so the method's declaration wins with the default.
        # Pinned in tests/discovery/test_class_jobs.py: a sentinel removes it.
        assert declarations["pg.stop"].visibility == "external"


class TestWarmEqualsCold:
    """F2 (b) — the warm proxy carries the same declaration as the cold one."""

    def test_a_warm_boot_reports_the_same_guards(self, cli_run, project: Path) -> None:
        # The group's secret comes from its environment override so the test
        # needs no vault and runs on both surfaces.
        secret = {"PG__PASSWORD": "hunter2-from-the-env"}
        cold = _payload(
            cli_run(["builtin", "why", "pg.stop", "--json"], cwd=project, env=secret)
        )
        # Runs the job, which is also what writes the discovery cache.
        ran = cli_run(["pg", "stop"], cwd=project, env=secret)
        warm = _payload(
            cli_run(["builtin", "why", "pg.stop", "--json"], cwd=project, env=secret)
        )

        assert ran.exit_code == 0, ran.stderr
        assert warm["state"] == cold["state"]
        assert warm["checks"] == cold["checks"]
        assert warm["deps"] == cold["deps"]
