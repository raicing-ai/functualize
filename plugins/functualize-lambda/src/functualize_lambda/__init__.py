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

if TYPE_CHECKING:
    from functualize.app.core import FunctualizeApp


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
            job_kwargs = event.get("kwargs", {})
            try:
                result = app.execute(job_name, **job_kwargs)
                return {"statusCode": 200, "body": result.return_value}
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

        job_kwargs = event.get("kwargs", {})

        try:
            result = self._app.execute(job_name, **job_kwargs)
            return {"statusCode": 200, "body": result.return_value}
        except Exception as exc:
            return {"statusCode": 500, "body": str(exc)}


__all__ = ["LambdaAdapter"]
