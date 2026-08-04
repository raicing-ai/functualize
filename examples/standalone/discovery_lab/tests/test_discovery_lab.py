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
