"""Property-based tests for invoke hooks and timeout (Properties 20, 22).

Property 20: INVOKE_START/INVOKE_END fire in matched pairs at each nesting level
For any sequence of nested rc.invoke() calls up to depth D, the engine fires
exactly one INVOKE_START and one INVOKE_END for each level, with matching
child job name and depth in stack order.

Property 22: invoke timeout — values below 0.1 rejected with ValueError
For any timeout value < 0.1, rc.invoke() raises ValueError.

**Validates: Requirements 14.5, 17.4**
"""

from __future__ import annotations

import sys
import textwrap

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from functualize._app.state import AppState
from functualize._events.hooks import HookEvent
from functualize.app.config import ExecutionConfig, JobSources
from functualize.app.core import FunctualizeApp

# --- Helpers ---


def _write_jobs(tmp_path, source: str) -> str:
    """Helper to write job files and return the directory path."""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir(exist_ok=True)
    (jobs_dir / "test_jobs.py").write_text(textwrap.dedent(source))
    # Clear any cached module to avoid stale imports across hypothesis examples
    sys.modules.pop("test_jobs", None)
    return str(jobs_dir)


# --- Strategies ---

# Nesting depth from 1 to 5 (we generate chain of invoke calls)
nesting_depths = st.integers(min_value=1, max_value=5)

# Job name suffixes — alphanumeric identifiers for child jobs
job_name_suffixes = st.text(
    alphabet=st.characters(whitelist_categories=("Ll",)),
    min_size=2,
    max_size=8,
)

# Timeout values that are below 0.1 (the minimum)
invalid_timeouts = st.one_of(
    st.floats(
        min_value=-1e10,
        max_value=0.09999999,
        allow_nan=False,
        allow_infinity=False,
    ),
    st.just(0.0),
    st.just(-1.0),
    st.just(0.05),
    st.just(0.099),
)

# Valid timeout values (at or above 0.1)
valid_timeouts = st.floats(
    min_value=0.1,
    max_value=10.0,
    allow_nan=False,
    allow_infinity=False,
)


# --- Property 20 Tests ---


class TestInvokeHookMatchedPairs:
    """Property 20: INVOKE_START/INVOKE_END fire in matched pairs at each nesting level.

    For any sequence of nested rc.invoke() calls up to depth D, the engine fires
    exactly one INVOKE_START and one corresponding INVOKE_END for each invocation
    level, with matching child job name and depth, in stack order.

    **Validates: Requirements 14.5**
    """

    @pytest.fixture(autouse=True)
    def reset_state(self):
        """Reset AppState before each test."""
        AppState.reset()
        AppState.set("config_directory", ".")
        AppState.set("environment", "DEV")

    @settings(
        suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=30000
    )
    @given(depth=nesting_depths)
    def test_nested_invokes_produce_matched_pairs(self, depth: int, tmp_path):
        """For any nesting depth D, exactly D INVOKE_START and D INVOKE_END events
        fire with matching (child_name, depth) pairs in stack order.

        **Validates: Requirements 14.5**
        """
        # Generate a chain of jobs: job_0 -> job_1 -> ... -> job_{depth-1} -> leaf
        # job_0 invokes job_1, job_1 invokes job_2, etc.
        # leaf just returns a value.
        job_names = [f"job_{i}" for i in range(depth)] + ["leaf_job"]

        # Build source code for the chain
        lines = ["from functualize.job.context import RunContext\n"]
        for i in range(depth):
            child = job_names[i + 1]
            lines.append(f"def {job_names[i]}(rc: RunContext):")
            lines.append(f'    return rc.invoke("{child}")')
            lines.append("")
        lines.append("def leaf_job(rc: RunContext):")
        lines.append('    return "leaf_result"')
        lines.append("")

        source = "\n".join(lines)
        jobs_dir = _write_jobs(tmp_path, source)
        app = FunctualizeApp(
            name="testapp",
            job_sources=JobSources(directories=[jobs_dir]),
            execution=ExecutionConfig(max_invoke_depth=depth + 5),
        )

        events: list[tuple[str, str, int]] = []

        def on_start(rc, child_name, kwargs, d):
            events.append(("START", child_name, d))

        def on_end(rc, child_name, d, result):
            events.append(("END", child_name, d))

        app.hook_registry.register_global(HookEvent.INVOKE_START, on_start)
        app.hook_registry.register_global(HookEvent.INVOKE_END, on_end)

        import click.testing

        runner = click.testing.CliRunner()
        result = runner.invoke(app.cli_command, [job_names[0]])
        assert result.exit_code == 0, f"Job failed: {result.output}"

        # There should be exactly `depth` START events and `depth` END events
        starts = [(name, d) for event_type, name, d in events if event_type == "START"]
        ends = [(name, d) for event_type, name, d in events if event_type == "END"]

        assert len(starts) == depth
        assert len(ends) == depth

        # Each START should have a matching END with the same (child_name, depth)
        assert set(starts) == set(ends)

        # Stack order: STARTs come in order of increasing depth,
        # ENDs come in order of decreasing depth
        for i in range(depth):
            expected_child = job_names[i + 1]
            expected_depth = i + 1
            assert starts[i] == (expected_child, expected_depth)
            # ENDs are in reverse order
            assert ends[depth - 1 - i] == (expected_child, expected_depth)

        # Verify interleaving: events should be START(1), START(2), ...,
        # START(D), END(D), ..., END(2), END(1)
        expected_events = []
        for i in range(depth):
            expected_events.append(("START", job_names[i + 1], i + 1))
        for i in range(depth - 1, -1, -1):
            expected_events.append(("END", job_names[i + 1], i + 1))

        assert events == expected_events

    @settings(
        suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=30000
    )
    @given(
        num_siblings=st.integers(min_value=2, max_value=4),
    )
    def test_sibling_invokes_produce_independent_pairs(
        self, num_siblings: int, tmp_path
    ):
        """For a parent invoking N siblings sequentially, each sibling
        gets its own matched INVOKE_START/INVOKE_END pair at the same depth.

        **Validates: Requirements 14.5**
        """
        # parent_job invokes child_0, child_1, ..., child_{N-1} sequentially
        child_names = [f"child_{i}" for i in range(num_siblings)]

        lines = ["from functualize.job.context import RunContext\n"]
        lines.append("def parent_job(rc: RunContext):")
        for name in child_names:
            lines.append(f'    rc.invoke("{name}")')
        lines.append('    return "done"')
        lines.append("")

        for name in child_names:
            lines.append(f"def {name}(rc: RunContext):")
            lines.append(f'    return "{name}_result"')
            lines.append("")

        source = "\n".join(lines)
        jobs_dir = _write_jobs(tmp_path, source)
        app = FunctualizeApp(
            name="testapp",
            job_sources=JobSources(directories=[jobs_dir]),
            execution=ExecutionConfig(max_invoke_depth=10),
        )

        events: list[tuple[str, str, int]] = []

        def on_start(rc, child_name, kwargs, d):
            events.append(("START", child_name, d))

        def on_end(rc, child_name, d, result):
            events.append(("END", child_name, d))

        app.hook_registry.register_global(HookEvent.INVOKE_START, on_start)
        app.hook_registry.register_global(HookEvent.INVOKE_END, on_end)

        import click.testing

        runner = click.testing.CliRunner()
        result = runner.invoke(app.cli_command, ["parent_job"])
        assert result.exit_code == 0, f"Job failed: {result.output}"

        # Each sibling should have exactly one START and one END at depth 1
        assert len(events) == num_siblings * 2

        # Events should alternate: START child_0, END child_0, START child_1, ...
        for i in range(num_siblings):
            start_event = events[i * 2]
            end_event = events[i * 2 + 1]
            assert start_event == ("START", child_names[i], 1)
            assert end_event == ("END", child_names[i], 1)


# --- Property 22 Tests ---


class TestInvokeTimeoutValidation:
    """Property 22: invoke timeout — values below 0.1 rejected with ValueError.

    For any timeout value < 0.1, rc.invoke() raises ValueError.

    **Validates: Requirements 17.4**
    """

    @pytest.fixture(autouse=True)
    def reset_state(self):
        """Reset AppState before each test."""
        AppState.reset()
        AppState.set("config_directory", ".")
        AppState.set("environment", "DEV")

    @settings(
        suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=30000
    )
    @given(timeout_val=invalid_timeouts)
    def test_timeout_below_minimum_raises_value_error(
        self, timeout_val: float, tmp_path
    ):
        """For any timeout < 0.1, rc.invoke() raises ValueError.

        **Validates: Requirements 17.4**
        """
        source = """\
            from functualize.job.context import RunContext

            def parent_job(rc: RunContext):
                rc.invoke("child_job", timeout={timeout})

            def child_job(rc: RunContext):
                return "done"
        """.replace("{timeout}", repr(timeout_val))

        jobs_dir = _write_jobs(tmp_path, source)
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[jobs_dir])
        )

        import click.testing

        runner = click.testing.CliRunner()
        result = runner.invoke(app.cli_command, ["parent_job"])

        # The ValueError should cause the job to fail
        assert result.exit_code != 0 or result.exception is not None

    @settings(
        suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=30000
    )
    @given(timeout_val=valid_timeouts)
    def test_timeout_at_or_above_minimum_accepted(self, timeout_val: float, tmp_path):
        """For any timeout >= 0.1, rc.invoke() does not raise ValueError.

        **Validates: Requirements 17.4**
        """
        source = """\
            from functualize.job.context import RunContext

            def parent_job(rc: RunContext):
                result = rc.invoke("child_job", timeout={timeout})
                return result.return_value

            def child_job(rc: RunContext):
                return "quick_result"
        """.replace("{timeout}", repr(timeout_val))

        jobs_dir = _write_jobs(tmp_path, source)
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[jobs_dir])
        )

        import click.testing

        runner = click.testing.CliRunner()
        result = runner.invoke(app.cli_command, ["parent_job"])

        # Should complete without error (no ValueError for valid timeouts)
        assert result.exit_code == 0, (
            f"Unexpected failure with timeout={timeout_val}: {result.output}"
        )

    @settings(
        suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=30000
    )
    @given(
        timeout_val=st.floats(
            min_value=-1000.0,
            max_value=0.09999,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    def test_timeout_validation_is_strict_boundary(self, timeout_val: float, tmp_path):
        """The boundary at 0.1 is strict: any value strictly less than 0.1
        is rejected. This tests the boundary more thoroughly.

        **Validates: Requirements 17.4**
        """
        # Direct unit test against the RunContext invoke method validation
        # without going through the full app lifecycle — tests the core logic
        import logging
        from unittest.mock import MagicMock

        from functualize._config.job_config import JobConfigView
        from functualize.job.context import RunContext

        mock_config = MagicMock(spec=JobConfigView)
        mock_logger = MagicMock(spec=logging.Logger)
        mock_engine = MagicMock()

        rc = RunContext(
            name="test-job",
            config=mock_config,
            logger=mock_logger,
            _execution_engine=mock_engine,
            _max_invoke_depth=10,
        )

        with pytest.raises(ValueError, match="at least 0.1"):
            rc.invoke("some_job", timeout=timeout_val)
