"""TestRunContext builder — minimal RunContext construction for unit tests.

Provides a static factory `TestRunContext.create(...)` that builds a fully-functional
RunContext backed by test doubles with sensible defaults. Reduces test setup from
15-20 lines to 3-5 lines.

Requirements: 8.1, 8.2, 8.6, 8.7
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

from functualize._primitives.di import DIRegistry
from functualize.job.capabilities import Invoke, JobContext, Log, Perf, Prompt, State
from functualize.job.context import RunContext
from functualize.testing.doubles import AutoPrompt, CapturingLog, MockInvoke, NoopPerf


class TestRunContext:
    """Builder for test RunContext instances with sensible defaults.

    Example::

        from functualize.testing import TestRunContext

        rc = TestRunContext.create()
        # Use rc in your job function under test

        # Or with overrides:
        rc = TestRunContext.create(log=my_custom_log, state=my_state)

    ``rc.log(...)`` emits through the same ``Log`` the job would receive as an
    injected parameter, so messages logged either way are recorded by the
    default ``CapturingLog`` and can be asserted through ``captured_logs()``.
    """

    @staticmethod
    def create(
        *,
        log: Log | None = None,
        invoke: Invoke | None = None,
        prompt: Prompt | None = None,
        perf: Perf | None = None,
        state: State | None = None,
        job_context: JobContext | None = None,
    ) -> RunContext:
        """Create a RunContext for testing with optional capability overrides.

        Each omitted parameter uses a default test double:
        - log: CapturingLog (records all calls)
        - invoke: MockInvoke({}) (no configured results)
        - prompt: AutoPrompt([]) (no pre-configured answers)
        - perf: NoopPerf (silently accepts all calls)
        - state: empty State instance
        - job_context: JobContext(name="test", trace_id=None, deadline=None, metadata=empty)

        Args:
            log: Override for the Log capability.
            invoke: Override for the Invoke capability.
            prompt: Override for the Prompt capability.
            perf: Override for the Perf capability.
            state: Override for the State capability.
            job_context: Override for the JobContext capability.

        Returns:
            A fully-constructed RunContext backed by a DIRegistry containing
            the resolved test doubles.
        """
        # Apply defaults for any omitted capabilities
        effective_log = log if log is not None else CapturingLog()
        effective_invoke = invoke if invoke is not None else MockInvoke({})
        effective_prompt = prompt if prompt is not None else AutoPrompt([])
        effective_perf = perf if perf is not None else NoopPerf()
        effective_state = state if state is not None else State()
        effective_job_context = (
            job_context
            if job_context is not None
            else JobContext(
                name="test",
                trace_id=None,
                deadline=None,
            )
        )

        # Build a DIRegistry with test doubles
        registry = DIRegistry()
        registry.provide(Log, effective_log)
        registry.provide(Invoke, effective_invoke)
        registry.provide(Prompt, effective_prompt)
        registry.provide(Perf, effective_perf)
        registry.provide(State, effective_state)
        registry.provide(JobContext, effective_job_context)

        # Create a minimal config mock that satisfies the RunContext constructor
        mock_config: Any = MagicMock()
        mock_config.set_prefix = MagicMock()

        # Create a silent logger for tests
        test_logger = logging.getLogger("functualize.test")

        # Construct the RunContext with the DI registry
        rc = RunContext(
            name=effective_job_context.name,
            config=mock_config,
            logger=test_logger,
            _di_registry=registry,
            # The per-invocation capability map the engine would hand a real
            # RunContext. rc.log() reads its Log out of here, so the double
            # sees rc.log(...) exactly as the injected `log: Log` parameter
            # would in production.
            _caps={
                Log: effective_log,
                Invoke: effective_invoke,
                Prompt: effective_prompt,
                Perf: effective_perf,
                State: effective_state,
                JobContext: effective_job_context,
            },
        )

        return rc

    @staticmethod
    def captured_logs(rc: RunContext) -> list[tuple[str, object]]:
        """Retrieve the ordered list of (level, message) tuples from the RunContext's log.

        Accesses the CapturingLog instance registered in the RunContext's DI registry
        and returns its recorded calls. Messages emitted via ``rc.log(...)`` are
        included: the same double sits in the RunContext's per-invocation
        capability map, which is where ``RunContext.log()`` takes its sink from.

        Args:
            rc: A RunContext created by TestRunContext.create().

        Returns:
            Ordered list of (level, message) tuples recorded by the CapturingLog.

        Raises:
            RuntimeError: If the RunContext has no DI registry attached.
            TypeError: If the registered Log is not a CapturingLog instance.
        """
        log_instance = rc[Log]
        if not isinstance(log_instance, CapturingLog):
            raise TypeError(
                f"Expected CapturingLog in RunContext, got {type(log_instance).__name__}. "
                f"captured_logs() only works with the default CapturingLog test double."
            )
        return log_instance.calls
