"""Configuration model for the webhook adapter."""

from pydantic import BaseModel, Field


class WebhookConfig(BaseModel):
    """Configuration for webhook delivery."""

    webhook_url: str = Field(description="URL to POST job results to")
    secret: str = Field(default="", description="Shared secret for HMAC signing")
    timeout: int = Field(
        default=10, ge=1, le=60, description="Request timeout in seconds"
    )
    retry_count: int = Field(
        default=3, ge=0, le=10, description="Number of retries on failure"
    )
    include_logs: bool = Field(
        default=False, description="Include job logs in webhook payload"
    )
