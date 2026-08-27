"""Declaring a credential: mark the field, not the name.

Two spellings, one meaning. `Secret[str]` is the one to reach for; the
`json_schema_extra` marker is for a field that must stay a plain `str` for some
other reason. Everything that renders configuration asks the same question of
both, so they mask identically.
"""

from pydantic import BaseModel, Field

from functualize.job import RunContext
from functualize.job.decorators import job
from functualize.types import Secret


class SyncConfig(BaseModel):
    api_url: str = Field(default="https://api.example.com", description="API base URL")

    credential: Secret[str] = Field(
        default=Secret(""), description="API token — the declared way"
    )

    legacy_token: str = Field(
        default="",
        description="Same treatment, for a field that must stay a plain str",
        json_schema_extra={"secret": True},
    )

    # Matches every name-based 'is this a secret' heuristic ever written, and is
    # not a secret. Detection follows the model, so this renders normally.
    sort_key: str = Field(default="created_at", description="Not a secret")

    page_size: int = Field(default=50, description="Rows per request")


@job(extra_description="Sync with the remote API")
def sync(config: SyncConfig, rc: RunContext) -> str:
    """Print what resolved. The credential cannot be printed by accident."""
    rc.log(f"api_url    = {config.api_url}")
    rc.log(f"sort_key   = {config.sort_key}")
    rc.log(f"page_size  = {config.page_size}")

    # A Secret refuses to render. This line is safe to leave in.
    rc.log(f"credential = {config.credential}")

    # The real value takes a deliberate call, and only where it is needed.
    return f"sent {config.page_size} rows to {config.api_url}"
