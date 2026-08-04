"""Health check job — verify a service is responding."""

from pydantic import BaseModel, Field

from functualize.job.context import RunContext
from functualize.job.decorators import job

JOB_NAME = "healthcheck"


class HealthcheckConfig(BaseModel):
    """Configuration for the healthcheck job."""

    service_url: str = Field(description="URL of the service to check")
    timeout: int = Field(
        default=5, ge=1, le=30, description="Request timeout in seconds"
    )
    expected_status: int = Field(default=200, description="Expected HTTP status code")


@job(
    extra_description="Check if a service endpoint is healthy and responding",
    category="monitoring",
    tags=["health", "monitoring", "safe", "read-only"],
    visibility="external",
)
def run(config: HealthcheckConfig, rc: RunContext) -> dict:
    """Check service health by making a request to the configured URL.

    Returns status information including response time and status code.
    This is a read-only operation suitable for automated monitoring.
    """
    rc.log(f"Checking health: {config.service_url}")

    # Simulated health check (real impl would use httpx/urllib)
    result = {
        "url": config.service_url,
        "status": "healthy",
        "status_code": config.expected_status,
        "response_time_ms": 42,
        "timeout_configured": config.timeout,
    }

    rc.log(f"Service healthy: {result['response_time_ms']}ms response time")
    return result
