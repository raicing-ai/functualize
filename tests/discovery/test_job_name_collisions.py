"""Two functions claiming one job name: reported, not silently dropped.

Job names are canonicalized to lowercase-hyphenated form, so two distinct
functions can resolve to one address. There are two shapes and, before this,
the registration path every `func` invocation uses dropped a job silently for
both:

| shape | measured on 0.2.3 |
|---|---|
| `build_wheel` + `buildWheel` in one file | one job, no message, `discovery_failures: []` |
| `build_wheel` in `a.py` and in `b.py` | one job, no message, **winner random per boot** |

The second row is the worse finding and was not in the original report. Eight
cold boots of unmodified 0.2.3 over the same two files produced winners
`b b a b b a a a`: `_list_jobs` imports new files while iterating a *set*
difference, and string-hash randomization reorders it per process. So the job
that survived kept changing behaviour with nothing changing on disk.

Both shapes now keep one claimant — the last by entry key, which preserves the
outcome in the case that was already deterministic — and report every other
claimant through `discovery_failures`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize._discovery.cached_provider import CachedDirectoryScanProvider
from functualize._primitives.locator import ResourceLocator
from functualize._types.discovery_report import JOB_NAME_COLLISION

TWO_SPELLINGS = '''
def build_wheel() -> None:
    """Build the wheel (snake_case spelling)."""

def buildWheel() -> None:  # noqa: N802
    """Build the wheel (camelCase spelling)."""
'''

ONE_SPELLING = '''
def build_wheel() -> None:
    """Build the wheel."""
'''

TWO_CLEAN_JOBS = '''
def alpha() -> None:
    """Alpha."""

def beta() -> None:
    """Beta."""
'''


@pytest.fixture
def jobs_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "jobs"
    directory.mkdir()
    return directory


def _provider(tmp_path: Path, jobs_dir: Path) -> CachedDirectoryScanProvider:
    """A provider whose cache lives under `tmp_path`, so a fresh one is cold
    and a second one over the same `tmp_path` is warm."""
    locator = (
        ResourceLocator()
        .search_explicit(tmp_path / "cache")
        .write_to_explicit(tmp_path / "cache")
    )
    return CachedDirectoryScanProvider(
        directories=[str(jobs_dir)], locator=locator, project_root=tmp_path
    )


def _collisions(provider: CachedDirectoryScanProvider) -> list[str]:
    return [
        f.message
        for f in provider.discovery_failures
        if f.error_type == JOB_NAME_COLLISION
    ]


class TestTwoSpellingsInOneFile:
    """`build_wheel` and `buildWheel` -> the job `build-wheel`."""

    def test_one_job_survives_and_the_other_is_reported(
        self, tmp_path: Path, jobs_dir: Path
    ) -> None:
        (jobs_dir / "wheels.py").write_text(TWO_SPELLINGS)
        provider = _provider(tmp_path, jobs_dir)

        jobs = provider.list_jobs()

        assert [d.name for d in jobs] == ["build-wheel"]
        assert len(_collisions(provider)) == 1

    def test_the_surviving_function_does_not_move(
        self, tmp_path: Path, jobs_dir: Path
    ) -> None:
        """A2. Asserted by Python name, not by count: "report and skip" reads
        like first-wins, and implementing it that way would change which
        function runs for a project that already collides."""
        (jobs_dir / "wheels.py").write_text(TWO_SPELLINGS)
        provider = _provider(tmp_path, jobs_dir)

        (survivor,) = provider.list_jobs()

        assert survivor.python_name == "build_wheel"

    def test_the_report_names_the_dropped_claimant(
        self, tmp_path: Path, jobs_dir: Path
    ) -> None:
        (jobs_dir / "wheels.py").write_text(TWO_SPELLINGS)
        provider = _provider(tmp_path, jobs_dir)
        provider.list_jobs()

        (message,) = _collisions(provider)

        assert "'buildWheel'" in message
        assert "'build_wheel'" in message
        assert "'build-wheel'" in message

    def test_the_dropped_function_is_unreachable_by_either_spelling(
        self, tmp_path: Path, jobs_dir: Path
    ) -> None:
        """There is no second address to reach it by: both spellings *are*
        `build-wheel`, which is what makes this a collision rather than two
        jobs. So a lookup under either one resolves to the survivor, and the
        dropped function is not callable through the provider at all."""
        (jobs_dir / "wheels.py").write_text(TWO_SPELLINGS)
        provider = _provider(tmp_path, jobs_dir)
        provider.list_jobs()

        for spelling in ("build-wheel", "buildWheel", "build_wheel"):
            resolved = provider.get_job(spelling)
            assert resolved is not None
            assert resolved.python_name == "build_wheel"


class TestOneSpellingInTwoFiles:
    """`build_wheel` in `a.py` and in `b.py` -> both want `build-wheel`."""

    def test_one_job_survives_and_the_other_is_reported(
        self, tmp_path: Path, jobs_dir: Path
    ) -> None:
        (jobs_dir / "a.py").write_text(ONE_SPELLING)
        (jobs_dir / "b.py").write_text(ONE_SPELLING)
        provider = _provider(tmp_path, jobs_dir)

        jobs = provider.list_jobs()

        assert [d.name for d in jobs] == ["build-wheel"]
        assert len(_collisions(provider)) == 1

    def test_the_winner_is_deterministic(self, tmp_path: Path, jobs_dir: Path) -> None:
        """A4. This is the criterion the original spec got wrong: it asked for
        today's winner to be preserved, and there was no stable winner to
        preserve. Sorting the entry key makes it well-defined."""
        (jobs_dir / "a.py").write_text(ONE_SPELLING)
        (jobs_dir / "b.py").write_text(ONE_SPELLING)
        provider = _provider(tmp_path, jobs_dir)

        (survivor,) = provider.list_jobs()

        assert survivor.module_path == "b"

    def test_a_rebuilt_index_picks_the_same_winner(
        self, tmp_path: Path, jobs_dir: Path
    ) -> None:
        """The property the eight-boot `b b a b b a a a` measurement violated:
        repeated resolution over unchanged files gives one answer. Rebuilding
        from the same entries is the in-process equivalent of a second boot."""
        (jobs_dir / "a.py").write_text(ONE_SPELLING)
        (jobs_dir / "b.py").write_text(ONE_SPELLING)
        provider = _provider(tmp_path, jobs_dir)
        provider.list_jobs()

        winners = set()
        for _ in range(8):
            provider._reindex_by_name()
            winners.add(provider._by_name["build-wheel"].module_path)

        assert winners == {"b"}


class TestTheReportSurvivesAWarmBoot:
    """The first design reported cold and went silent warm.

    `contributor/reference/pitfalls.md`: four of its eighteen shipped defects
    were visible only on the warm-cache path. A collision is not a *read*
    failure, so it cannot rely on the retry that keeps import failures visible
    — it is re-derived from retained entries, which is why both claimants are
    now persisted.
    """

    def test_a_second_provider_over_the_same_cache_still_reports(
        self, tmp_path: Path, jobs_dir: Path
    ) -> None:
        """A6. The second provider imports nothing: it loads the cache the
        first one wrote."""
        (jobs_dir / "wheels.py").write_text(TWO_SPELLINGS)
        _provider(tmp_path, jobs_dir).list_jobs()

        warm = _provider(tmp_path, jobs_dir)
        jobs = warm.list_jobs()

        assert [d.name for d in jobs] == ["build-wheel"]
        assert len(_collisions(warm)) == 1

    def test_both_claimants_are_persisted(self, tmp_path: Path, jobs_dir: Path) -> None:
        """The mechanism behind the criterion above: keyed by job name, the
        loser was overwritten at write time and could not be re-derived."""
        (jobs_dir / "wheels.py").write_text(TWO_SPELLINGS)
        _provider(tmp_path, jobs_dir).list_jobs()

        warm = _provider(tmp_path, jobs_dir)

        retained = sorted(d.python_name for d in warm._entries.values())
        assert retained == ["buildWheel", "build_wheel"]

    def test_the_warm_winner_matches_the_cold_winner(
        self, tmp_path: Path, jobs_dir: Path
    ) -> None:
        (jobs_dir / "wheels.py").write_text(TWO_SPELLINGS)
        cold = _provider(tmp_path, jobs_dir)
        (cold_survivor,) = cold.list_jobs()

        (warm_survivor,) = _provider(tmp_path, jobs_dir).list_jobs()

        assert warm_survivor.python_name == cold_survivor.python_name


class TestACleanTreeIsUnaffected:
    """A10. The guard must not invent collisions for ordinary projects."""

    def test_no_collision_is_reported(self, tmp_path: Path, jobs_dir: Path) -> None:
        (jobs_dir / "things.py").write_text(TWO_CLEAN_JOBS)
        provider = _provider(tmp_path, jobs_dir)

        jobs = provider.list_jobs()

        assert sorted(d.name for d in jobs) == ["alpha", "beta"]
        assert _collisions(provider) == []

    def test_the_same_file_rescanned_reports_nothing(
        self, tmp_path: Path, jobs_dir: Path
    ) -> None:
        """One function reaching the index twice across passes is idempotent
        re-registration, not a collision (A11)."""
        (jobs_dir / "things.py").write_text(TWO_CLEAN_JOBS)
        _provider(tmp_path, jobs_dir).list_jobs()

        warm = _provider(tmp_path, jobs_dir)
        warm.list_jobs()

        assert _collisions(warm) == []
