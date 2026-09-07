"""Unit tests for the discovery lab job bodies.

Discovery *behavior* (which jobs each filter selects) is a CLI concern —
verified manually via the README table and by the CLI integration tests in
tests/. These tests prove the job functions themselves work.
"""

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent


def _load(name: str, relpath: str):
    """Load a module from a file path under the lab directory."""
    spec = importlib.util.spec_from_file_location(name, _ROOT / relpath)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_deploy = _load("lab_job_deploy", "jobs/job_deploy.py")
_build = _load("lab_job_build", "jobs/job_build.py")
_cleanup = _load("lab_cleanup_task", "jobs/cleanup_task.py")
_marked = _load("lab_marked", "jobs/marked.py")
_helpers = _load("lab_helpers", "jobs/helpers.py")
_snippets = _load("lab_snippets", "global/snippets.py")


def test_deploy_and_rollback():
    assert _deploy.deploy() == "Deployed to staging"
    assert _deploy.deploy(target="production") == "Deployed to production"
    assert _deploy.rollback() == "Rolled back to previous"


def test_build():
    assert _build.build() == "Build complete (debug)"
    assert _build.build(optimize=True) == "Build complete (optimized)"


def test_cleanup():
    assert _cleanup.cleanup() == "Cleaned artifacts older than 30 days"


def test_audit_and_marker():
    assert _marked.audit(strict=True) == "Audit passed (strict)"
    assert _marked.__functualize__ is True


def test_helper():
    assert _helpers.helper_info() == "helpers: none configured"


def test_snippets():
    assert _snippets.snippet_hello("Lab") == "Hello, Lab!"
    assert len(_snippets.snippet_date()) == 10  # YYYY-MM-DD


# ---------------------------------------------------------------------------
# The tenth filter: `pre_filter`, which has no env var or CLI flag
# ---------------------------------------------------------------------------
#
# Unlike the nine `require_*` settings, this one takes a predicate, so it can
# only be set programmatically. That makes it the one filter the README table
# cannot demonstrate, and the one worth asserting here rather than by hand.

_demo = _load("lab_pre_filter_demo", "pre_filter_demo.py")


def test_the_predicate_selects_by_a_rule_no_setting_can_express():
    """A word ending in 'y' anywhere in the stem — neither prefix nor postfix."""
    check = _demo.NameContainsWordEndingInY().should_import
    assert check(Path("jobs/job_deploy.py")) is True
    assert check(Path("jobs/cleanup_task.py")) is False
    assert check(Path("jobs/helpers.py")) is False


def test_the_fingerprint_is_stable_across_instances():
    """Two filters with the same logic must produce the same stamp.

    The discovery cache replays this filter's negative decisions while the
    stamp matches, so a stamp that varied per instance would rescan every boot.
    """
    a = _demo.NameContainsWordEndingInY()
    b = _demo.NameContainsWordEndingInY()
    assert a.fingerprint() == b.fingerprint()
    assert str(a) != str(b), "distinct objects — so identity is not the stamp"


def test_the_demo_narrows_the_job_list():
    """End to end: the filter drops four files and keeps one."""
    baseline = _demo.jobs_with(None)
    filtered = _demo.jobs_with(_demo.NameContainsWordEndingInY())
    assert set(filtered) == {"deploy", "rollback"}
    assert set(baseline) - set(filtered) == {"audit", "build", "cleanup", "helper-info"}
