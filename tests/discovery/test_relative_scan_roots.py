"""`exclude_patterns` must not depend on how the caller spelled its directory.

Found while re-measuring `eager-boot-provider` against master, and it affected
**both** boot paths — so fixing only the eager one would have left them equally
wrong while the feature claimed "both paths honour your filters":

    JobSources(directories=["jobs"])       + exclude_patterns=("skipme.py",)  ->  skipme.py ADMITTED
    JobSources(directories=["/abs/jobs"])  + exclude_patterns=("skipme.py",)  ->  skipme.py excluded

`GlobExcludePreFilter` decides which scan root a candidate belongs to with
`Path.relative_to`, which is textual: a relative root can never contain an
absolute candidate path. So the loop found no containing root, fell through to
its permissive default, and every pattern was silently ignored.

`func --exclude` was never affected — the CLI resolves its roots before
building filters — which is why this survived: the covered surface happened to
spell paths the one way that worked, and the natural spelling for a
library-mode host is the broken one.

Fixed in the filter rather than in its callers, so no future caller has to know
which spelling is safe.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize import FunctualizeApp
from functualize._discovery.filter_factory import build_pre_filter_from_config
from functualize._primitives.pre_filter import GlobExcludePreFilter
from functualize.app.config import DiscoveryConfig, JobSources

JOB = 'def {name}() -> None:\n    """A job."""\n'


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "keeper.py").write_text(JOB.format(name="kept"))
    (jobs / "skipme.py").write_text(JOB.format(name="skipped_job"))
    return tmp_path


class TestTheFilterItself:
    """One level below the app, so a failure here localizes immediately."""

    def test_a_relative_root_still_judges_an_absolute_candidate(
        self, tree: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Relative root, absolute candidate — the combination that silently
        admitted everything. The root resolves against the working directory,
        so this has to be built from inside the tree, not before entering it.
        """
        monkeypatch.chdir(tree)
        jobs = tree / "jobs"
        pre_filter = build_pre_filter_from_config(
            DiscoveryConfig(exclude_patterns=("skipme.py",)),
            Path("jobs"),
            [Path("jobs")],
        )

        assert pre_filter.should_import(jobs / "skipme.py") is False
        assert pre_filter.should_import(jobs / "keeper.py") is True

    def test_an_absolute_root_is_unchanged(self, tree: Path) -> None:
        """The spelling that already worked must keep working."""
        jobs = tree / "jobs"
        pre_filter = build_pre_filter_from_config(
            DiscoveryConfig(exclude_patterns=("skipme.py",)), jobs, [jobs]
        )

        assert pre_filter.should_import(jobs / "skipme.py") is False
        assert pre_filter.should_import(jobs / "keeper.py") is True

    def test_a_file_under_no_scan_root_is_still_admitted(self, tree: Path) -> None:
        """The permissive default is deliberate and stays: a candidate with no
        containing root has nothing to relativize against. The defect was
        reaching that default for files that *did* have one.

        Asserted on the glob filter alone rather than the composed stack: the
        composed stack also contains filters that read the candidate, and a
        file outside the tree is a different question from a file that cannot
        be read.
        """
        jobs = tree / "jobs"
        elsewhere = tree / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "skipme.py").write_text(JOB.format(name="outside"))
        pre_filter = GlobExcludePreFilter(("skipme.py",), jobs, [jobs])

        assert pre_filter.should_import(elsewhere / "skipme.py") is True


@pytest.mark.parametrize("lazy", [True, False], ids=["lazy", "eager"])
class TestThroughTheApp:
    """A14-A16, on both boot paths."""

    def test_a_relative_directory_honours_exclude_patterns(
        self, tree: Path, lazy: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A14."""
        monkeypatch.chdir(tree)

        app = FunctualizeApp(
            "t",
            job_sources=JobSources(directories=["jobs"], lazy=lazy),
            discovery_config=DiscoveryConfig(exclude_patterns=("skipme.py",)),
        )

        assert [d.name for d in app.get_jobs()] == ["kept"]

    def test_a_relative_directory_honours_require_file_prefix(
        self, tree: Path, lazy: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A15. This one already worked — it matches on the filename and never
        relativizes — and is pinned so the fix cannot be mistaken for making
        filtering work at all rather than making one filter path-independent."""
        monkeypatch.chdir(tree)
        (tree / "jobs" / "job_extra.py").write_text(JOB.format(name="extra"))

        app = FunctualizeApp(
            "t",
            job_sources=JobSources(directories=["jobs"], lazy=lazy),
            discovery_config=DiscoveryConfig(require_file_prefix="job_"),
        )

        assert [d.name for d in app.get_jobs()] == ["extra"]

    def test_both_spellings_of_one_directory_admit_the_same_set(
        self, tree: Path, lazy: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A16. They also shared one cache entry, so a run under one spelling
        could serve stale results to the other."""
        monkeypatch.chdir(tree)
        config = DiscoveryConfig(exclude_patterns=("skipme.py",))

        relative = FunctualizeApp(
            "r",
            job_sources=JobSources(directories=["jobs"], lazy=lazy),
            discovery_config=config,
        )
        absolute = FunctualizeApp(
            "a",
            job_sources=JobSources(directories=[str(tree / "jobs")], lazy=lazy),
            discovery_config=config,
        )

        assert sorted(d.name for d in relative.get_jobs()) == sorted(
            d.name for d in absolute.get_jobs()
        )
