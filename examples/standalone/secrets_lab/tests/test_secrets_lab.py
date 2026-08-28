"""Unit tests for the secrets lab job bodies.

The cross-surface behaviour itself lives in
``tests/config/test_secret_surface_parity.py``; these only pin that the example
jobs are importable and that a ``Secret`` really does refuse to render, which is
the claim the README makes in step 5.
"""

import importlib.util
import sys
from pathlib import Path

from functualize.types import Secret

_ROOT = Path(__file__).parent.parent


def _load(name: str, relpath: str):
    spec = importlib.util.spec_from_file_location(name, _ROOT / relpath)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_sync = _load("secrets_lab_sync", "jobs/sync.py")
_report = _load("secrets_lab_report", "jobs/report.py")


def test_sync_config_defaults():
    cfg = _sync.SyncConfig()
    assert cfg.api_url == "https://api.example.com"
    assert cfg.sort_key == "created_at"
    assert cfg.credential.get_secret_value() == ""


def test_a_secret_refuses_to_render():
    """The claim README step 5 makes about leaving the log line in."""
    cfg = _sync.SyncConfig(credential="hunter2-real")

    assert "hunter2-real" not in str(cfg.credential)
    assert "hunter2-real" not in repr(cfg.credential)
    assert "hunter2-real" not in str(cfg.model_dump())
    assert cfg.credential.get_secret_value() == "hunter2-real"


def test_a_plain_string_accepted_for_a_secret_field():
    """Ordinary resolution hands strings in; the field must take them."""
    cfg = _sync.SyncConfig(credential="abc")
    assert isinstance(cfg.credential, Secret)


def test_report_token_is_required():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _report.ReportConfig()
