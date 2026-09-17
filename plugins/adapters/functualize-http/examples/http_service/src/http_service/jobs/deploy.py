"""Deploy job — deploy application artifacts to an environment."""

from enum import StrEnum

from pydantic import BaseModel, Field

from functualize.job.context import RunContext
from functualize.job.decorators import job

JOB_NAME = "deploy"


class Environment(StrEnum):
    """Target deployment environment."""

    staging = "staging"
    production = "production"


class DeployConfig(BaseModel):
    """Configuration for the deploy job."""

    version: str = Field(description="Version tag to deploy (e.g., v1.2.3)")
    environment: Environment = Field(
        default=Environment.staging, description="Target environment"
    )
    dry_run: bool = Field(default=False, description="Preview without applying changes")


@job(
    extra_description="Deploy application artifacts to staging or production",
    category="deployment",
    tags=["deploy", "infrastructure"],
    examples=["deploy --version v1.2.3 --environment production"],
    visibility="external",
)
def run(config: DeployConfig, rc: RunContext) -> dict:
    """Deploy the application to the specified environment.

    Builds a container image, pushes to the registry, and updates
    the target environment's deployment manifest.
    """
    rc.log(f"Deploying {config.version} to {config.environment.value}")

    if config.dry_run:
        rc.log("DRY RUN — no changes applied")
        return {
            "version": config.version,
            "environment": config.environment.value,
            "status": "dry_run",
            "changes_applied": False,
        }

    # Simulated deployment steps
    rc.log("Building container image...")
    rc.log("Pushing to registry...")
    rc.log("Updating deployment manifest...")

    return {
        "version": config.version,
        "environment": config.environment.value,
        "status": "deployed",
        "changes_applied": True,
    }
