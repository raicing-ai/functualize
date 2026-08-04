"""Tests for S1/T6: require_job_decorators='job' with the real @job, and the
§A.6 plugin extension-metadata orphan check (warn by default, error under
plugins.strict).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from functualize._app.boot import (
    _resolve_plugins_strict,
    validate_plugin_ext_metadata,
)
from functualize._discovery.cached_provider import CachedDirectoryScanProvider
from functualize._discovery.providers import extract_ext_metadata
from functualize._primitives.locator import ResourceLocator
from functualize._types.errors import OrphanedPluginMetadataError

# ---------------------------------------------------------------------------
# require_job_decorators="job" with the real @job decorator
# ---------------------------------------------------------------------------

_MIXED_MODULE = '''
from functualize.job import job

@job
def real_job():
    """A @job-decorated function."""
    pass

@job(group="infra")
def called_job():
    """A @job(...)-decorated function."""
    pass

def plain_helper():
    """Not a job — no @job decorator."""
    pass
'''


def _provider(tmp_path: Path, jobs_dir: Path, job_filter=None):
    locator = (
        ResourceLocator()
        .search_explicit(tmp_path / "cache")
        .write_to_explicit(tmp_path / "cache")
    )
    return CachedDirectoryScanProvider(
        directories=[str(jobs_dir)],
        locator=locator,
        project_root=tmp_path,
        job_filter=job_filter,
    )


def test_require_job_decorators_job_filters_to_decorated(tmp_path: Path) -> None:
    from functualize.app.config import DiscoveryConfig
    from functualize.app.utils import build_job_filter

    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    (jobs_dir / "mixed.py").write_text(_MIXED_MODULE)

    job_filter = build_job_filter(DiscoveryConfig(require_job_decorators=("job",)))
    names = {j.func_name for j in _provider(tmp_path, jobs_dir, job_filter).list_jobs()}

    # Both @job forms are AST-visible as "job"; the plain helper is excluded.
    assert names == {"real-job", "called-job"}


def test_job_decorator_is_ast_visible(tmp_path: Path) -> None:
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    (jobs_dir / "mixed.py").write_text(_MIXED_MODULE)

    by_name = {j.func_name: j for j in _provider(tmp_path, jobs_dir).list_jobs()}
    assert "job" in by_name["real-job"].decorators
    assert "job" in by_name["called-job"].decorators


# ---------------------------------------------------------------------------
# extract_ext_metadata
# ---------------------------------------------------------------------------


def test_extract_ext_metadata_collects_namespaced_dunders() -> None:
    def fn() -> None: ...

    fn.__functualize_ext_rate_limit__ = "10/min"  # type: ignore[attr-defined]
    fn.__functualize_ext_audit__ = {"level": "high"}  # type: ignore[attr-defined]

    assert extract_ext_metadata(fn) == {
        "plugins": {"rate_limit": "10/min", "audit": {"level": "high"}}
    }


def test_extract_ext_metadata_empty_for_plain_function() -> None:
    def fn() -> None: ...

    assert extract_ext_metadata(fn) == {}


# ---------------------------------------------------------------------------
# §A.6 orphan-metadata boot validation
# ---------------------------------------------------------------------------


def _app_with(descriptors, plugins, *, strict=False):
    """Build a minimal app-like object for validate_plugin_ext_metadata."""
    resolution = SimpleNamespace(
        resolve=lambda key, section: SimpleNamespace(value=strict)
    )
    return SimpleNamespace(
        plugin_loader=SimpleNamespace(loaded_instances=plugins),
        job_registry=SimpleNamespace(_job_descriptors=descriptors),
        _resolution_chain=resolution,
    )


def _desc(name: str, plugins_meta: dict | None):
    return SimpleNamespace(
        name=name,
        metadata=({"plugins": plugins_meta} if plugins_meta is not None else {}),
    )


def test_no_orphan_when_plugin_name_matches() -> None:
    app = _app_with(
        descriptors=[_desc("deploy", {"rate_limit": "10/min"})],
        plugins=[SimpleNamespace(name="rate_limit")],
    )
    validate_plugin_ext_metadata(app)  # no raise, no warning


def test_no_orphan_when_declared_namespace_matches() -> None:
    app = _app_with(
        descriptors=[_desc("deploy", {"rl": "10/min"})],
        plugins=[
            SimpleNamespace(name="ratelimiter", functualize_ext_namespaces=("rl",))
        ],
    )
    validate_plugin_ext_metadata(app)


def test_orphan_warns_by_default(caplog) -> None:
    app = _app_with(
        descriptors=[_desc("deploy", {"rate_limit": "10/min"})],
        plugins=[],
    )
    import logging

    with caplog.at_level(logging.WARNING):
        validate_plugin_ext_metadata(app)
    assert any("rate_limit" in r.message for r in caplog.records)


def test_orphan_errors_under_strict() -> None:
    app = _app_with(
        descriptors=[_desc("deploy", {"rate_limit": "10/min"})],
        plugins=[],
        strict=True,
    )
    with pytest.raises(OrphanedPluginMetadataError) as exc:
        validate_plugin_ext_metadata(app)
    assert ("deploy", "rate_limit") in exc.value.orphans


def test_no_metadata_no_check() -> None:
    app = _app_with(descriptors=[_desc("deploy", None)], plugins=[], strict=True)
    validate_plugin_ext_metadata(app)  # nothing to validate → no raise


def test_resolve_plugins_strict_defaults_false_on_missing() -> None:
    def _raise(key, section):
        raise KeyError(key)

    app = SimpleNamespace(_resolution_chain=SimpleNamespace(resolve=_raise))
    assert _resolve_plugins_strict(app) is False


@pytest.mark.parametrize(
    "value,expected",
    [
        (True, True),
        ("true", True),
        ("1", True),
        ("on", True),
        (False, False),
        ("false", False),
        ("no", False),
    ],
)
def test_resolve_plugins_strict_coerces(value, expected) -> None:
    app = SimpleNamespace(
        _resolution_chain=SimpleNamespace(
            resolve=lambda k, s: SimpleNamespace(value=value)
        )
    )
    assert _resolve_plugins_strict(app) is expected
