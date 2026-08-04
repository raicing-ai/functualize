"""Inline-TUI orchestrator handoff for terminal-owning (tty: TTY) jobs.

A job whose cached descriptor has requires_tty cannot run on the TUI worker
thread; run_job must step aside (request_handoff) instead of executing it, and
_run_handoff must run it via the app facade after the shell exits.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("textual")

from functualize._cli.inline_tui import _run_handoff  # noqa: E402
from functualize._cli.tui.job_execution import run_job  # noqa: E402
from functualize._types.descriptors import FieldDescriptor, JobDescriptor  # noqa: E402


def _descriptor(name: str, *, requires_tty: bool) -> JobDescriptor:
    return JobDescriptor(name=name, group=None, requires_tty=requires_tty)


def _fake_tui(descriptor: JobDescriptor | None, job_name: str = "") -> MagicMock:
    app = MagicMock()
    app.workers = []  # _job_worker_running iterates this
    app._func_app.get_job.return_value = descriptor
    # run_job resolves the space-separated path first (S6b). A MagicMock would
    # hand back truthy `dotted_token`/`bad_flag` and trip the refusal branches,
    # so the walk result is stated explicitly: a plain job, nothing mid-path.
    app.resolve_command.return_value = SimpleNamespace(
        job_name=job_name or getattr(descriptor, "name", None),
        args=[],
        group_values={},
        dotted_token=None,
        bad_flag=None,
    )
    app.job_kwargs_for.return_value = {}
    return app


def test_run_job_hands_off_a_requires_tty_job() -> None:
    app = _fake_tui(_descriptor("editor", requires_tty=True))
    run_job(app, ["editor", "--path", "x"])

    app.request_handoff.assert_called_once_with(["editor", "--path", "x"])
    # It must NOT fall through to the worker-thread execution path.
    app.run_worker.assert_not_called()


def test_run_job_runs_a_normal_job_in_worker() -> None:
    app = _fake_tui(_descriptor("build", requires_tty=False))
    run_job(app, ["build"])

    app.request_handoff.assert_not_called()
    app.run_worker.assert_called_once()  # normal PANEL path preserved


def test_run_handoff_parses_tokens_and_executes() -> None:
    app = MagicMock()
    app.get_job.return_value = SimpleNamespace(
        config_fields=[
            FieldDescriptor(
                name="path",
                type_annotation="str",
                default=None,
                description="",
                required=True,
            )
        ]
    )

    _run_handoff(app, ["editor", "--path", "/tmp/f"])

    app.execute.assert_called_once()
    _args, kwargs = app.execute.call_args
    assert _args[0] == "editor"
    assert kwargs.get("path") == "/tmp/f"


def test_run_handoff_survives_job_error() -> None:
    app = MagicMock()
    app.get_job.return_value = SimpleNamespace(config_fields=[])
    app.execute.side_effect = RuntimeError("boom")
    # Must not propagate — a failed handoff still returns to the shell.
    _run_handoff(app, ["editor"])


def test_launch_loop_runs_handoff_then_relaunches() -> None:
    from unittest.mock import patch

    from functualize._cli import inline_tui

    app = MagicMock()
    tui1 = MagicMock()
    tui1.handoff_tokens = ["editor"]
    tui2 = MagicMock()
    tui2.handoff_tokens = None
    tui2.return_code = 0
    mock_class = MagicMock(side_effect=[tui1, tui2])

    with (
        patch.dict(
            "sys.modules",
            {"functualize._cli.tui.app": MagicMock(FunctualizeInlineTUI=mock_class)},
        ),
        patch.object(inline_tui, "_run_handoff") as mock_handoff,
    ):
        code = inline_tui.launch_inline_tui(app)

    assert code == 0
    mock_handoff.assert_called_once_with(app, ["editor"])
    app.refresh.assert_called_once()  # staleness hook after the handoff
    assert mock_class.call_count == 2  # shell relaunched after the handoff
