"""Auth service jobs — discovered by the parent and namespaced as "auth.*".

These appear in the CLI as:
  platform-ops auth.login
  platform-ops auth.rotate-keys
"""

from pydantic import BaseModel, Field

from functualize.job.context import RunContext
from functualize.job.decorators import job


class AuthConfig(BaseModel):
    """Configuration for auth jobs."""

    provider: str = Field(default="internal", description="Auth provider name")
    token_ttl_hours: int = Field(default=24, description="Token TTL in hours")


@job(
    extra_description="Simulate a user login flow",
    category="auth",
    tags=["safe"],
)
def login(config: AuthConfig, rc: RunContext) -> str:
    """Simulate the login flow for testing."""
    rc.log(f"Authenticating via {config.provider}...")
    rc.log(f"Token issued (TTL: {config.token_ttl_hours}h)")
    return "login_success"


@job(
    extra_description="Rotate authentication keys",
    category="auth",
    tags=["destructive"],
)
def rotate_keys(config: AuthConfig, rc: RunContext) -> str:
    """Rotate the auth provider's signing keys."""
    rc.log(f"Rotating keys for provider: {config.provider}...")
    rc.log("Old keys revoked, new keys active")
    return "keys_rotated"
