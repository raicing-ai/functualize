"""Lambda application wiring — configures FunctualizeApp with Lambda adapter.

Demonstrates two deployment patterns:
1. Fat Lambda — single handler routing via event["job"]
2. Thin Lambda — one handler per job via make_handler()
"""

from functualize_lambda import LambdaAdapter

from functualize.app import FunctualizeApp, JobSources, twelve_factor
from lambda_service.jobs import process_order, send_notification

# Create the app with explicit function registration (no directory scanning).
# This minimizes cold start time in Lambda — no filesystem I/O at boot.
app = FunctualizeApp(
    name="lambda-service",
    job_sources=JobSources(functions=[process_order, send_notification]),
    config_sources=twelve_factor(),  # Env vars only — no config files in Lambda
)

# Create the Lambda adapter
adapter = LambdaAdapter()
adapter(app)


# ---------------------------------------------------------------------------
# Fat Lambda handler — routes based on event["job"]
# ---------------------------------------------------------------------------


def fat_handler(event: dict, context) -> dict:
    """Single Lambda entry point with internal job routing.

    Event format: {"job": "process_order", "kwargs": {"order_id": "ORD-123"}}
    """
    return adapter.run(event, context)


# ---------------------------------------------------------------------------
# Thin Lambda handlers — one per job
# ---------------------------------------------------------------------------

process_order_handler = adapter.make_handler("process_order")
send_notification_handler = adapter.make_handler("send_notification")
