"""Config inspector jobs: pre-flight ring, config table, sources, masking.

This module demonstrates the FULL layered config resolution:
  Override → CLI → Env → File → Default

Config sources for the ``release`` job (all provided by the showcase dir):
  - config.base.toml    — baseline values (region, replicas, timeout, api_key)
  - config.dev.toml     — DEV overlay (environment, region, replicas)
  - Env vars            — pass RELEASE_DB_PASSWORD=xxx at launch
  - Defaults            — from Pydantic Field(default=...) below
  - CLI                 — pass values inline: `release --timeout 10`
  - Override            — a value deposited by `config.set()` during the run. The
                          Config Table's `i` key does *not* land here: an edit
                          becomes a CLI token and resolves as `cli`.

Expected resolution for ``release`` (highest wins):
  environment → config.dev.toml ("dev")
  region      → config.dev.toml ("us-west-2"), base had "us-east-1"
  replicas    → config.dev.toml (1), base had 2
  api_key     → config.base.toml ("sk-from-base-config-77777"), rendered masked
                 everywhere because it is declared `Secret[str]`
  db_password → env var if set, else default, and likewise `Secret[str]`
  timeout     → config.base.toml (60), default was 30

Run: RELEASE_DB_PASSWORD=env-secret-pw func (from the showcase directory)
"""

from enum import StrEnum

from pydantic import BaseModel, Field

from functualize.job import RunContext
from functualize.types import Secret


class ReleaseEnvironment(StrEnum):
    """Target environment for a release."""

    dev = "dev"
    staging = "staging"
    production = "production"


class ReleaseConfig(BaseModel):
    """Release config with a mix of field types for config inspector testing.

    Includes two `Secret[str]` fields (api_key, db_password) — declaring the
    field is what makes every surface render it masked — an enum field for value
    completions, and fields fed by different config sources (see the module
    docstring for the expected chain).
    """

    environment: ReleaseEnvironment = Field(
        default=ReleaseEnvironment.production, description="Target environment"
    )
    region: str = Field(default="us-east-1", description="Cloud region")
    replicas: int = Field(default=3, ge=1, le=20, description="Number of replicas")
    api_key: Secret[str] = Field(
        default=Secret("sk-default-key-12345"), description="API secret key"
    )
    db_password: Secret[str] = Field(
        default=Secret("super-secret-pass"), description="Database password"
    )
    timeout: int = Field(default=30, ge=1, le=300, description="Request timeout (s)")


def release(config: ReleaseConfig, rc: RunContext) -> str:
    """Release the application (all optional — bar turns green immediately).

    Tests: pre-flight summary, config table, field detail, override flow.
    """
    rc.log(f"Releasing to {config.environment}/{config.region}")
    rc.log(f"  Replicas: {config.replicas}")
    rc.log(f"  Timeout: {config.timeout}s")
    # A Secret refuses to render. These lines are safe to leave in.
    rc.log(f"  API Key: {config.api_key}")
    rc.log(f"  DB Pass: {config.db_password}")
    return f"Released to {config.environment}/{config.region} x{config.replicas}"


class AnalyzeConfig(BaseModel):
    """Analyze config — fewer fields, for quick diff comparison."""

    depth: int = Field(default=5, ge=1, le=20, description="Analysis depth")
    output_token: Secret[str] = Field(
        default=Secret("tok-abc123"), description="Output API token (sensitive)"
    )
    verbose: bool = Field(default=False, description="Verbose output")


def analyze(config: AnalyzeConfig, rc: RunContext) -> str:
    """Analyze code quality (all optional — bar turns green immediately).

    Tests: masking of a field declared `Secret[str]`.
    """
    rc.log(f"Analyzing with depth={config.depth}, verbose={config.verbose}")
    rc.log(f"Output token: {config.output_token}")
    return f"Analysis complete (depth={config.depth})"


def healthcheck(rc: RunContext) -> str:
    """Simple health check with no config (no pre-flight panel).

    Tests: pre-flight shows "No configuration fields for this job".
    """
    rc.log("All systems operational")
    return "healthy"
