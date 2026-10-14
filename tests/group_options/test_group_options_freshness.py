"""A resolved GroupOptions value is part of the freshness key.

`func demo --target a scan`, then `func demo --target b scan`: the second run
was skipped as "up to date" and handed back the first run's record, because
the key hashed the job's own config model plus the caller's explicit
arguments — and a `GroupOptions` parameter is neither. It is resolved against
the *group's* config section and injected, so the key subtracted it along with
the DI capabilities. The `FromJob` consequence was worse than a missed
rebuild: `report` under `--target b` received the value `scan` recorded under
`--target a` (`REPORT target=b scanned=a`), with exit 0 and nothing printed.

Both directions are pinned, because the fix is only right if it is narrow: a
changed option misses, an unchanged option still hits.
"""

from __future__ import annotations

import subprocess
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import pytest

from functualize._app.state import AppState
from functualize._primitives.fingerprint import (
    canonical_json,
    compute_args_hash,
)
from functualize.app.core import FunctualizeApp
from functualize.job import (
    Fingerprint,
    FromJob,
    GroupOptions,
    Log,
    Option,
    RunStatus,
    job,
)
from functualize.types import RunRequest

if TYPE_CHECKING:
    from functualize._types import JobResult

PROJECT_ROOT = Path(__file__).parent.parent.parent


class DemoOptions(GroupOptions, group="demo"):
    """The `demo` group's flags — the group the report types at."""

    target: Annotated[str, Option("--target", help="Which target to scan")] = "a"


@pytest.fixture(autouse=True)
def _isolated_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None]:
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    (project / "input.txt").write_text("unchanged\n", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(project)
    AppState.reset()
    yield
    AppState.reset()


def _app(scans: list[str], reports: list[tuple[str, str | None]]) -> FunctualizeApp:
    """``scan`` (cached, reads the group option) and two consumers of it.

    ``report`` declares the upstream (``FromJob`` with the default
    ``run=True``); ``peek`` only reads what is recorded (``run=False``), so it
    exercises the reader-side key with no dependency run to mask it.
    """
    app = FunctualizeApp(name="freshness-group-options")

    @job(cache=Fingerprint(sources=["input.txt"]))
    def scan(opts: DemoOptions = None, log: Log = None) -> str:
        scans.append(opts.target)
        return opts.target

    @job
    def report(
        scanned: Annotated[str, FromJob("scan")], opts: DemoOptions = None
    ) -> None:
        reports.append((opts.target, scanned))

    @job
    def peek(
        scanned: Annotated[str | None, FromJob("scan", run=False)] = None,
        opts: DemoOptions = None,
    ) -> None:
        reports.append((opts.target, scanned))

    app.register_dynamic_job("scan", scan)
    app.register_dynamic_job("report", report)
    app.register_dynamic_job("peek", peek)
    return app


def _run(app: FunctualizeApp, job_name: str, target: str | None) -> JobResult:
    """Through the engine with a group-CLI layer, as the dispatcher does."""
    return app._execution_engine.run(
        RunRequest(
            job_name=job_name,
            surface="app.execute",
            group_option_values={"target": target} if target is not None else None,
        )
    )


class TestTheKeyFollowsTheOption:
    """AC-1 and AC-2: a changed option misses, an unchanged one hits."""

    def test_a_changed_option_runs_again(self) -> None:
        scans: list[str] = []
        app = _app(scans, [])

        first = _run(app, "scan", "a")
        second = _run(app, "scan", "b")

        assert first.status is RunStatus.SUCCESS, repr(first.exception)
        # Before the fix this was SKIPPED and `scans == ["a"]`: the record
        # written under `a` answered for `b`.
        assert second.status is RunStatus.SUCCESS, repr(second.exception)
        assert scans == ["a", "b"]

    def test_the_same_option_is_still_fresh(self) -> None:
        """No gratuitous invalidation — and with a `Log` capability declared
        beside the option, so an injected capability's `repr` cannot be what
        makes the key move."""
        scans: list[str] = []
        app = _app(scans, [])

        _run(app, "scan", "a")
        again = _run(app, "scan", "a")

        assert again.status is RunStatus.SKIPPED, repr(again.exception)
        assert scans == ["a"]

    def test_going_back_hits_the_first_record(self) -> None:
        """Each option value keeps its own record: a → b → a reruns nothing
        on the third call."""
        scans: list[str] = []
        app = _app(scans, [])

        _run(app, "scan", "a")
        _run(app, "scan", "b")
        third = _run(app, "scan", "a")

        assert third.status is RunStatus.SKIPPED
        assert scans == ["a", "b"]

    def test_an_option_from_the_environment_moves_the_key_too(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The key is the *resolved* value, whichever layer supplied it."""
        scans: list[str] = []
        app = _app(scans, [])

        _run(app, "scan", None)  # default: a
        monkeypatch.setenv("DEMO__TARGET", "fromenv")
        AppState.reset()
        again = _run(app, "scan", None)

        assert again.status is RunStatus.SUCCESS
        assert scans == ["a", "fromenv"]


class TestFromJobNeverCrossesOptionValues:
    """AC-3: the report's `REPORT target=b scanned=a` case."""

    def test_the_consumer_receives_the_value_for_its_own_option(self) -> None:
        scans: list[str] = []
        reports: list[tuple[str, str | None]] = []
        app = _app(scans, reports)

        _run(app, "scan", "a")
        result = _run(app, "report", "b")

        assert result.status is RunStatus.SUCCESS, repr(result.exception)
        # Before the fix: `[("b", "a")]` — the dependency ran under `b`
        # (group options reach a `Deps`/`FromJob` upstream), was judged fresh
        # under the option-blind key, and the consumer read `a`'s record.
        assert reports == [("b", "b")]
        assert scans == ["a", "b"]

    def test_a_read_only_consumer_does_not_read_another_options_record(
        self,
    ) -> None:
        """`run=False` causes no work, so the reader-side key alone decides
        what it receives: nothing recorded for `b` means the default."""
        reports: list[tuple[str, str | None]] = []
        app = _app([], reports)

        _run(app, "scan", "a")
        _run(app, "peek", "b")
        _run(app, "peek", "a")

        assert reports == [("b", None), ("a", "a")]


class TestTheKeyFormula:
    """AC-5's injected-parameter case and the no-option invariant."""

    def test_a_job_without_group_options_keeps_its_key(self) -> None:
        """No group options, no new key: every record written before this
        change still addresses the same key, byte for byte."""
        import hashlib

        legacy = hashlib.sha256(
            canonical_json({"config": {"x": 1}, "args": {"y": 2}}).encode()
        ).hexdigest()

        assert compute_args_hash({"x": 1}, {"y": 2}) == legacy
        assert compute_args_hash({"x": 1}, {"y": 2}, {}) == legacy

    def test_group_options_change_the_hash(self) -> None:
        a = compute_args_hash(None, {}, {"opts": {"target": "a"}})
        b = compute_args_hash(None, {}, {"opts": {"target": "b"}})

        assert a != b
        assert a != compute_args_hash(None, {})

    def test_the_writer_counts_the_injected_option_and_nothing_else(self) -> None:
        """The option is *injected* (`context.injected`), like a capability —
        the writer must keep it while still subtracting the capability."""
        app = _app([], [])
        engine = app._execution_engine
        captured: dict[str, str] = {}

        original = engine._args_hash_for

        def spy(context: object) -> str:
            value = original(context)
            injected = getattr(context, "injected", set())
            assert "opts" in injected and "log" in injected
            captured[context.call_kwargs["opts"].target] = value  # type: ignore[attr-defined]
            return value

        engine._args_hash_for = spy  # type: ignore[method-assign]
        _run(app, "scan", "a")
        _run(app, "scan", "b")

        assert set(captured) == {"a", "b"}
        assert captured["a"] != captured["b"]
        # The reader holding only a job name and the same option layer
        # addresses the key the writer wrote.
        assert (
            engine.fingerprint_key_for(
                "scan", "checksum", group_option_values={"target": "b"}
            )
            == f"scan::{captured['b']}::checksum"
        )
        assert engine.fingerprint_key_for("scan", "checksum") == (
            f"scan::{captured['a']}::checksum"
        )


_JOBS_MODULE = """\
from typing import Annotated

from functualize.job import Fingerprint, FromJob, GroupOptions, Option, job

JOB_GROUP = "demo"


class DemoOptions(GroupOptions, group="demo"):
    target: Annotated[str, Option("--target", help="Which target")] = "a"


@job(group=JOB_GROUP, cache=Fingerprint(sources=["input.txt"]))
def scan(opts: DemoOptions = None) -> str:
    print(f"SCAN target={opts.target}")
    return opts.target


@job(group=JOB_GROUP)
def report(
    scanned: Annotated[str, FromJob("demo.scan")], opts: DemoOptions = None
) -> None:
    print(f"REPORT target={opts.target} scanned={scanned}")
"""


def _func(*args: str, cwd: Path, home: Path) -> subprocess.CompletedProcess[str]:
    env = {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "PATH": __import__("os").environ["PATH"],
    }
    return subprocess.run(
        ["uv", "run", "--project", str(PROJECT_ROOT), "func", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
        timeout=120,
    )


class TestTheReportAcrossProcesses:
    """The report's own shape: separate `func` processes, so no live value
    in hand can mask a record read."""

    @pytest.fixture
    def project(self, tmp_path: Path) -> Path:
        project = tmp_path / "cli"
        (project / ".functualize").mkdir(parents=True)
        (project / ".functualize.toml").write_text('jobs_directories = ["jobs"]\n')
        (project / "input.txt").write_text("unchanged\n")
        (project / "jobs").mkdir()
        (project / "jobs" / "demo.py").write_text(_JOBS_MODULE)
        return project

    def test_report_b_after_scan_a_reads_b(self, project: Path, tmp_path: Path) -> None:
        home = tmp_path / "cli-home"
        home.mkdir()

        first = _func("demo", "--target", "a", "scan", cwd=project, home=home)
        assert first.returncode == 0, first.stderr
        second = _func("demo", "--target", "b", "report", cwd=project, home=home)
        assert second.returncode == 0, second.stderr

        assert "REPORT target=b scanned=b" in second.stdout, second.stdout
        assert "scanned=a" not in second.stdout

    def test_why_agrees_with_a_group_option_run(
        self, project: Path, tmp_path: Path
    ) -> None:
        """`why` reads the key through the engine, so adding the option to the
        writer's key did not leave `why` reading the option-blind one."""
        home = tmp_path / "cli-home"
        home.mkdir()

        assert _func("demo", "scan", cwd=project, home=home).returncode == 0
        why = _func("builtin", "why", "demo.scan", cwd=project, home=home)

        assert "up to date" in why.stdout + why.stderr, why.stdout + why.stderr
