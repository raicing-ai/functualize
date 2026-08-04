"""Webhook adapter — delivers job results via HTTP POST.

Implements the AdapterPlugin protocol from functualize. After a job
executes, the adapter POSTs the result to the configured webhook URL.
"""

from __future__ import annotations

from typing import Any

from functualize_webhook._config import WebhookConfig


class WebhookAdapter:
    """Delivery adapter that POSTs job results to a webhook URL.

    Satisfies the AdapterPlugin protocol:
    - adapter_type: str identifying this adapter
    - __call__(app): initialization with the FunctualizeApp
    - run(**kwargs): execute and deliver results

    Example usage:
        adapter = WebhookAdapter(webhook_url="https://hooks.example.com/jobs")
        adapter(app)
        adapter.run(job_name="deploy", kwargs={"version": "v1.0.0"})
    """

    adapter_type: str = "webhook"

    def __init__(
        self,
        webhook_url: str = "",
        secret: str = "",
        timeout: int = 10,
        retry_count: int = 3,
        include_logs: bool = False,
    ) -> None:
        """Initialize the adapter with webhook configuration.

        Args:
            webhook_url: URL to POST results to.
            secret: Shared secret for payload signing.
            timeout: HTTP request timeout.
            retry_count: Retries on delivery failure.
            include_logs: Whether to include job logs in the payload.
        """
        self._config = WebhookConfig(
            webhook_url=webhook_url,
            secret=secret,
            timeout=timeout,
            retry_count=retry_count,
            include_logs=include_logs,
        )
        self._app: Any = None
        self._deliveries: list[dict] = []  # Track deliveries for testing

    def __call__(self, app: Any) -> None:
        """Initialize the adapter with a FunctualizeApp instance.

        This is called during app boot. The adapter stores a reference
        to the app for executing jobs via app.execute().

        Args:
            app: The FunctualizeApp instance.
        """
        self._app = app

    def run(self, job_name: str, kwargs: dict[str, Any] | None = None) -> dict:
        """Execute a job and deliver results via webhook.

        Args:
            job_name: Name of the job to execute.
            kwargs: Arguments to pass to the job.

        Returns:
            Delivery result with job_result and webhook_status.
        """
        if self._app is None:
            raise RuntimeError("Adapter not initialized — call adapter(app) first")

        # Execute the job
        job_result = self._app.execute(job_name, **(kwargs or {}))

        # Build webhook payload
        payload = {
            "job_name": job_name,
            "status": job_result.status.value
            if hasattr(job_result.status, "value")
            else str(job_result.status),
            "return_value": job_result.return_value,
            "duration_ms": job_result.duration_ms,
            "kwargs": kwargs or {},
        }

        # Deliver via webhook (simulated — real impl would use httpx/urllib)
        delivery = self._deliver(payload)

        return {
            "job_result": job_result,
            "webhook_status": delivery["status"],
            "webhook_url": self._config.webhook_url,
        }

    def _deliver(self, payload: dict) -> dict:
        """Deliver payload to webhook URL (simulated for example).

        In a real implementation, this would:
        1. JSON-encode the payload
        2. Compute HMAC signature with the secret
        3. POST to webhook_url with signature header
        4. Retry on failure up to retry_count times
        """
        delivery_record = {
            "url": self._config.webhook_url,
            "payload": payload,
            "status": "delivered",
            "attempts": 1,
        }
        self._deliveries.append(delivery_record)
        return delivery_record

    @property
    def deliveries(self) -> list[dict]:
        """Access delivery history (useful for testing)."""
        return self._deliveries
