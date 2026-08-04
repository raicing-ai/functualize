"""Deploy jobs — a nested group, so the shell has something to drill into."""

from __future__ import annotations

from functualize.job import job

# `deploy.web` and `deploy.api` become a navigable group in both the CLI and
# the shell: `deploy-tool deploy web` on the command line, and Enter-to-drill
# on the `deploy` row in the shell's job browser.
JOB_GROUP = "deploy"


@job
def web(environment: str = "dev", dry_run: bool = False) -> str:
    """Deploy the web frontend."""
    action = "Would deploy" if dry_run else "Deploying"
    return f"{action} web to {environment}"


@job
def api(environment: str = "dev", replicas: int = 2) -> str:
    """Deploy the API service."""
    return f"Deploying api to {environment} with {replicas} replica(s)"
