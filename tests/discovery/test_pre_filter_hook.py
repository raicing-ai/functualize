"""``DiscoveryConfig.pre_filter`` — a host's own pre-import predicate.

The nine ``require_*`` settings describe modules by filename, import, marker or
decorator. A host whose jobs are, say, methods on a class can express itself in
none of them, and until now had no way to say so without forking discovery.

Two properties are the whole point of this file, and both are easy to get
wrong in a way every other test stays green through:

- **It composes.** The caller's filter is ANDed onto the stack the settings
  build. Substituting it instead would silently drop a ``require_file_prefix``
  the same config also sets.
- **It joins the cache fingerprint.** The discovery cache persists *negative*
  pre-filter decisions and replays them while the fingerprint matches, so a
  filter outside the digest gets its rejections replayed after its logic
  changes. That is the X1-X4 class ADR-010/ADR-011 exist to close, and
  ``fingerprint()`` is what keeps this field out of it.

**Everything here exercises the lazy boot path**, which is
``JobSources.lazy``'s default and the only path where discovery filtering
happens at all. That is not a convenience: ``lazy=False`` ignores the whole
``require_*`` family, and ``TestTheEagerPathFiltersNothing`` at the bottom
pins that pre-existing gap rather than leaving this file looking like it
covers both.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize.app import FunctualizeApp, JobSources
from functualize.app.config import DiscoveryConfig


class _RejectByName:
    """Reject any module whose filename contains ``needle``.

    Deliberately something no ``require_*`` setting can express: a substring
    match anywhere in the stem, neither prefix nor postfix.
    """

    def __init__(self, needle: str, stamp: str = "v1") -> None:
        self._needle = needle
        self._stamp = stamp

    def should_import(self, source_file: Path) -> bool:
        return self._needle not in source_file.stem

    def fingerprint(self) -> str:
        return f"reject-by-name:{self._needle}:{self._stamp}"


def _write(root: Path, name: str, job: str) -> None:
    (root / name).write_text(
        f"def {job}(value: str = 'x') -> str:\n    return value\n",
        encoding="utf-8",
    )


@pytest.fixture
def jobs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Two modules, and a CWD the discovery cache can live under."""
    root = tmp_path / "jobs"
    root.mkdir()
    _write(root, "alpha.py", "alpha_job")
    _write(root, "beta_skipme.py", "beta_job")
    monkeypatch.chdir(tmp_path)
    return root


def _boot(jobs_dir: Path, config: DiscoveryConfig) -> set[str]:
    app = FunctualizeApp(
        "hook",
        job_sources=JobSources(directories=[str(jobs_dir)]),
        discovery_config=config,
    )
    return {job.name for job in app.get_jobs()}


class TestTheCallerSuppliedFilterIsConsulted:
    def test_a_rejected_module_contributes_no_jobs(self, jobs_dir: Path) -> None:
        names = _boot(jobs_dir, DiscoveryConfig(pre_filter=_RejectByName("skipme")))
        assert "alpha-job" in names
        assert "beta-job" not in names

    def test_without_the_filter_both_modules_are_read(self, jobs_dir: Path) -> None:
        """The control. Without it the test above could pass because the second
        module was never discoverable in the first place."""
        names = _boot(jobs_dir, DiscoveryConfig())
        assert {"alpha-job", "beta-job"} <= names


class TestCompositionIsAnd:
    """A caller's filter *adds* a constraint; it never replaces one."""

    def test_a_require_setting_alongside_it_still_applies(self, jobs_dir: Path) -> None:
        _write(jobs_dir, "job_gamma.py", "gamma_job")
        names = _boot(
            jobs_dir,
            DiscoveryConfig(
                require_file_prefix="job_",
                pre_filter=_RejectByName("skipme"),
            ),
        )
        # Only `job_gamma.py` satisfies both. `alpha.py` fails the prefix and
        # `beta_skipme.py` fails both — substituting rather than composing
        # would let `alpha.py` back in.
        assert names == {"gamma-job"}

    def test_the_caller_filter_can_reject_what_the_prefix_admits(
        self, jobs_dir: Path
    ) -> None:
        """The other direction of the AND."""
        _write(jobs_dir, "job_skipme.py", "delta_job")
        _write(jobs_dir, "job_gamma.py", "gamma_job")
        names = _boot(
            jobs_dir,
            DiscoveryConfig(
                require_file_prefix="job_",
                pre_filter=_RejectByName("skipme"),
            ),
        )
        assert names == {"gamma-job"}


class TestTheFilterIsCacheAware:
    """Reachability of ``fingerprint()`` through a real cold/warm cycle."""

    def test_a_changed_filter_rescans_rather_than_replaying(
        self, jobs_dir: Path
    ) -> None:
        """X4, for this field.

        The first boot rejects `beta_skipme.py` and persists that decision. The
        second boot runs a filter that rejects nothing — if the digest ignored
        the filter, the stored rejection would be replayed and `beta-job` would
        stay missing.
        """
        cold = _boot(jobs_dir, DiscoveryConfig(pre_filter=_RejectByName("skipme")))
        assert "beta-job" not in cold

        warm = _boot(
            jobs_dir, DiscoveryConfig(pre_filter=_RejectByName("nothing-matches"))
        )
        assert "beta-job" in warm

    def test_the_same_filter_twice_is_stable(self, jobs_dir: Path) -> None:
        """The warm half: identical logic, identical results.

        Identity-hashing would satisfy this too, so it is the weaker of the two
        assertions and exists to bound the one above — a fingerprint that
        changed every boot would pass here while rescanning every run.
        """
        first = _boot(jobs_dir, DiscoveryConfig(pre_filter=_RejectByName("skipme")))
        second = _boot(jobs_dir, DiscoveryConfig(pre_filter=_RejectByName("skipme")))
        assert first == second


class TestTheEagerPathFiltersToo:
    """Inverted, not deleted — this class used to pin the opposite.

    It read `TestTheEagerPathFiltersNothing`, and characterized a real gap:
    ``lazy=False`` never reached the provider boot had just built with these
    filters. ``resolve_and_register_jobs`` called
    ``JobRegistry.scan_and_register_headless`` instead, which enumerates with
    ``pkgutil.iter_modules`` and takes no filter argument at all — so the whole
    ``require_*`` family and ``exclude_patterns`` were silently ignored there.
    It was pinned rather than fixed because the fix belonged to the eager path
    rather than to the ``pre_filter`` field, and its own docstring said "when
    someone does fix it, these two fail and point at the reason."

    They did. `eager-boot-provider` routes the eager branch through the
    provider, so the filters apply on both paths. The class is kept in its
    inverted form so the gap stays on the record: the assertions below are the
    exact ones that used to read `in`.
    """

    def _eager(self, jobs_dir: Path, config: DiscoveryConfig) -> set[str]:
        app = FunctualizeApp(
            "hook",
            job_sources=JobSources(directories=[str(jobs_dir)], lazy=False),
            discovery_config=config,
        )
        return {job.name for job in app.get_jobs()}

    def test_a_caller_filter_is_honoured(self, jobs_dir: Path) -> None:
        names = self._eager(
            jobs_dir, DiscoveryConfig(pre_filter=_RejectByName("skipme"))
        )
        assert "beta-job" not in names

    def test_require_file_prefix_is_honoured_too(self, jobs_dir: Path) -> None:
        """The same setting, which had shipped far longer than `pre_filter` —
        which is what made this the eager path's defect rather than the
        field's."""
        names = self._eager(jobs_dir, DiscoveryConfig(require_file_prefix="job_"))
        assert "alpha-job" not in names

    def test_both_paths_now_agree(self, jobs_dir: Path) -> None:
        """The property that replaces the characterization: `lazy` chooses
        when modules are imported, never which jobs exist."""
        config = DiscoveryConfig(require_file_prefix="job_")
        eager = self._eager(jobs_dir, config)
        lazy_app = FunctualizeApp(
            "hook",
            job_sources=JobSources(directories=[str(jobs_dir)], lazy=True),
            discovery_config=config,
        )
        assert eager == {job.name for job in lazy_app.get_jobs()}
