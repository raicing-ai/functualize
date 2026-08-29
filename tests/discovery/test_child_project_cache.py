"""A child project must not write into its parent's discovery cache.

`build_cached_provider(project_root=child_path)` reads as though the child gets
its own cache. It did not: `find_functualize_dir` searches *upward*, so a child
under a parent that has `.functualize/` resolved to the **parent's**
`cache.json`. Both providers then wrote the same file and whichever booted last
erased the other's entries, so the parent's cache never survived a boot.

The fingerprint work turned that from silent into loud. The child provider
carried no `discovery_hash`, so it wrote `null`, and the parent read that as a
mismatch and invalidated on *every* boot -- forever, with a warning on stderr, in
any project using `children=`. See ADR-011.

These boot the app repeatedly rather than calling the provider directly, because
the defect is only visible across boots: a single cold boot looks correct in
every version. That is `wiring-discipline.md` §5 -- exercise the cached path, not
just the live one.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from functualize._app.impl import build_cached_provider
from functualize.app import FunctualizeApp
from functualize.app.config import DiscoveryConfig, JobSources

_PARENT_JOB = '"""Parent job."""\n\n\ndef alpha() -> str:\n    return "a"\n'
_PARENT_EXCLUDED = '"""Parent, excluded."""\n\n\ndef pbeta() -> str:\n    return "b"\n'
_CHILD_JOB = '"""Child job."""\n\n\ndef childjob() -> str:\n    return "c"\n'


def _make_tree(tmp_path: Path) -> Path:
    root = tmp_path / "parent"
    (root / ".functualize").mkdir(parents=True)
    (root / "jobs").mkdir()
    (root / "jobs" / "alpha.py").write_text(_PARENT_JOB, encoding="utf-8")
    (root / "jobs" / "test_beta.py").write_text(_PARENT_EXCLUDED, encoding="utf-8")
    child_jobs = root / "services" / "child" / "jobs"
    child_jobs.mkdir(parents=True)
    (child_jobs / "childjob.py").write_text(_CHILD_JOB, encoding="utf-8")
    return root


def _boot(root: Path, monkeypatch) -> FunctualizeApp:
    """Boot and resolve jobs — the cache is written on first resolution.

    `chdir` because the parent's provider resolves its cache location from the
    CWD, which is where the `.functualize/` the child used to walk up into lives.
    """
    monkeypatch.chdir(root)
    app = FunctualizeApp(
        "parent",
        job_sources=JobSources(
            directories=[str(root / "jobs")],
            children={"svc": str(root / "services" / "child")},
        ),
        discovery_config=DiscoveryConfig(exclude_patterns=("test_*.py",)),
    )
    app.get_jobs()
    return app


def _parent_cache(root: Path) -> dict:
    return json.loads((root / ".functualize" / "cache.json").read_text("utf-8"))


class TestChildDoesNotClobberTheParentCache:
    def test_the_parent_keeps_its_entries_across_repeated_boots(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The parent's own job survived boot 1 and vanished on every boot after."""
        root = _make_tree(tmp_path)

        for boot in range(3):
            _boot(root, monkeypatch)
            entries = _parent_cache(root)["entries"]
            assert any("alpha.py" in key for key in entries), (
                f"boot {boot + 1}: the child overwrote the parent's cache entries"
            )

    def test_the_parent_cache_keeps_a_real_fingerprint(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The child wrote `null` here, which is what forced the reboot loop."""
        root = _make_tree(tmp_path)

        _boot(root, monkeypatch)
        _boot(root, monkeypatch)

        assert isinstance(_parent_cache(root).get("discovery_hash"), str)

    def test_the_parent_filter_still_applies(self, tmp_path: Path, monkeypatch) -> None:
        """Guard the fix from the other side: the parent is still filtered."""
        root = _make_tree(tmp_path)

        app = _boot(root, monkeypatch)

        names = {job.name for job in app.get_jobs()}
        assert "alpha" in names
        assert "pbeta" not in names
        assert {"svc.childjob"} <= names


class TestRepeatedBootsDoNotInvalidate:
    """The symptom, asserted directly: no boot after the first should rescan.

    This covers both halves of the fix at once. `ancestor_search=False` stops the
    child writing into the parent's file; the all-defaults `discovery_hash` stops
    it writing `null` into its **own**. Drop either and some provider reads a
    fingerprint it disagrees with and logs this line on every boot.
    """

    def test_no_invalidation_warning_on_later_boots(
        self, tmp_path: Path, monkeypatch, caplog
    ) -> None:
        root = _make_tree(tmp_path)
        _boot(root, monkeypatch)

        with caplog.at_level(
            logging.WARNING, logger="functualize._discovery.cached_provider"
        ):
            _boot(root, monkeypatch)
            _boot(root, monkeypatch)

        invalidations = [
            record.getMessage()
            for record in caplog.records
            if "Cache invalidated" in record.getMessage()
        ]
        assert invalidations == [], (
            f"a warm boot rescanned instead of reusing its cache: {invalidations}"
        )

    def test_the_child_writes_a_real_fingerprint_to_its_own_cache(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """A writer must never persist the "unknown" sentinel (ADR-011).

        This one asserts the artefact rather than a symptom, deliberately. `None`
        *skips* the check, so a child that wrote `discovery_hash: null` into its
        own cache would still reuse it and log nothing — there is no behaviour to
        observe today. It is still wrong: the moment a child gains a discovery
        config of its own, that persisted `null` is the same defect one level
        down, and it is the exact shape that made `cache rebuild` discard its own
        work. Pin the invariant while it is cheap.
        """
        root = _make_tree(tmp_path)
        _boot(root, monkeypatch)

        child = root / "services" / "child"
        stats = build_cached_provider(
            [str(child / "jobs")], project_root=child, ancestor_search=False
        ).stats()

        data = json.loads(Path(stats.cache_path).read_text(encoding="utf-8"))
        assert isinstance(data.get("discovery_hash"), str), (
            "the child provider persisted the 'unknown' fingerprint sentinel"
        )
