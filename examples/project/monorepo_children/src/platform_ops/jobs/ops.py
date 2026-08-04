"""Platform-level operations — shared jobs owned by the parent project.

These run without a namespace prefix: `platform-ops health-check`, `platform-ops report`.
"""

from functualize.job.context import RunContext
from functualize.job.decorators import job
from functualize.types import RunStatus


@job(
    extra_description="Check health of all platform services",
    category="ops",
    tags=["safe", "read-only"],
)
def health_check(rc: RunContext) -> str:
    """Run health checks across all services."""
    rc.log("Checking platform health...")

    services = ["auth", "billing"]
    results = []
    for svc in services:
        rc.track_phase(f"check-{svc}", f"Checking {svc}", RunStatus.RUNNING)
        rc.log(f"  {svc}: healthy ✓")
        rc.track_phase(f"check-{svc}", f"{svc} OK", RunStatus.SUCCESS)
        results.append(f"{svc}=ok")

    summary = ", ".join(results)
    rc.log(f"All services healthy: {summary}")
    return summary


@job(
    extra_description="Generate a cross-service platform report",
    category="ops",
    tags=["safe", "read-only"],
)
def report(rc: RunContext) -> str:
    """Generate a summary report across all child services."""
    rc.log("Generating platform report...")
    rc.log("  Auth: 1,234 logins today")
    rc.log("  Billing: 56 invoices processed")
    rc.log("Report complete.")
    return "report_generated"
