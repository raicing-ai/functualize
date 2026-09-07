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

from functualize import FunctualizeApp
from functualize._discovery.cached_provider import CachedDirectoryScanProvider
from functualize._primitives.locator import ResourceLocator
from functualize._types.discovery_report import JOB_NAME_COLLISION
from functualize.app.config import JobSources

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


def _build_wheel() -> None:
    """Build the wheel (snake_case spelling)."""


def _build_wheel_camel() -> None:
    """Build the wheel (camelCase spelling)."""


def _healthy() -> None:
    """An unrelated job that must survive a collision elsewhere."""


# `StaticProvider` derives a job name from `function.__name__`, so the two
# colliding callables must *be* named `build_wheel` and `buildWheel`.
_build_wheel.__name__ = "build_wheel"
_build_wheel_camel.__name__ = "buildWheel"
_healthy.__name__ = "healthy"


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


class TestTheEagerPathAgrees:
    """`JobSources(lazy=False)` — the library-mode opt-in for import-at-boot.

    It reached the registry through a second scanner that raised `ValueError`
    for two spellings in one file, while the default path dropped the same job
    in silence: one authoring mistake was fatal to app construction on one path
    and invisible on the other.

    No test pinned that raise — the diagnostic it produced was itself untested,
    which is why these exist. The eager scanner is deleted by
    `eager-boot-provider`; until then it warns rather than raises, and its
    structured report has no route to `builtin info` (see the TRANSITIONAL note
    at the recording site).
    """

    def test_construction_no_longer_raises(
        self, tmp_path: Path, jobs_dir: Path
    ) -> None:
        """A7. This used to be a `ValueError` out of `FunctualizeApp(...)`."""
        (jobs_dir / "wheels.py").write_text(TWO_SPELLINGS)

        app = FunctualizeApp(
            "eager", job_sources=JobSources(directories=[str(jobs_dir)], lazy=False)
        )

        assert app is not None

    def test_it_warns_instead(
        self, tmp_path: Path, jobs_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        (jobs_dir / "wheels.py").write_text(TWO_SPELLINGS)

        with caplog.at_level("WARNING"):
            FunctualizeApp(
                "eager", job_sources=JobSources(directories=[str(jobs_dir)], lazy=False)
            )

        assert any("build-wheel" in record.message for record in caplog.records)

    def test_one_job_is_registered_not_two(
        self, tmp_path: Path, jobs_dir: Path
    ) -> None:
        """A8. Shape B used to register two entries under one name on this
        path, so which one ran was undefined."""
        (jobs_dir / "a.py").write_text(ONE_SPELLING)
        (jobs_dir / "b.py").write_text(ONE_SPELLING)

        app = FunctualizeApp(
            "eager", job_sources=JobSources(directories=[str(jobs_dir)], lazy=False)
        )

        assert list(app.job_registry._registered_jobs) == ["build-wheel"]
        # And the descriptor list too: the registry dict deduped by key while
        # the list carried both, so `get_jobs()` published a duplicate.
        assert [d.name for d in app.get_jobs()] == ["build-wheel"]

    @pytest.mark.parametrize("source", [TWO_SPELLINGS, ONE_SPELLING, TWO_CLEAN_JOBS])
    def test_both_paths_admit_the_same_job_names(
        self, tmp_path: Path, source: str
    ) -> None:
        """A9. The property that matters more than either path's internals:
        `lazy` chooses *when* modules are imported, never *which* jobs exist."""
        eager_dir = tmp_path / "eager" / "jobs"
        lazy_dir = tmp_path / "lazy" / "jobs"
        for directory in (eager_dir, lazy_dir):
            directory.mkdir(parents=True)
            (directory / "wheels.py").write_text(source)

        eager = FunctualizeApp(
            "e", job_sources=JobSources(directories=[str(eager_dir)], lazy=False)
        )
        lazy = FunctualizeApp(
            "l", job_sources=JobSources(directories=[str(lazy_dir)], lazy=True)
        )

        # Lists, not sets: a set comparison passed while the eager path was
        # publishing `build-wheel` twice.
        assert sorted(d.name for d in eager.get_jobs()) == sorted(
            d.name for d in lazy.get_jobs()
        )


class TestAProviderAssembledByHand:
    """`StaticProvider`, a plugin's own provider — no cache in front of it.

    This was the third and worst answer to the same question. The pipeline
    raised `ValueError` on a duplicate name and the caller in `_app/boot.py`
    catches that and returns, so **every** job vanished — not just the
    collider — behind one logged line:

        Resolution pipeline error: Duplicate job name 'build-wheel' ...
        get_jobs()  -> []
        registry    -> {}

    Provider order is a declared precedence (the directory provider is added
    before the static one), so the first claimant wins here rather than the
    last.
    """

    def test_the_other_jobs_survive_a_collision(self, tmp_path: Path) -> None:
        app = FunctualizeApp(
            "static",
            job_sources=JobSources(
                directories=[], functions=[_build_wheel, _build_wheel_camel, _healthy]
            ),
        )

        assert sorted(d.name for d in app.get_jobs()) == ["build-wheel", "healthy"]

    def test_the_first_claimant_wins(self, tmp_path: Path) -> None:
        app = FunctualizeApp(
            "static",
            job_sources=JobSources(
                directories=[], functions=[_build_wheel, _build_wheel_camel]
            ),
        )

        (survivor,) = [d for d in app.get_jobs() if d.name == "build-wheel"]
        assert survivor.python_name == "build_wheel"

    def test_the_collision_is_reported(self, tmp_path: Path) -> None:
        app = FunctualizeApp(
            "static",
            job_sources=JobSources(
                directories=[], functions=[_build_wheel, _build_wheel_camel]
            ),
        )

        messages = [f.message for f in app._resolution_pipeline.collisions]

        assert len(messages) == 1
        assert "'build-wheel'" in messages[0]

    def test_a_clean_static_provider_reports_nothing(self, tmp_path: Path) -> None:
        app = FunctualizeApp(
            "static", job_sources=JobSources(directories=[], functions=[_healthy])
        )

        assert app._resolution_pipeline.collisions == []
        assert [d.name for d in app.get_jobs()] == ["healthy"]
