"""Tests for BF-3: DI capability types are filtered from CLI command signatures."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from functualize.app.adapters.click_params import create_job_command

if TYPE_CHECKING:
    from functualize._config.job_config import JobConfigView
    from functualize.job._invoke import Invoke
    from functualize.job._job_context import JobContext
    from functualize.job._log import Log
    from functualize.job._perf import Perf
    from functualize.job._state import State


class TestDICapabilityFiltering:
    """Verify that create_job_command strips DI types from CLI signatures."""

    def test_log_stripped_from_signature(self) -> None:
        def run(log: Log, name: str) -> None:
            pass

        app = MagicMock()
        app._execution_engine = MagicMock()
        wrapped = create_job_command("run", run, app=app)
        sig = inspect.signature(wrapped)
        param_names = list(sig.parameters.keys())
        assert "log" not in param_names
        assert "name" in param_names

    def test_multiple_di_types_stripped(self) -> None:
        def run(invoke: Invoke, perf: Perf, count: int = 5) -> None:
            pass

        app = MagicMock()
        app._execution_engine = MagicMock()
        wrapped = create_job_command("run", run, app=app)
        sig = inspect.signature(wrapped)
        param_names = list(sig.parameters.keys())
        assert "invoke" not in param_names
        assert "perf" not in param_names
        assert "count" in param_names

    def test_state_and_jobcontext_stripped(self) -> None:
        def run(state: State, ctx: JobContext, verbose: bool = False) -> None:
            pass

        app = MagicMock()
        app._execution_engine = MagicMock()
        wrapped = create_job_command("run", run, app=app)
        sig = inspect.signature(wrapped)
        param_names = list(sig.parameters.keys())
        assert "state" not in param_names
        assert "ctx" not in param_names
        assert "verbose" in param_names

    def test_job_config_view_stripped(self) -> None:
        def run(config_view: JobConfigView, output: str = "json") -> None:
            pass

        app = MagicMock()
        app._execution_engine = MagicMock()
        wrapped = create_job_command("run", run, app=app)
        sig = inspect.signature(wrapped)
        param_names = list(sig.parameters.keys())
        assert "config_view" not in param_names
        assert "output" in param_names

    def test_string_annotation_stripped(self) -> None:
        """Forward-reference string annotations for DI types are stripped."""

        def run(log, name: str = "default") -> None:  # noqa: ANN001
            pass

        # Manually set a string annotation to simulate forward reference
        run.__annotations__["log"] = "Log"

        app = MagicMock()
        app._execution_engine = MagicMock()
        wrapped = create_job_command("run", run, app=app)
        sig = inspect.signature(wrapped)
        param_names = list(sig.parameters.keys())
        assert "log" not in param_names
        assert "name" in param_names

    def test_all_di_stripped_leaves_only_cli_params(self) -> None:
        """A function with only DI params results in empty parameter list."""

        def run(log: Log, invoke: Invoke) -> None:
            pass

        app = MagicMock()
        app._execution_engine = MagicMock()
        wrapped = create_job_command("run", run, app=app)
        sig = inspect.signature(wrapped)
        assert len(sig.parameters) == 0

    def test_primitive_types_preserved(self) -> None:
        """str, int, float, bool, Path params are kept."""
        from pathlib import Path

        def run(name: str, count: int, rate: float, dry: bool, out: Path) -> None:
            pass

        app = MagicMock()
        app._execution_engine = MagicMock()
        wrapped = create_job_command("run", run, app=app)
        sig = inspect.signature(wrapped)
        param_names = list(sig.parameters.keys())
        assert param_names == ["name", "count", "rate", "dry", "out"]

    def test_unannotated_params_preserved(self) -> None:
        """Parameters without annotations pass through (for legacy compat)."""

        def run(name, count=5):  # noqa: ANN001
            pass

        app = MagicMock()
        app._execution_engine = MagicMock()
        wrapped = create_job_command("run", run, app=app)
        sig = inspect.signature(wrapped)
        param_names = list(sig.parameters.keys())
        assert "name" in param_names
        assert "count" in param_names
