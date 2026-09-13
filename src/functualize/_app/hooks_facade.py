"""Every hook and middleware registration point — `app.hooks`.

Extracted from :class:`~functualize.app.core.FunctualizeApp`
(engine-sealed-construction/T9). Fifteen members, all the same shape: a
decorator that registers a callback against one lifecycle event. On the flat
class they were fifteen four-line properties reading identically, which is what
made `FunctualizeApp` 71 public members wide — and a class that wide cannot be
put on a diet by moving bodies, only by grouping names.

`app.hooks.on_job_failure` says what `app.hooks.on_job_failure` said, in a place that
tells you there are fourteen siblings.

**Job-scoped vs global.** The five that take an optional job name —
``on_job_failure``, ``on_job_success``, ``on_job_teardown``, ``before_job``,
``pre_execute`` — register globally when called bare and for one job when given
its name. The phase and invoke hooks are global only, and say so in each
docstring rather than failing at registration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from functualize.app.core import FunctualizeApp

__all__ = ["HooksFacade"]


class HooksFacade:
    """`app.hooks` — register a callback against a lifecycle event."""

    __slots__ = ("_app",)

    def __init__(self, app: FunctualizeApp) -> None:
        self._app = app

    # --- Job-scoped or global ---

    @property
    def on_job_failure(self) -> Callable[..., Any]:
        """Decorator: register AFTER_FAILURE hook (global or job-scoped)."""
        from functualize._app.impl import make_on_job_failure_decorator

        return make_on_job_failure_decorator(self._app)

    @property
    def on_job_success(self) -> Callable[..., Any]:
        """Decorator: register AFTER_SUCCESS hook (global or job-scoped)."""
        from functualize._app.impl import make_on_job_success_decorator

        return make_on_job_success_decorator(self._app)

    @property
    def on_job_teardown(self) -> Callable[..., Any]:
        """Decorator: register ON_TEARDOWN hook (global or job-scoped)."""
        from functualize._app.impl import make_on_job_teardown_decorator

        return make_on_job_teardown_decorator(self._app)

    @property
    def before_job(self) -> Callable[..., Any]:
        """Decorator: register BEFORE_JOB hook (global or job-scoped)."""
        from functualize._app.impl import make_before_job_decorator

        return make_before_job_decorator(self._app)

    @property
    def pre_execute(self) -> Callable[..., Any]:
        """Decorator: register PRE_EXECUTE hook (global or job-scoped)."""
        from functualize._app.impl import make_pre_execute_decorator

        return make_pre_execute_decorator(self._app)

    # --- Global only ---

    @property
    def on_phase_failure(self) -> Callable[..., Any]:
        """Decorator: register ON_PHASE_FAILURE hook (global only)."""
        from functualize._app.impl import make_on_phase_failure_decorator

        return make_on_phase_failure_decorator(self._app)

    @property
    def on_phase_complete(self) -> Callable[..., Any]:
        """Decorator: register ON_PHASE_COMPLETE hook (global only)."""
        from functualize._app.impl import make_on_phase_complete_decorator

        return make_on_phase_complete_decorator(self._app)

    @property
    def on_phase_start(self) -> Callable[..., Any]:
        """Decorator: register ON_PHASE_START hook (global only)."""
        from functualize._app.impl import make_on_phase_start_decorator

        return make_on_phase_start_decorator(self._app)

    @property
    def on_invoke_failure(self) -> Callable[..., Any]:
        """Decorator: register INVOKE_FAILURE hook (global only)."""
        from functualize._app.impl import make_on_invoke_failure_decorator

        return make_on_invoke_failure_decorator(self._app)

    @property
    def on_invoke_start(self) -> Callable[..., Any]:
        """Decorator: register INVOKE_START hook (global only)."""
        from functualize._app.impl import make_on_invoke_start_decorator

        return make_on_invoke_start_decorator(self._app)

    @property
    def on_invoke_end(self) -> Callable[..., Any]:
        """Decorator: register INVOKE_END hook (global only)."""
        from functualize._app.impl import make_on_invoke_end_decorator

        return make_on_invoke_end_decorator(self._app)

    @property
    def on_ready(self) -> Callable[..., Any]:
        """Decorator: register APP_READY hook (global only)."""
        from functualize._app.impl import make_on_ready_decorator

        return make_on_ready_decorator(self._app)

    # --- Events and middleware ---

    def on_event(self, pattern: str) -> Callable[..., Any]:
        """Decorator: subscribe to custom events matching ``pattern``."""
        from functualize._app.impl import make_on_event_decorator

        return make_on_event_decorator(self._app, pattern)

    @property
    def run_middleware(self) -> Callable[..., Any]:
        """Decorator: register generator-based RunContext middleware."""
        from functualize._app.impl import make_run_middleware_decorator

        return make_run_middleware_decorator(self._app)

    def register_run_middleware(
        self,
        middleware: Callable[[Any], Generator[None]],
        priority: int = 0,
    ) -> None:
        """Register RunContext middleware for job execution wrapping."""
        from functualize._app.impl import register_run_middleware

        register_run_middleware(self._app, middleware, priority)
