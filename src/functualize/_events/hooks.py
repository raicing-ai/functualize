"""Lifecycle hook registry for managing global and job-scoped hooks.

HookRegistry is a facade over EventBus that provides a familiar hook-based
API for lifecycle events (before_job, after_success, after_failure, etc.)
while routing through the event bus internally.

Only imports from _types/, _primitives/, and stdlib.
"""

from __future__ import annotations

import copy
import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


def _accepts_keyword(fn: Callable[..., Any], param_name: str) -> bool:
    """Check if a callable accepts a given keyword parameter.

    Handles both regular functions and bound methods. Returns True if the
    function has the named parameter or accepts **kwargs.

    Args:
        fn: The callable to inspect.
        param_name: The keyword parameter name to check for.

    Returns:
        True if the callable accepts the given keyword parameter.
    """
    try:
        sig = inspect.signature(fn)
    except (ValueError, TypeError):
        return False

    for name, param in sig.parameters.items():
        if name == param_name:
            return True
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return True
    return False


@dataclass(frozen=True)
class HookDecision:
    """Return type for PRE_EXECUTE hooks.

    PRE_EXECUTE hooks can return a HookDecision to control execution flow:
    - PROCEED(): Continue execution unchanged
    - BLOCK(reason): Skip job execution, return failure with reason
    - MODIFY(kwargs): Replace call kwargs before invoking the job
    """

    action: str  # "proceed" | "block" | "modify"
    reason: str | None = None  # For BLOCK: 1-500 chars
    kwargs: dict[str, Any] | None = None  # For MODIFY: replacement kwargs

    @classmethod
    def PROCEED(cls) -> HookDecision:  # noqa: N802
        """Create a PROCEED decision — continue execution unchanged."""
        return cls(action="proceed")

    @classmethod
    def BLOCK(cls, reason: str) -> HookDecision:  # noqa: N802
        """Create a BLOCK decision — skip job execution with a reason.

        Args:
            reason: Explanation for blocking (1-500 characters).
        """
        return cls(action="block", reason=reason)

    @classmethod
    def MODIFY(cls, kwargs: dict[str, Any]) -> HookDecision:  # noqa: N802
        """Create a MODIFY decision — replace call kwargs.

        Args:
            kwargs: Replacement keyword arguments for the job function.
        """
        return cls(action="modify", kwargs=kwargs)

    @property
    def is_block(self) -> bool:
        """True if this decision blocks execution."""
        return self.action == "block"

    @property
    def is_modify(self) -> bool:
        """True if this decision modifies call kwargs."""
        return self.action == "modify"


class HookEvent:
    """Constants for lifecycle hook events."""

    BEFORE_JOB = "before_job"
    AFTER_SUCCESS = "after_success"
    AFTER_FAILURE = "after_failure"
    ON_TEARDOWN = "on_teardown"
    JOB_REGISTERED = "job_registered"
    """Fired when a job is registered with the framework."""

    PRE_EXECUTE = "pre_execute"
    """Fired after config resolution and before the job function is called."""

    APP_READY = "app_ready"
    """Fired after the application has fully booted."""

    INVOKE_START = "invoke_start"
    """Fired before a nested rc.invoke() child job begins execution."""

    INVOKE_END = "invoke_end"
    """Fired after a nested rc.invoke() child job completes execution."""

    INVOKE_FAILURE = "invoke_failure"
    """Fired after a nested rc.invoke() child job completes with FAILURE status."""

    ON_PHASE_START = "on_phase_start"
    """Fired when track_phase() creates a NEW phase."""

    ON_PHASE_FAILURE = "on_phase_failure"
    """Fired when track_phase() transitions a phase to FAILURE status."""

    ON_PHASE_COMPLETE = "on_phase_complete"
    """Fired when track_phase() transitions a phase to SUCCESS status."""

    ON_SCOPE_CREATED = "on_scope_created"
    """Fired when a WorkflowScope is created."""

    TUI_STARTED = "tui_started"
    """Fired when the TUI application launches."""


class ConfigHookEvent:
    """Constants for configuration lifecycle hook events.

    These events fire during the config system's initialization and resolution,
    distinct from job lifecycle events (BEFORE_JOB, AFTER_SUCCESS, etc.).
    """

    AFTER_CONFIG_INIT = "after_config_init"
    """Fired after the Resolution_Chain is built and all providers are registered."""

    BEFORE_CONFIG_RESOLVE = "before_config_resolve"
    """Fired before a Settings_Model is resolved from the chain."""

    AFTER_CONFIG_RESOLVE = "after_config_resolve"
    """Fired after a Settings_Model is successfully resolved."""


# Sentinel to distinguish "no result passed" from "result=None passed"
_NO_RESULT = object()


class HookRegistry:
    """Manages lifecycle hooks for job execution.

    Global hooks are invoked for all jobs, while job-scoped hooks
    are invoked only for the specific job they are registered to.
    Hooks are invoked in registration order, with global hooks first.
    """

    def __init__(self) -> None:
        self._global_hooks: dict[str, list[Callable[..., Any]]] = {}
        self._job_hooks: dict[str, dict[str, list[Callable[..., Any]]]] = {}

    def register_global(self, event: str, hook: Callable[..., Any]) -> None:
        """Register a hook that fires for all jobs on the given event.

        Args:
            event: The lifecycle event (use HookEvent or ConfigHookEvent constants).
            hook: The callable to invoke. Signature depends on event.
        """
        if event not in self._global_hooks:
            self._global_hooks[event] = []
        self._global_hooks[event].append(hook)

    def register_for_job(
        self, job_name: str, event: str, hook: Callable[..., Any]
    ) -> None:
        """Register a hook scoped to a specific job.

        Args:
            job_name: The name of the job this hook applies to.
            event: The lifecycle event (use HookEvent constants).
            hook: The callable to invoke.
        """
        if job_name not in self._job_hooks:
            self._job_hooks[job_name] = {}
        if event not in self._job_hooks[job_name]:
            self._job_hooks[job_name][event] = []
        self._job_hooks[job_name][event].append(hook)

    def invoke(
        self,
        event: str,
        job_name: str,
        rc: Any,
        exception: BaseException | None = None,
        *,
        kwargs: dict[str, Any] | None = None,
        result: Any = _NO_RESULT,
        capabilities: dict[type, Any] | None = None,
    ) -> None:
        """Invoke all hooks registered for the given event and job.

        Global hooks are invoked first (in registration order), then
        job-scoped hooks (in registration order). If a hook raises an
        exception, the error is logged at ERROR level and remaining hooks
        continue executing.

        Signature-adaptive dispatch:
        - BEFORE_JOB: If kwargs is provided and hook accepts a `kwargs` param,
          pass a fresh shallow copy. Otherwise invoke with only rc.
        - AFTER_SUCCESS: If result was passed and hook accepts a `result` param,
          pass the result value. If capabilities is provided and hook accepts a
          `capabilities` param, pass the capabilities dict.
        - AFTER_FAILURE: Always invoke with (rc, exception).
        - Others: invoke with (rc).

        Args:
            event: The lifecycle event being triggered.
            job_name: The name of the job being executed.
            rc: The RunContext for the current job execution.
            exception: The exception (if any) for AFTER_FAILURE events.
            kwargs: Original kwargs dict for BEFORE_JOB hooks.
            result: The job's return value for AFTER_SUCCESS hooks.
            capabilities: The resolved per-invocation capabilities dict.
        """
        hooks_to_invoke: list[Callable[..., Any]] = []

        # Global hooks first
        hooks_to_invoke.extend(self._global_hooks.get(event, []))

        # Then job-scoped hooks
        job_hooks = self._job_hooks.get(job_name, {})
        hooks_to_invoke.extend(job_hooks.get(event, []))

        # Determine if result was explicitly passed (even if None)
        has_result = result is not _NO_RESULT
        _capabilities = capabilities or {}

        for hook in hooks_to_invoke:
            try:
                if event == HookEvent.AFTER_FAILURE:
                    hook(rc, exception)
                elif event == HookEvent.BEFORE_JOB and kwargs is not None:
                    if _accepts_keyword(hook, "kwargs"):
                        hook(rc, kwargs=copy.copy(kwargs))
                    else:
                        hook(rc)
                elif event == HookEvent.AFTER_SUCCESS and has_result:
                    hook_kwargs: dict[str, Any] = {}
                    if _accepts_keyword(hook, "result"):
                        hook_kwargs["result"] = result
                    if _capabilities and _accepts_keyword(hook, "capabilities"):
                        hook_kwargs["capabilities"] = _capabilities
                    if hook_kwargs:
                        hook(rc, **hook_kwargs)
                    else:
                        hook(rc)
                else:
                    hook(rc)
            except Exception as e:
                hook_name = getattr(hook, "__name__", repr(hook))
                logger.error(
                    f"Hook {hook_name!r} raised an error during "
                    f"'{event}' for job '{job_name}': {e}"
                )

    def invoke_pre_execute(
        self,
        job_name: str,
        rc: Any,
        kwargs: dict[str, Any],
        *,
        capabilities: dict[type, Any] | None = None,
    ) -> HookDecision | None:
        """Invoke PRE_EXECUTE hooks in registration order.

        Each hook receives (rc, kwargs_copy) and returns HookDecision or None.
        If the hook accepts a `capabilities` keyword argument, the resolved
        per-invocation capabilities dict is also passed.

        - On MODIFY: replace kwargs with decision.kwargs, pass modified kwargs to next hook
        - On BLOCK: stop immediately, return the BLOCK decision
        - On exception: log ERROR, treat as PROCEED, continue to next hook
        - On PROCEED or None: continue to next hook

        Args:
            job_name: The name of the job being executed.
            rc: The RunContext for the current job execution.
            kwargs: The resolved call kwargs (will be copied before passing to hooks).
            capabilities: The resolved per-invocation capabilities dict.

        Returns:
            The final HookDecision if a BLOCK was encountered or MODIFY accumulated,
            or None if all hooks returned PROCEED/None.
        """
        hooks_to_invoke: list[Callable[..., Any]] = []

        # Global hooks first
        hooks_to_invoke.extend(self._global_hooks.get(HookEvent.PRE_EXECUTE, []))

        # Then job-scoped hooks
        job_hooks = self._job_hooks.get(job_name, {})
        hooks_to_invoke.extend(job_hooks.get(HookEvent.PRE_EXECUTE, []))

        if not hooks_to_invoke:
            return None

        current_kwargs = dict(kwargs)
        was_modified = False
        _capabilities = capabilities or {}

        for hook in hooks_to_invoke:
            try:
                if _capabilities and _accepts_keyword(hook, "capabilities"):
                    decision = hook(
                        rc, dict(current_kwargs), capabilities=_capabilities
                    )
                else:
                    decision = hook(rc, dict(current_kwargs))
            except Exception as e:
                hook_name = getattr(hook, "__name__", repr(hook))
                logger.error(
                    f"PRE_EXECUTE hook {hook_name!r} raised an error for "
                    f"job '{job_name}': {e}"
                )
                continue

            if decision is None:
                continue

            if decision.is_block:
                return decision  # type: ignore[no-any-return]

            if decision.is_modify and decision.kwargs is not None:
                current_kwargs = decision.kwargs
                was_modified = True

        if was_modified:
            return HookDecision.MODIFY(current_kwargs)

        return None

    def invoke_job_registered(self, metadata: dict[str, Any]) -> None:
        """Invoke all hooks registered for the JOB_REGISTERED event.

        Hook failures are logged at WARNING level but do NOT prevent
        job registration from proceeding.

        Args:
            metadata: Job metadata dict with keys: name, group, config_schema, docstring.
        """
        hooks = self._global_hooks.get(HookEvent.JOB_REGISTERED, [])

        for hook in hooks:
            try:
                hook(metadata)
            except Exception as e:
                hook_name = getattr(hook, "__name__", repr(hook))
                logger.warning(
                    f"Hook {hook_name!r} raised an error during "
                    f"'{HookEvent.JOB_REGISTERED}': {e}"
                )

    def invoke_config_event(self, event: str, *args: Any, **kwargs: Any) -> None:
        """Invoke all hooks registered for a configuration lifecycle event.

        Hook failures are logged at WARNING level but do NOT prevent
        config resolution from proceeding.

        Args:
            event: The config lifecycle event (use ConfigHookEvent constants).
            *args: Positional arguments passed to each hook.
            **kwargs: Keyword arguments passed to each hook.
        """
        hooks = self._global_hooks.get(event, [])

        for hook in hooks:
            try:
                hook(*args, **kwargs)
            except Exception as e:
                hook_name = getattr(hook, "__name__", repr(hook))
                logger.warning(
                    f"Config hook {hook_name!r} raised an error during '{event}': {e}"
                )

    @property
    def has_callbacks(self) -> bool:
        """True if any hooks have callbacks registered."""
        return bool(self._global_hooks or self._job_hooks)
