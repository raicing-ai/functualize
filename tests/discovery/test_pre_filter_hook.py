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


class TestTheEagerPathFiltersNothing:
    """Characterization of a pre-existing gap, not a property worth having.

    ``lazy=False`` never reaches the provider the boot path just built with
    these filters: ``resolve_and_register_jobs`` calls
    ``JobRegistry.scan_and_register_headless`` instead, and
    ``_scan_directory_headless`` enumerates with ``pkgutil.iter_modules`` and
    takes no filter argument at all. So the whole ``require_*`` family and
    ``exclude_patterns`` are silently ignored there — this is not specific to
    ``pre_filter``, and predates it.

    Pinned rather than fixed because a fix belongs to the eager path, not to
    this field. When someone does fix it, these two fail and point at the
    reason. See `.spec/STATUS.md`.
    """

    def _eager(self, jobs_dir: Path, config: DiscoveryConfig) -> set[str]:
        app = FunctualizeApp(
            "hook",
            job_sources=JobSources(directories=[str(jobs_dir)], lazy=False),
            discovery_config=config,
        )
        return {job.name for job in app.get_jobs()}

    def test_a_caller_filter_is_ignored(self, jobs_dir: Path) -> None:
        names = self._eager(
            jobs_dir, DiscoveryConfig(pre_filter=_RejectByName("skipme"))
        )
        assert "beta-job" in names, (
            "The eager path started honouring pre_filter. If that is the fix, "
            "delete this class -- and check the require_* test below with it."
        )

    def test_require_file_prefix_is_ignored_too(self, jobs_dir: Path) -> None:
        """The same gap, on a setting that has shipped for far longer — which
        is what makes it the eager path's defect rather than this field's."""
        names = self._eager(jobs_dir, DiscoveryConfig(require_file_prefix="job_"))
        assert "alpha-job" in names
