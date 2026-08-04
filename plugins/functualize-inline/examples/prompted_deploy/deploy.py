"""A job that asks for confirmation and a region via inline widgets.

With functualize-inline installed, `rc.prompt` renders real terminal
widgets; headless runs resolve from defaults.

Run with:
    func deploy.py run
"""

from functualize.job import RunContext


def run(rc: RunContext) -> str:
    """Deploy after an interactive confirmation and region pick."""
    if not rc.prompt_confirm("Deploy to production?", destructive=True, default=False):
        rc.log("Deploy cancelled")
        return "cancelled"

    region = rc.prompt_choice(
        "Which region?",
        ["us-east-1", "eu-west-1", "ap-southeast-1"],
        default="us-east-1",
    )
    rc.log(f"Deploying to {region}...")
    rc.log("Deploy complete")
    return region
