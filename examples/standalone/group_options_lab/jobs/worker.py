"""`deploy.worker.run` — one level of inheritance, not two.

The contrast with `web.py`: this job sits under `deploy` but not under
`deploy.web`, so `--env` reaches it and `--region` does not. `glab deploy
--region eu-west-1 worker run` fails at the group rather than silently handing
`worker` a flag nothing under it declared.
"""

from _options import DeployOptions

from functualize.job import RunContext, job

JOB_GROUP = "deploy.worker"


@job
def run(rc: RunContext, queue: str = "default", opts: DeployOptions = None) -> str:
    """Deploy a worker."""
    prefix = "Would deploy" if opts.dry_run else "Deploying"
    rc.log(f"queue = {queue}")
    rc.log(f"env   = {opts.env}   (from [deploy] — inherited one level)")
    return f"{prefix} worker on {queue} to {opts.env}"
