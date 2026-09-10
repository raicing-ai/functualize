"""Functualize Lambda Adapter Plugin — AWS Lambda delivery for FunctualizeApp.

Implements the AdapterPlugin Protocol with adapter_type="lambda".
Supports two deployment patterns:

1. Fat Lambda (internal routing):
   - Single Lambda function handling multiple jobs
   - Event contains {"job": "job_name", "kwargs": {...}}
   - Adapter routes to the correct job via app.execute()

2. Thin Lambda (per-job handler):
   - One Lambda function per job, routing handled by infrastructure
   - Use make_handler(job_name) to create a bound handler

Both patterns work with the static wiring fast path for <5ms cold start
when using JobSources(functions=[...]) with fully-explicit config.

Usage (fat Lambda):
    app = FunctualizeApp("my-app", job_sources=JobSources(functions=[deploy, rollback]))
    adapter = LambdaAdapter()
    adapter(app)

    def handler(event, context):
        return adapter.run(event, context)

Usage (thin Lambda):
    app = FunctualizeApp("my-app", job_sources=JobSources(functions=[deploy]))
    adapter = LambdaAdapter()
    adapter(app)

    handler = adapter.make_handler("deploy")
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from functualize.types import RunRequest, http_status_for_status

if TYPE_CHECKING:
    from functualize.app.core import FunctualizeApp


def _envelope(payload: dict[str, Any], job_name: str) -> RunRequest:
    """Build the request from a wire payload.

    The shape is an **envelope**: the job's own parameters live in a nested
    ``arguments`` object and the control inputs sit beside it, never inside::

        {"arguments": {"target": "prod"},
         "group_option_values": {"env": "staging"},
         "scope_id": "run-42",
         "force": true}

    The nesting is the fix, not decoration. A flat body meant a caller's key
    could bind to a control parameter — send ``{"scope_id": "x"}`` and you were
    choosing the workflow scope the run joined rather than passing an argument
    (risk R-a, spec AC-9). Nested, a job parameter literally named ``scope_id``
    arrives as an argument and the scope stays a separate, deliberate choice.

    ``scope_id`` is also what makes a gated workflow **resumable over the wire**:
    start it, read the scope id back from the result metadata, answer the gate,
    send the same id again. The audit recorded that as impossible (D-6) because
    there was no field to put it in.

    **Breaking, deliberately.** Job parameters used to be the whole body; they
    are now under ``arguments``.
    """
    arguments = payload.get("arguments") or {}
    if not isinstance(arguments, dict):
        raise ValueError("'arguments' must be a JSON object")
    group_options = payload.get("group_option_values") or None
    if group_options is not None and not isinstance(group_options, dict):
        raise ValueError("'group_option_values' must be a JSON object")
    scope_id = payload.get("scope_id")
    if scope_id is not None and not isinstance(scope_id, str):
        raise ValueError("'scope_id' must be a string")
    return RunRequest(
        job_name=job_name,
        surface="lambda",
        kwargs=arguments,
        group_option_values=group_options,
        workflow_scope_id=scope_id,
        force=bool(payload.get("force", False)),
    )


def _response(result: Any) -> dict[str, Any]:
    """Turn a finished run into a Lambda proxy response.

    Both handler shapes -- fat (``_handle_event``) and thin
    (``make_handler``) -- go through here, because two copies is how the two
    drifted from the status table in the first place.

    Before this, every outcome the engine *returned* was reported as
    ``{"statusCode": 200, "body": None}``: ``result.status`` was never read.
    A failure, a refusal, and a workflow paused at a gate were all
    indistinguishable from a job that succeeded and returned nothing. Only an
    exception escaping ``execute()`` became a 500 -- and the engine's whole
    design is that failures do *not* escape, so the one branch that reported
    failure was the branch the engine tries hardest never to take.

    ``status`` and ``error`` are added rather than substituted: a caller
    reading ``body`` on success keeps reading exactly what it read before.

    This surface declares :attr:`~functualize.types.Family.WIRE`: a finished
    run reads as an HTTP status code, and the outcome authority's WIRE table
    renders it -- BLOCKED is 202, resumable rather than an error. The family
    used to be implied by importing the WIRE table's function; naming it
    keeps the surface-to-family map greppable when a status lands.
    """
    status = result.status
    payload: dict[str, Any] = {
        "statusCode": http_status_for_status(status),
        "status": status.value if hasattr(status, "value") else str(status),
        "body": result.return_value,
    }
    exception = getattr(result, "exception", None)
    if exception is not None:
        # A 500 whose body is `null` tells a caller nothing at all.
        payload["error"] = str(exception)
    return payload


class LambdaAdapter:
    """AWS Lambda delivery adapter.

    Satisfies the AdapterPlugin Protocol. Supports fat-Lambda (internal
    routing via event["job"]) and thin-Lambda (per-job handler via
    make_handler()) deployment patterns.

    PluginMetadata attributes:
        name: "functualize-lambda"
        version: "1.0.0"
        description: "AWS Lambda adapter supporting fat and thin Lambda patterns"
    """

    name: str = "functualize-lambda"
    version: str = "1.0.0"
    description: str = "AWS Lambda adapter supporting fat and thin Lambda patterns"
    adapter_type: str = "lambda"

    def __init__(self) -> None:
        self._app: FunctualizeApp | None = None

    def __call__(self, app: FunctualizeApp) -> None:
        """Setup phase — store app reference.

        Args:
            app: The FunctualizeApp kernel instance.
        """
        self._app = app

    def run(self, *args: Any, **kwargs: Any) -> Any:
        """Fat Lambda entrypoint — route event to the correct job.

        Parses the event to determine which job to execute and with
        what arguments, then delegates to the kernel's execute method.

        Args:
            *args: Expected to be (event, context) where event is a dict
                containing "job" (required) and "kwargs" (optional).

        Returns:
            Dict with "statusCode" (200 or 500) and "body" (result or
            error message).

        Raises:
            RuntimeError: If run() is called before __call__(app).
        """
        if self._app is None:
            raise RuntimeError("LambdaAdapter.run() called before __call__(app)")

        # Extract event and context from positional args
        event: dict[str, Any] = args[0] if args else kwargs.get("event", {})
        # context is available but not used by the adapter itself
        # _context = args[1] if len(args) > 1 else kwargs.get("context")

        return self._handle_event(event)

    def make_handler(self, job_name: str) -> Callable[..., Any]:
        """Create a thin-Lambda handler bound to a specific job.

        Returns a callable with the standard Lambda signature
        (event, context) that always executes the specified job.
        Event kwargs can still be provided via event.get("kwargs", {}).

        Args:
            job_name: The name of the job this handler will execute.

        Returns:
            A callable(event, context) -> dict suitable as a Lambda handler.

        Raises:
            RuntimeError: If make_handler() is called before __call__(app).
        """
        if self._app is None:
            raise RuntimeError(
                "LambdaAdapter.make_handler() called before __call__(app)"
            )

        app = self._app

        def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
            """Thin Lambda handler for job '{job_name}'."""
            try:
                request = _envelope(event, job_name)
                return _response(app.execute(request))
            except Exception as exc:
                return {"statusCode": 500, "body": str(exc)}

        # Set a useful name for debugging/logging
        handler.__name__ = f"lambda_handler_{job_name}"
        handler.__qualname__ = (
            f"LambdaAdapter.make_handler.<locals>.handler[{job_name}]"
        )

        return handler

    def shutdown(self) -> None:
        """No-op shutdown. Lambda functions are stateless."""
        pass

    def _handle_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Internal: parse event and execute the job.

        Args:
            event: Lambda event dict with "job" and optional "kwargs".

        Returns:
            Dict with "statusCode" and "body".
        """
        assert self._app is not None

        try:
            job_name = event["job"]
        except (KeyError, TypeError) as exc:
            return {
                "statusCode": 400,
                "body": f"Missing required field 'job' in event: {exc}",
            }

        try:
            request = _envelope(event, job_name)
            return _response(self._app.execute(request))
        except Exception as exc:
            return {"statusCode": 500, "body": str(exc)}


__all__ = ["LambdaAdapter"]
