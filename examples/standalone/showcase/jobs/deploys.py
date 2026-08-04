"""Deploy family: autocomplete prefixes, enum value completions, modal, paths.

What each job exercises in the inline TUI:

- ``deploy`` / ``deploy_rollback`` / ``deploy_status`` — shared prefix, so
  typing "deploy" shows three candidates (autocomplete testing).
- ``deploy`` has 5 required fields → Ctrl+R opens the full config modal.
  Its enum fields (env, region, protocol) drive value completions: type
  "deploy --env " (trailing space) to see dev/staging/production/canary.
- ``build`` has path-like string fields (source_dir, output_dir, …) for
  filesystem suggestions.
- ``inspect`` has LogLevel/Format enums plus a bool for mixed value
  completions ("inspect --level ", "inspect --format ").

Run: func (from the showcase directory)
"""

from enum import StrEnum

from pydantic import BaseModel, Field

from functualize.job import RunContext

# ─── Shared enums ────────────────────────────────────────────────────────


class Environment(StrEnum):
    """Deployment environments."""

    dev = "dev"
    staging = "staging"
    production = "production"
    canary = "canary"


class Region(StrEnum):
    """Cloud regions."""

    us_east_1 = "us-east-1"
    us_west_2 = "us-west-2"
    eu_west_1 = "eu-west-1"
    ap_southeast_1 = "ap-southeast-1"


class Protocol(StrEnum):
    """Network protocols."""

    http = "http"
    grpc = "grpc"
    websocket = "websocket"


class LogLevel(StrEnum):
    """Log levels."""

    debug = "debug"
    info = "info"
    warning = "warning"
    error = "error"
    critical = "critical"


class Format(StrEnum):
    """Output formats."""

    json = "json"
    text = "text"
    table = "table"
    csv = "csv"


# ─── deploy family: shared prefix for autocomplete testing ───────────────


class DeployConfig(BaseModel):
    """Deploy config — 5 required fields → full config modal."""

    service: str = Field(description="Service name to deploy")
    version: str = Field(description="Version tag (e.g., v1.2.3)")
    env: Environment = Field(description="Target environment")
    region: Region = Field(description="Cloud region")
    protocol: Protocol = Field(description="Network protocol")
    replicas: int = Field(default=2, ge=1, le=20, description="Number of replicas")
    health_path: str = Field(default="/health", description="Health check endpoint")
    timeout: int = Field(default=300, ge=30, le=3600, description="Deploy timeout (s)")


def deploy(config: DeployConfig, rc: RunContext) -> str:
    """Deploy a service (5 required fields → full modal; enums → completions)."""
    rc.log(f"Deploying {config.service}@{config.version}")
    rc.log(f"  Environment: {config.env}")
    rc.log(f"  Region: {config.region}")
    rc.log(f"  Protocol: {config.protocol}")
    rc.log(f"  Replicas: {config.replicas}")
    rc.log(f"  Health: {config.health_path}")
    rc.log(f"  Timeout: {config.timeout}s")
    return f"Deployed {config.service}@{config.version} to {config.env}/{config.region}"


class DeployRollbackConfig(BaseModel):
    """Rollback a deployment."""

    service: str = Field(description="Service name to rollback")
    env: Environment = Field(description="Target environment")
    to_version: str = Field(description="Version to rollback to")


def deploy_rollback(config: DeployRollbackConfig, rc: RunContext) -> str:
    """Rollback a deployment to a previous version."""
    rc.log(f"Rolling back {config.service} in {config.env} to {config.to_version}")
    return f"Rolled back {config.service} to {config.to_version}"


class DeployStatusConfig(BaseModel):
    """Check deploy status."""

    service: str = Field(description="Service name to check")
    env: Environment = Field(default=Environment.production, description="Environment")


def deploy_status(config: DeployStatusConfig, rc: RunContext) -> str:
    """Check the status of a deployed service."""
    rc.log(f"Checking {config.service} in {config.env}...")
    rc.log("  Status: healthy")
    rc.log("  Uptime: 3d 14h")
    return f"{config.service} ({config.env}): healthy"


# ─── Path-like fields (filesystem suggestions) ───────────────────────────


class BuildConfig(BaseModel):
    """Build configuration with path-like string parameters."""

    source_dir: str = Field(description="Source directory to build from")
    output_dir: str = Field(
        default="./dist",
        description="Output directory for build artifacts",
    )
    config_file: str = Field(
        default="./build.yaml",
        description="Build configuration file",
    )
    cache_dir: str = Field(
        default="./.cache",
        description="Build cache directory",
    )


def build(config: BuildConfig, rc: RunContext) -> str:
    """Build the project from source (tests path-like string fields)."""
    rc.log(f"Building from {config.source_dir}")
    rc.log(f"  Output: {config.output_dir}")
    rc.log(f"  Config: {config.config_file}")
    rc.log(f"  Cache: {config.cache_dir}")
    return f"Built from {config.source_dir} → {config.output_dir}"


# ─── Mixed enums + bool (value completions) ──────────────────────────────


class InspectConfig(BaseModel):
    """Inspect configuration — tests value completions from choices."""

    target: str = Field(description="Resource to inspect")
    level: LogLevel = Field(default=LogLevel.info, description="Log level filter")
    format: Format = Field(default=Format.table, description="Output format")
    verbose: bool = Field(default=False, description="Verbose output")


def inspect(config: InspectConfig, rc: RunContext) -> str:
    """Inspect a resource with filtering (tests value completions)."""
    rc.log(f"Inspecting: {config.target}")
    rc.log(f"  Level: {config.level}")
    rc.log(f"  Format: {config.format}")
    rc.log(f"  Verbose: {config.verbose}")
    return f"Inspected {config.target}"
