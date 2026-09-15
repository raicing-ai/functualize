"""Two files cannot own one group's flags — and the user is told, not shown a traceback.

`cached_provider._record_group_options_entries` raised `GroupOptionsConflictError`
straight out of `provider.list_jobs()`, so a project with two `GroupOptions` classes bound to one
group died during boot: no group named, no file named, nothing to act on, and a half-populated
`sys.modules` behind the traceback. The audit filed it as D-12, beside ADR-018's
reported-not-fatal surface, which covered module *reads* and not this.

The provider now records it and drops the contested path; the boot seam renders it and exits with
the table's config-error code. Both halves are asserted here, because they answer different
questions: the record is what `discovery_failures` — and every renderer built on it — can answer
*"what is wrong with this project?"* with, and the rendered line is what a user gets instead of a
traceback. A conflict is not a broken module: every job still loads, and it is the *flags* that
cannot be answered, so no declaration is picked over the other.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize._discovery.cached_provider import CachedDirectoryScanProvider
from functualize._primitives.cache_format import CACHE_FILENAME
from functualize._primitives.locator import ResourceLocator
from functualize.app.utils import read_group_options_from_cache

_GROUP_MODULE = '''\
from typing import Annotated

from functualize.job import GroupOptions, Option


class DeployOptions(GroupOptions, group="deploy"):
    """Deploy-level flags."""

    env: Annotated[str, Option("-e", help="Target environment")] = "staging"
'''

_DUP_MODULE = '''\
from typing import Annotated

from functualize.job import GroupOptions, Option


class OtherDeployOptions(GroupOptions, group="deploy"):
    """A second declaration of the same group."""

    region: Annotated[str, Option("-r", help="Region")] = "eu"


def dup() -> str:
    """A job that lives beside a contested declaration."""
    return "dup"
'''

_HEALTHY = '''\
def hello() -> str:
    """Say hi."""
    return "hi"
'''

#: `ExitCode.USAGE` — a config error, the same code a Pydantic `ValidationError`
#: at invocation takes.
_USAGE = 2


@pytest.fixture(autouse=True)
def _no_module_bleed(clean_sys_modules: None) -> None:
    """Evict this suite's job modules after each test.

    The provider and the CLI importer register these files as top-level modules
    named ``_group``/``_dup``/``hello`` — generic names other suites also use.
    Left in ``sys.modules``, a stale entry shadows a later suite's
    identically-named file and its jobs silently fail to discover.
    """


def _conflicting_project(project_tree) -> Path:
    return project_tree(
        jobs={
            "_group.py": _GROUP_MODULE,
            "_dup.py": _DUP_MODULE,
            "hello.py": _HEALTHY,
        }
    )


def _make_project(root: Path, files: dict[str, str]) -> Path:
    """A project whose job modules are the given files, for the provider tests."""
    (root / "pyproject.toml").write_text(
        '[project]\nname = "probe"\nversion = "0.1.0"\ndependencies = []\n'
    )
    jobs = root / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (jobs / name).write_text(content, encoding="utf-8")
    return jobs


def _make_provider(root: Path, jobs: Path) -> CachedDirectoryScanProvider:
    cache_dir = root / ".functualize"
    locator = (
        ResourceLocator()
        .search_explicit(str(cache_dir))
        .write_to_explicit(str(cache_dir))
    )
    return CachedDirectoryScanProvider(
        directories=[str(jobs)], locator=locator, project_root=root
    )


class TestTheRenderedError:
    """AC-1: a rendered error naming both declaring files, not a traceback."""

    def test_it_names_the_group_and_both_files_and_exits_usage(
        self, project_tree, cli_run
    ) -> None:
        root = _conflicting_project(project_tree)

        result = cli_run(["hello"], cwd=root)

        assert result.exit_code == _USAGE, result.stderr
        assert "_group.py" in result.stderr, result.stderr
        assert "_dup.py" in result.stderr, result.stderr
        assert "'deploy'" in result.stderr, result.stderr
        assert "declared exactly once" in result.stderr, result.stderr

    def test_the_user_is_told_once(self, project_tree, cli_run) -> None:
        """One conflict, one sentence (adj M4).

        The provider logged `⚠ <message>` and boot printed `Error: <message>`,
        so every command in a conflicting project said the same thing twice.
        The warning defended itself as being "for the scans that never boot",
        naming `func builtin cache rebuild` — which boots, and dies at boot's
        rendered error before its own scan runs. It is `debug` now; the record a
        non-booting caller actually needs is `discovery_failures`, asserted
        below.
        """
        root = _conflicting_project(project_tree)

        result = cli_run(["hello"], cwd=root)

        combined = result.stderr + result.stdout
        assert combined.count("declared exactly once") == 1, combined

    def test_it_is_not_a_traceback(self, project_tree, cli_run) -> None:
        """The two spellings an escape takes on the two surfaces.

        A real process prints ``Traceback (most recent call last)``; the
        in-process runner records the exception's class name instead. Both mean
        the user was handed an unhandled error rather than a message.
        """
        root = _conflicting_project(project_tree)

        result = cli_run(["hello"], cwd=root)

        assert "Traceback" not in result.stderr, result.stderr
        assert "GroupOptionsConflictError" not in result.stderr, result.stderr

    def test_a_warm_run_reports_it_again(self, project_tree, cli_run) -> None:
        """The second run must not answer what the first refused to.

        The scan persists its cache before boot decides what the conflict means,
        so a warm boot re-imports the losing declaration only because the cache
        holds no group-options record for it. Were that record written, run two
        would find a cache that looks complete and serve it — the intermittent
        shape this repository treats as worse than the original defect.
        """
        root = _conflicting_project(project_tree)
        cli_run(["hello"], cwd=root)

        again = cli_run(["hello"], cwd=root)

        assert again.exit_code == _USAGE, again.stderr
        assert "_group.py" in again.stderr and "_dup.py" in again.stderr, again.stderr


class TestTheProviderRecord:
    """The provider reports; it does not raise and it does not pick a winner."""

    def test_it_records_the_conflict_instead_of_raising(self, tmp_path: Path) -> None:
        jobs = _make_project(
            tmp_path, {"_group.py": _GROUP_MODULE, "_dup.py": _DUP_MODULE}
        )
        provider = _make_provider(tmp_path, jobs)

        provider.list_jobs()  # must not raise

        failures = provider.discovery_failures
        assert [f.error_type for f in failures] == ["GroupOptionsConflictError"]
        message = failures[0].message
        assert "_group.py" in message and "_dup.py" in message
        assert "'deploy'" in message

    def test_the_conflicting_file_is_left_out_and_the_healthy_one_is_not(
        self, tmp_path: Path
    ) -> None:
        """A contested file keeps nothing in the cache, so the next boot sees it.

        It used to raise, which dropped the file from the scan anyway: a job
        defined beside the second declaration never existed. Now the drop is
        deliberate and complete — see `_forget_source_file` — because a partial
        one (the jobs kept, the declaration dropped) makes the *next* boot
        silent rather than loud.
        """
        jobs = _make_project(
            tmp_path,
            {"_group.py": _GROUP_MODULE, "_dup.py": _DUP_MODULE, "hello.py": _HEALTHY},
        )
        provider = _make_provider(tmp_path, jobs)

        names = sorted(d.name for d in provider.list_jobs())

        assert names == ["hello"]

    def test_the_contested_group_is_not_served(self, tmp_path: Path) -> None:
        """Neither declaration wins, so no stale section can be read back.

        Which file the scan reaches first is set-iteration order, so serving
        either would hand a different set of flags to a different process. The
        section for that group is empty until one declaration is removed.
        """
        jobs = _make_project(
            tmp_path, {"_group.py": _GROUP_MODULE, "_dup.py": _DUP_MODULE}
        )
        provider = _make_provider(tmp_path, jobs)
        provider.list_jobs()

        specs = read_group_options_from_cache(
            tmp_path / ".functualize" / CACHE_FILENAME, discovery_hash=None
        )

        assert specs is not None
        assert "deploy" not in specs

    def test_removing_the_second_declaration_serves_the_group_again(
        self, tmp_path: Path
    ) -> None:
        """The remedy the message names actually works, and the cache proves it."""
        jobs = _make_project(
            tmp_path, {"_group.py": _GROUP_MODULE, "_dup.py": _DUP_MODULE}
        )
        provider = _make_provider(tmp_path, jobs)
        provider.list_jobs()

        (jobs / "_dup.py").unlink()
        provider.list_jobs()

        specs = read_group_options_from_cache(
            tmp_path / ".functualize" / CACHE_FILENAME, discovery_hash=None
        )
        assert specs is not None and list(specs) == ["deploy"]
