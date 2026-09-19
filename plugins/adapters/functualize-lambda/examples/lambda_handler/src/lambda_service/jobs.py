"""Job definitions for the Lambda service.

These jobs are registered explicitly via JobSources(functions=[...])
rather than directory scanning — common in Lambda where cold start
time matters and we want minimal import overhead.
"""

from pydantic import BaseModel, Field

from functualize.job.context import RunContext
from functualize.job.decorators import job

# ---------------------------------------------------------------------------
# Job 1: Process Order
# ---------------------------------------------------------------------------


class ProcessOrderConfig(BaseModel):
    """Configuration for order processing."""

    order_id: str = Field(description="Order identifier")
    amount: float = Field(ge=0, description="Order amount in USD")
    priority: bool = Field(default=False, description="Priority processing flag")


@job(
    extra_description="Process an incoming order and validate payment",
    category="orders",
    tags=["order", "payment"],
    visibility="external",
)
def process_order(config: ProcessOrderConfig, rc: RunContext) -> dict:
    """Process an order — validate, charge, and confirm.

    In production this would integrate with payment providers and
    inventory systems. Here we simulate the happy path.
    """
    rc.log(f"Processing order {config.order_id} (${config.amount:.2f})")

    if config.priority:
        rc.log("Priority processing enabled")

    return {
        "order_id": config.order_id,
        "status": "processed",
        "amount": config.amount,
        "priority": config.priority,
        "confirmation_code": f"CONF-{config.order_id[-4:]}",
    }


# ---------------------------------------------------------------------------
# Job 2: Send Notification
# ---------------------------------------------------------------------------


class NotificationConfig(BaseModel):
    """Configuration for sending notifications."""

    recipient: str = Field(description="Email or user ID")
    message: str = Field(description="Notification message body")
    channel: str = Field(
        default="email", description="Delivery channel: email, sms, push"
    )


@job(
    extra_description="Send a notification to a user via the specified channel",
    category="messaging",
    tags=["notification", "messaging"],
    visibility="external",
)
def send_notification(config: NotificationConfig, rc: RunContext) -> dict:
    """Send a notification through the configured channel."""
    rc.log(f"Sending {config.channel} to {config.recipient}")

    return {
        "recipient": config.recipient,
        "channel": config.channel,
        "status": "sent",
        "message_preview": config.message[:50],
    }
