"""A *required* credential — the case an operator most needs to see coming.

`token` has no default, so nothing but you can supply it. Before this lab's
work, every surface rendered it as `••• model default`, which reads as
"configured". It now reads as missing, and names the variable that sets it.
"""

from pydantic import BaseModel, Field

from functualize.job import RunContext
from functualize.job.decorators import job
from functualize.types import Secret


class ReportConfig(BaseModel):
    output_dir: str = Field(default="./out", description="Where to write")
    token: Secret[str] = Field(description="Required. No default.")


@job(extra_description="Generate a report (requires a token)")
def report(config: ReportConfig, rc: RunContext) -> str:
    """Generate a report. Needs REPORT_TOKEN."""
    rc.log(f"output_dir = {config.output_dir}")
    rc.log(f"token      = {config.token}")
    return f"report written to {config.output_dir}"
