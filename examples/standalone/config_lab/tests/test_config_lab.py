"""Unit tests for the config lab job bodies.

The precedence behavior itself is a CLI concern — verified manually via the
README steps and by the CLI integration tests in tests/.
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


_deploy = _load("cfg_job_deploy", "jobs/job_deploy.py")
_build = _load("cfg_task_build", "jobs/task_build.py")


def test_deploy():
    assert _deploy.deploy() == "Deployed to staging"
    assert _deploy.deploy(target="production") == "Deployed to production"


def test_build():
    assert _build.build() == "Built (debug)"
    assert _build.build(release=True) == "Built (release)"
