"""Unit tests for InvocationPreset and get_recent_invocations."""

from __future__ import annotations

from functualize._cli.data.argument_history import ArgumentHistory
from functualize._cli.data.invocation_preset import get_recent_invocations

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_empty_history_returns_empty():
    """ArgumentHistory with empty _store → empty results."""
    history = ArgumentHistory(_store={}, _max_entries=50, _path=None, _dirty=False)
    result = get_recent_invocations(history, job_names=["deploy", "build"], limit=5)
    assert result == []


def test_single_job_with_history():
    """Record values for 'deploy' with fields 'env' and 'region' → one preset with correct kwargs."""
    history = ArgumentHistory(_store={}, _max_entries=50, _path=None, _dirty=False)
    history.record("deploy", "env", "staging")
    history.record("deploy", "region", "us-east-1")

    result = get_recent_invocations(history, job_names=["deploy"], limit=5)

    assert len(result) == 1
    preset = result[0]
    assert preset.job_name == "deploy"
    assert preset.kwargs == {"env": "staging", "region": "us-east-1"}


def test_limit_caps_results():
    """5 jobs with history, limit=2 → only 2 results."""
    history = ArgumentHistory(_store={}, _max_entries=50, _path=None, _dirty=False)
    for i in range(5):
        job_name = f"job_{i}"
        history.record(job_name, "arg", f"value_{i}")

    job_names = [f"job_{i}" for i in range(5)]
    result = get_recent_invocations(history, job_names=job_names, limit=2)

    assert len(result) == 2


def test_jobs_not_in_job_names_excluded():
    """History has 'deploy' and 'build', job_names=['deploy'] → only 'deploy' in results."""
    history = ArgumentHistory(_store={}, _max_entries=50, _path=None, _dirty=False)
    history.record("deploy", "env", "staging")
    history.record("build", "target", "release")

    result = get_recent_invocations(history, job_names=["deploy"], limit=5)

    assert len(result) == 1
    assert result[0].job_name == "deploy"


def test_display_text_format():
    """display_text should be 'job_name --field-name value' with underscores as hyphens."""
    history = ArgumentHistory(_store={}, _max_entries=50, _path=None, _dirty=False)
    history.record("deploy", "target_env", "production")

    result = get_recent_invocations(history, job_names=["deploy"], limit=5)

    assert len(result) == 1
    preset = result[0]
    # Underscores in field names become hyphens in display
    assert preset.display_text == "deploy --target-env production"


def test_kwargs_use_most_recent_value():
    """Record multiple values for same field → kwargs uses the most recent."""
    history = ArgumentHistory(_store={}, _max_entries=50, _path=None, _dirty=False)
    history.record("deploy", "env", "dev")
    history.record("deploy", "env", "staging")
    history.record("deploy", "env", "production")

    result = get_recent_invocations(history, job_names=["deploy"], limit=5)

    assert len(result) == 1
    preset = result[0]
    assert preset.kwargs["env"] == "production"
