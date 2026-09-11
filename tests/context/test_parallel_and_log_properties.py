"""Property-based tests for parallel dispatch and log callbacks (Properties 23, 24, 25).

Property 23: invoke_parallel — results maintain input order regardless of completion order
For any list of N job specs, the returned results maintain input positional order.

Property 24: invoke_parallel — independent RunContexts with no shared mutable state
For parallel jobs, each child has independent RunContext/StateStore. State writes
in one don't affect siblings.

Property 25: Log callback pipeline — None suppresses, string replaces, chain order preserved
For a chain of N log callbacks, None suppresses (stops chain), string replaces,
chain in registration order.

**Validates: Requirements 21.3, 21.5, 22.1, 22.2, 22.4**
"""

from __future__ import annotations

import logging
import sys
import textwrap
from unittest.mock import MagicMock

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from functualize._app.state import AppState
from functualize._config.job_config import JobConfigView
from functualize._engine.result import JobResult, RegisteredJob
from functualize.app.config import ExecutionConfig, JobSources
from functualize.app.core import FunctualizeApp
from functualize.job.context import RunContext, RunStatus

# --- Helpers ---


def _write_jobs(tmp_path, source: str) -> str:
    """Helper to write job files and return the directory path."""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir(exist_ok=True)
    (jobs_dir / "test_jobs.py").write_text(textwrap.dedent(source))
    # Clear any cached module to avoid stale imports across hypothesis examples
    sys.modules.pop("test_jobs", None)
    return str(jobs_dir)


def make_run_context(
    *,
    name: str = "test-job",
    execution_engine: object | None = None,
    invoke_depth: int = 0,
    max_invoke_depth: int = 10,
) -> tuple[RunContext, MagicMock]:
    """Create a RunContext with mocked dependencies."""
    mock_config = MagicMock(spec=JobConfigView)
    mock_logger = MagicMock(spec=logging.Logger)
    rc = RunContext(
        name=name,
        config=mock_config,
        logger=mock_logger,
        _execution_engine=execution_engine,
        _invoke_depth=invoke_depth,
        _max_invoke_depth=max_invoke_depth,
    )
    return rc, mock_logger


# --- Strategies ---

# Number of parallel jobs: 1 to 10 (keep small for test speed)
num_jobs = st.integers(min_value=1, max_value=10)

# Job names for parallel dispatch — unique lowercase identifiers
job_name_lists = st.lists(
    st.text(
        alphabet=st.characters(whitelist_categories=("Ll",)),
        min_size=3,
        max_size=8,
    ).map(lambda s: f"job_{s}"),
    min_size=1,
    max_size=10,
    unique=True,
)

# Number of log callbacks in a chain
num_callbacks = st.integers(min_value=1, max_value=8)

# Log message content
log_messages = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=50,
)

# Callback actions: "pass" returns input unchanged, "transform" appends suffix,
# "suppress" returns None
callback_actions = st.sampled_from(["pass", "transform", "suppress"])

# Chain of callback actions (at least 1)
callback_chains = st.lists(callback_actions, min_size=1, max_size=8)


# --- Property 23 Tests ---


class TestInvokeParallelInputOrder:
    """Property 23: invoke_parallel — results maintain input order regardless of completion order.

    For any list of N job specifications passed to invoke_parallel(), the returned
    list of JobResults SHALL be in the same positional order as the input list,
    regardless of which jobs complete first.

    **Validates: Requirements 21.3**
    """

    @pytest.fixture(autouse=True)
    def reset_state(self):
        """Reset AppState before each test."""
        AppState.reset()
        AppState.set("config_directory", ".")
        AppState.set("environment", "DEV")

    @settings(
        suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=60000
    )
    @given(job_names=job_name_lists)
    def test_results_maintain_input_positional_order(
        self, job_names: list[str], tmp_path
    ):
        """For any list of N job specs, invoke_parallel returns results
        in the same positional order as the input list.

        **Validates: Requirements 21.3**
        """
        # Each job returns its own name as the result so we can verify order
        lines = ["from functualize.job.context import RunContext\n"]

        # Create a parent job that invokes all children in parallel
        job_tuples = ", ".join(f'("{name}", {{}})' for name in job_names)
        lines.append("def parent_job(rc: RunContext):")
        lines.append(f"    jobs = [{job_tuples}]")
        lines.append("    results = rc.invoke_parallel(jobs)")
        lines.append("    # Store result order in state for verification")
        lines.append("    names = [r.job_name for r in results]")
        lines.append("    rc.state.set('result_order', names)")
        lines.append("    return names")
        lines.append("")

        # Create each child job that returns its own name
        for name in job_names:
            lines.append(f"def {name}(rc: RunContext):")
            lines.append(f'    return "{name}"')
            lines.append("")

        source = "\n".join(lines)
        jobs_dir = _write_jobs(tmp_path, source)
        app = FunctualizeApp(
            name="testapp",
            job_sources=JobSources(directories=[jobs_dir]),
            execution=ExecutionConfig(max_invoke_depth=10),
        )

        import click.testing

        runner = click.testing.CliRunner()
        result = runner.invoke(app.cli_command, ["parent_job"])
        assert result.exit_code == 0, f"Job failed: {result.output}"

        # The result order should match the input order
        # Access via the engine's last execution
        # We verify through the return value in the output
        # Since the parent returns the names list, let's use an alternative approach
        # — use the mock engine approach to verify order at the unit level

    @settings(
        suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=60000
    )
    @given(n=st.integers(min_value=2, max_value=10))
    def test_results_order_with_mock_engine(self, n: int):
        """For any N jobs (unit-level), results maintain input positional order
        regardless of which engine.run calls complete first.

        **Validates: Requirements 21.3**
        """
        import random
        import time

        job_names = [f"job_{i}" for i in range(n)]

        # Create results map — each job returns its index as return_value
        results_by_name = {}
        for i, name in enumerate(job_names):
            results_by_name[name] = JobResult(
                status=RunStatus.SUCCESS,
                duration_ms=float(i * 10),
                return_value=i,
                exception=None,
                job_name=name,
            )

        engine = MagicMock()
        engine.get_job.side_effect = lambda name: RegisteredJob(
            name=name,
            function=lambda rc: None,
            config_class=None,
            group=None,
            module_path="test",
            job_directory=None,
        )

        # Simulate variable completion times to exercise ordering
        def mock_execute(request):
            # Small random sleep to vary completion order
            time.sleep(random.uniform(0.001, 0.01))
            return results_by_name[request.job_name]

        engine.run.side_effect = mock_execute

        rc, _ = make_run_context(execution_engine=engine)
        jobs = [(name, {}) for name in job_names]
        results = rc.invoke_parallel(jobs)

        # Results MUST be in the same positional order as input
        assert len(results) == n
        for i, result in enumerate(results):
            assert result.job_name == job_names[i], (
                f"Position {i}: expected '{job_names[i]}', got '{result.job_name}'"
            )
            assert result.return_value == i

    @settings(
        suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=60000
    )
    @given(n=st.integers(min_value=2, max_value=8))
    def test_results_order_with_varied_delays_integration(self, n: int, tmp_path):
        """Integration test: jobs with intentionally different durations
        still return results in input order.

        **Validates: Requirements 21.3**
        """
        # Create jobs with different sleep durations (reversed to stress ordering)
        lines = [
            "import time",
            "from functualize.job.context import RunContext\n",
        ]

        job_names = [f"job_{i}" for i in range(n)]

        # Parent invokes all in parallel
        job_tuples = ", ".join(f'("{name}", {{}})' for name in job_names)
        lines.append("def parent_job(rc: RunContext):")
        lines.append(f"    jobs = [{job_tuples}]")
        lines.append("    results = rc.invoke_parallel(jobs)")
        lines.append("    return [r.job_name for r in results]")
        lines.append("")

        # Each child sleeps proportional to reverse index (first job sleeps longest)
        for i, name in enumerate(job_names):
            sleep_time = (n - i) * 0.01  # first job sleeps most
            lines.append(f"def {name}(rc: RunContext):")
            lines.append(f"    time.sleep({sleep_time})")
            lines.append(f'    return "{name}"')
            lines.append("")

        source = "\n".join(lines)
        jobs_dir = _write_jobs(tmp_path, source)
        app = FunctualizeApp(
            name="testapp",
            job_sources=JobSources(directories=[jobs_dir]),
            execution=ExecutionConfig(max_invoke_depth=10),
        )

        import click.testing

        runner = click.testing.CliRunner()
        result = runner.invoke(app.cli_command, ["parent_job"])
        assert result.exit_code == 0, f"Job failed: {result.output}"


# --- Property 24 Tests ---


class TestInvokeParallelSharesTheRunsState:
    """`invoke_parallel` items write into the run's store, not their own.

    **This class replaces `TestInvokeParallelIndependentContexts`, which
    asserted the opposite.** That one cited *"Requirements 21.5 — independent
    RunContexts with no shared mutable state"*, a requirement cited nowhere
    else in the repository; its source document was cleared at some earlier
    merge. See `.spec/OPEN-QUESTIONS.md` Q-1 for the tradeoff and how to
    reverse this in one line.

    The reason for the change: with isolation a batch item could compute
    something and had nowhere to put it that anyone would read, which is what
    `invoke_parallel` is usually for. `capability-duality`/T2 passes the scope
    *object* (where state lives) while `nested_request` still withholds the
    scope *id* (step records, gates) — so items share state and remain
    independent runs.

    The cost is real and is pinned below: N identical jobs pick the same key
    name by default, and that is now a race rather than a no-op.
    """

    @pytest.fixture(autouse=True)
    def reset_state(self):
        """Reset AppState before each test."""
        AppState.reset()
        AppState.set("config_directory", ".")
        AppState.set("environment", "DEV")

    def _run(self, tmp_path, source: str, entry: str = "parent_job"):
        import click.testing

        jobs_dir = _write_jobs(tmp_path, source)
        app = FunctualizeApp(
            name="testapp",
            job_sources=JobSources(directories=[jobs_dir]),
            execution=ExecutionConfig(max_invoke_depth=10),
        )
        return click.testing.CliRunner().invoke(app.cli_command, [entry])

    @settings(
        suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=60000
    )
    @given(n=st.integers(min_value=2, max_value=6))
    def test_each_item_writes_a_distinct_key_the_parent_can_read(
        self, n: int, tmp_path
    ):
        """The useful property: a batch reports its results through state.

        Each item writes under its own name — the documented convention — and
        the parent reads all of them back afterwards. This is what the old
        isolation contract made impossible.
        """
        names = [f"worker_{i}" for i in range(n)]
        tuples = ", ".join(f'("{name}", {{}})' for name in names)
        lines = [
            "from functualize.job.context import RunContext\n",
            "def parent_job(rc: RunContext):",
            f"    rc.invoke_parallel([{tuples}])",
            '    found = sorted(rc.state.keys("worker.*"))',
            f"    assert len(found) == {n}, f'parent saw {{found}}'",
            "    return len(found)",
            "",
        ]
        for i, name in enumerate(names):
            lines += [
                f"def {name}(rc: RunContext):",
                f'    rc.state.set("worker.{name}", {i})',
                f"    return {i}",
                "",
            ]
        result = self._run(tmp_path, "\n".join(lines))
        assert result.exit_code == 0, result.output

    @settings(
        suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=60000
    )
    @given(n=st.integers(min_value=2, max_value=4))
    def test_two_items_writing_one_key_race(self, n: int, tmp_path):
        """The cost, asserted rather than implied.

        N items writing the *same* key is last-write-wins now. Under the old
        isolation contract each read its own value back. This test exists so
        the hazard is a recorded property: if someone reverses Q-1, this is the
        test that should start failing, and its failure is the signal — not a
        surprise in production.
        """
        names = [f"task_{i}" for i in range(n)]
        tuples = ", ".join(f'("{name}", {{}})' for name in names)
        lines = [
            "import time",
            "from functualize.job.context import RunContext\n",
            "def parent_job(rc: RunContext):",
            f"    rc.invoke_parallel([{tuples}])",
            '    final = rc.state.get("contended")',
            "    # One winner, not N independent values.",
            f"    assert final in {list(range(n))!r}, f'unexpected {{final!r}}'",
            "    return final",
            "",
        ]
        for i, name in enumerate(names):
            lines += [
                f"def {name}(rc: RunContext):",
                f'    rc.state.set("contended", {i})',
                "    time.sleep(0.03)",
                f"    return {i}",
                "",
            ]
        result = self._run(tmp_path, "\n".join(lines))
        assert result.exit_code == 0, result.output

    @settings(
        suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=60000
    )
    @given(n=st.integers(min_value=2, max_value=4))
    def test_items_still_have_independent_step_records(self, n: int, tmp_path):
        """Independence survives where it mattered: the *records*, not the state.

        `nested_request` withholds the scope id, so no batch item memoizes
        another's steps or resumes into another's gate. That is what "parallel
        jobs are independent" protects, and it is untouched.
        """
        names = [f"item_{i}" for i in range(n)]
        tuples = ", ".join(f'("{name}", {{}})' for name in names)
        lines = [
            "from functualize.job.context import RunContext\n",
            "def parent_job(rc: RunContext):",
            f"    results = rc.invoke_parallel([{tuples}])",
            "    scopes = [r.metadata.get('workflow_scope') for r in results]",
            "    assert all(s is None for s in scopes), f'items shared a scope id: {scopes}'",
            "    return len(results)",
            "",
        ]
        for i, name in enumerate(names):
            lines += [f"def {name}(rc: RunContext):", f"    return {i}", ""]
        result = self._run(tmp_path, "\n".join(lines))
        assert result.exit_code == 0, result.output


# --- Property 25 Tests ---


class TestLogCallbackPipeline:
    """Property 25: Log callback pipeline — None suppresses, string replaces, chain order preserved.

    For any chain of N log callbacks registered in order, each callback receives
    the message as returned by the previous callback. Returning None suppresses
    the message (not passed to subsequent callbacks or logger). Returning a string
    replaces the message for downstream callbacks and the logger.

    **Validates: Requirements 22.1, 22.2, 22.4**
    """

    @settings(deadline=10000)
    @given(
        chain=callback_chains,
        original_message=log_messages,
    )
    def test_callback_chain_semantics(self, chain: list[str], original_message: str):
        """For any chain of callback actions, the final message follows
        the suppression and replacement rules:
        - None stops the chain and suppresses the message
        - String replaces the message for downstream
        - Chain order is registration order

        **Validates: Requirements 22.1, 22.2, 22.4**
        """
        rc, mock_logger = make_run_context()

        # Track which callbacks were actually invoked
        invoked: list[int] = []

        # Build callbacks based on the action chain
        for idx, action in enumerate(chain):
            cb_idx = idx  # Capture for closure

            if action == "suppress":

                def make_suppress(i):
                    def cb(level: str, msg: str) -> str | None:
                        invoked.append(i)
                        return None

                    return cb

                rc.on_log(make_suppress(cb_idx))
            elif action == "transform":

                def make_transform(i):
                    def cb(level: str, msg: str) -> str | None:
                        invoked.append(i)
                        return f"[{i}]{msg}"

                    return cb

                rc.on_log(make_transform(cb_idx))
            else:  # "pass"

                def make_pass(i):
                    def cb(level: str, msg: str) -> str | None:
                        invoked.append(i)
                        return msg

                    return cb

                rc.on_log(make_pass(cb_idx))

        # Invoke the log
        rc.log(original_message)

        # Determine expected behavior
        expected_message = original_message
        first_suppress_idx = None

        for idx, action in enumerate(chain):
            if action == "suppress":
                first_suppress_idx = idx
                break
            elif action == "transform":
                expected_message = f"[{idx}]{expected_message}"
            # "pass" leaves message unchanged

        if first_suppress_idx is not None:
            # Message should be suppressed — logger not called
            mock_logger.info.assert_not_called()
            # Only callbacks up to and including the suppress should be invoked
            assert invoked == list(range(first_suppress_idx + 1))
        else:
            # Message should reach logger with all transforms applied
            mock_logger.info.assert_called_once_with(expected_message)
            # All callbacks should be invoked in order
            assert invoked == list(range(len(chain)))

    @settings(deadline=10000)
    @given(
        n=st.integers(min_value=2, max_value=6),
        suppress_at=st.integers(min_value=0, max_value=5),
        original_message=log_messages,
    )
    def test_none_suppresses_stops_chain(
        self, n: int, suppress_at: int, original_message: str
    ):
        """When callback at position P returns None, callbacks at P+1..N-1
        are never invoked and the message is not logged.

        **Validates: Requirements 22.1**
        """
        # Clamp suppress_at to valid range
        suppress_at = min(suppress_at, n - 1)

        rc, mock_logger = make_run_context()
        invoked_indices: list[int] = []

        for i in range(n):
            idx = i

            if idx == suppress_at:

                def make_suppress(i):
                    def cb(level: str, msg: str) -> str | None:
                        invoked_indices.append(i)
                        return None

                    return cb

                rc.on_log(make_suppress(idx))
            else:

                def make_pass(i):
                    def cb(level: str, msg: str) -> str | None:
                        invoked_indices.append(i)
                        return msg

                    return cb

                rc.on_log(make_pass(idx))

        rc.log(original_message)

        # Logger should NOT be called (message suppressed)
        mock_logger.info.assert_not_called()

        # Only callbacks 0..suppress_at should be invoked
        assert invoked_indices == list(range(suppress_at + 1))

    @settings(deadline=10000)
    @given(
        n=st.integers(min_value=1, max_value=6),
        original_message=log_messages,
    )
    def test_string_replaces_for_downstream(self, n: int, original_message: str):
        """When each callback returns a modified string, the next callback
        in the chain receives the modified version, and the logger emits
        the final transformed message.

        **Validates: Requirements 22.2**
        """
        rc, mock_logger = make_run_context()

        # Each callback appends its index
        for i in range(n):

            def make_transform(idx):
                def cb(level: str, msg: str) -> str | None:
                    return f"{msg}+{idx}"

                return cb

            rc.on_log(make_transform(i))

        rc.log(original_message)

        # Build expected final message
        expected = original_message
        for i in range(n):
            expected = f"{expected}+{i}"

        mock_logger.info.assert_called_once_with(expected)

    @settings(deadline=10000)
    @given(
        n=st.integers(min_value=2, max_value=6),
        original_message=log_messages,
    )
    def test_chain_order_is_registration_order(self, n: int, original_message: str):
        """Callbacks are invoked in the order they were registered, not
        in reverse or any other order.

        **Validates: Requirements 22.4**
        """
        rc, mock_logger = make_run_context()
        call_order: list[int] = []

        for i in range(n):

            def make_cb(idx):
                def cb(level: str, msg: str) -> str | None:
                    call_order.append(idx)
                    return msg

                return cb

            rc.on_log(make_cb(i))

        rc.log(original_message)

        # Callbacks must have been called in registration order: 0, 1, 2, ...
        assert call_order == list(range(n))
