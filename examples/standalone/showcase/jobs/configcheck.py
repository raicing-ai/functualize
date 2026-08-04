"""Config inspector jobs: pre-flight ring, config table, sources, masking.

This module demonstrates the FULL layered config resolution:
  CLI → Session → Env → File → Default

Config sources for the ``release`` job (all provided by the showcase dir):
  - config.base.toml    — baseline values (region, replicas, timeout, api_key)
  - config.dev.toml     — DEV overlay (environment, region, replicas)
  - Env vars            — pass RELEASE_DB_PASSWORD=xxx at launch
  - Defaults            — from Pydantic Field(default=...) below
  - CLI                 — pass values inline: `release --timeout 10`
  - Session             — edit values via the Config Table `i` key

Expected resolution for ``release`` (highest wins):
  environment → config.dev.toml ("dev")
  region      → config.dev.toml ("us-west-2"), base had "us-east-1"
  replicas    → config.dev.toml (1), base had 2
  api_key     → config.base.toml ("sk-from-base-config-77777"), masked in the UI
  db_password → env var if set, else default ("super-secret-pass")
  timeout     → config.base.toml (60), default was 30

Run: RELEASE_DB_PASSWORD=env-secret-pw func (from the showcase directory)
"""

from enum import StrEnum

from pydantic import BaseModel, Field

from functualize.job import RunContext


class ReleaseEnvironment(StrEnum):
    """Target environment for a release."""

    dev = "dev"
    staging = "staging"
    production = "production"


class ReleaseConfig(BaseModel):
    """Release config with a mix of field types for config inspector testing.

    Includes sensitive fields (api_key, db_password) that should be masked,
    an enum field for value completions, and fields fed by different config
    sources (see the module docstring for the expected chain).
    """

    environment: ReleaseEnvironment = Field(
        default=ReleaseEnvironment.production, description="Target environment"
    )
    region: str = Field(default="us-east-1", description="Cloud region")
    replicas: int = Field(default=3, ge=1, le=20, description="Number of replicas")
    api_key: str = Field(default="sk-default-key-12345", description="API secret key")
    db_password: str = Field(
        default="super-secret-pass", description="Database password"
    )
    timeout: int = Field(default=30, ge=1, le=300, description="Request timeout (s)")


def release(config: ReleaseConfig, rc: RunContext) -> str:
    """Release the application (all optional — bar turns green immediately).

    Tests: pre-flight summary, config table, field detail, override flow.
    """
    rc.log(f"Releasing to {config.environment}/{config.region}")
    rc.log(f"  Replicas: {config.replicas}")
    rc.log(f"  Timeout: {config.timeout}s")
    rc.log(f"  API Key: {'*' * 8} (masked)")
    rc.log(f"  DB Pass: {'*' * 8} (masked)")
    return f"Released to {config.environment}/{config.region} x{config.replicas}"


class AnalyzeConfig(BaseModel):
    """Analyze config — fewer fields, for quick diff comparison."""

    depth: int = Field(default=5, ge=1, le=20, description="Analysis depth")
    output_token: str = Field(
        default="tok-abc123", description="Output API token (sensitive)"
    )
    verbose: bool = Field(default=False, description="Verbose output")


def analyze(config: AnalyzeConfig, rc: RunContext) -> str:
    """Analyze code quality (all optional — bar turns green immediately).

    Tests: sensitive field masking for the "token" keyword.
    """
    rc.log(f"Analyzing with depth={config.depth}, verbose={config.verbose}")
    rc.log(f"Output token: {'*' * 8} (masked)")
    return f"Analysis complete (depth={config.depth})"


def healthcheck(rc: RunContext) -> str:
    """Simple health check with no config (no pre-flight panel).

    Tests: pre-flight shows "No configuration fields for this job".
    """
    rc.log("All systems operational")
    return "healthy"
