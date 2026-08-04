"""An MCP caller's group options reach the engine as a group layer (S6a T-GO-5).

The translator publishes a group's flags alongside the job's own parameters,
so an agent sees one flat argument list. They cannot be delivered the same
way: a group field is *not* a parameter of the job function, and passing one
through as a keyword argument fails argument validation. `_execute_job` is
where the flat list splits back into its two halves.

That split is the whole reason `MCPToolDef.group_option_names` exists — the
schema alone cannot tell the two kinds of argument apart at call time.
"""

from __future__ import annotations

from typing import Any

from functualize_mcp._server import _execute_job


class _RecordingApp:
    """Captures exactly how `execute` was called."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], dict[str, Any] | None]] = []

    def execute(
        self,
        job_name: str,
        *,
        group_option_values: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        self.calls.append((job_name, kwargs, group_option_values))
        return type(
            "Result",
            (),
            {"status": "SUCCESS", "return_value": "ok", "duration_ms": 1.0},
        )()


def test_group_fields_are_split_off_from_the_job_arguments() -> None:
    app = _RecordingApp()

    _execute_job(
        app,
        "deploy.web.run",
        {"image": "custom", "env": "prod", "dry_run": True},
        None,
        frozenset({"env", "dry_run"}),
    )

    _job_name, kwargs, group_values = app.calls[0]
    assert kwargs == {"image": "custom"}
    assert group_values == {"env": "prod", "dry_run": True}


def test_nothing_is_split_when_the_job_declares_no_group_options() -> None:
    """The overwhelmingly common case, and the one every existing caller
    exercises — it must reach `execute` byte for byte as before."""
    app = _RecordingApp()

    _execute_job(app, "plain", {"image": "custom"})

    _job_name, kwargs, group_values = app.calls[0]
    assert kwargs == {"image": "custom"}
    assert group_values is None


def test_an_unsupplied_group_field_passes_nothing_rather_than_none() -> None:
    """`None` means "no CLI layer", which lets the file/env/default layers
    resolve. An explicit empty dict would say the same thing, but sending
    `{}` for every ungrouped call would be noise on the hot path."""
    app = _RecordingApp()

    _execute_job(app, "deploy.web.run", {"image": "x"}, None, frozenset({"env"}))

    _job_name, kwargs, group_values = app.calls[0]
    assert kwargs == {"image": "x"}
    assert group_values is None


def test_a_group_field_never_reaches_the_job_kwargs() -> None:
    """The failure this prevents: `run()` has no `env` parameter, so passing
    it through raises rather than configuring anything."""
    app = _RecordingApp()

    _execute_job(app, "deploy.web.run", {"env": "prod"}, None, frozenset({"env"}))

    _job_name, kwargs, group_values = app.calls[0]
    assert kwargs == {}
    assert group_values == {"env": "prod"}
