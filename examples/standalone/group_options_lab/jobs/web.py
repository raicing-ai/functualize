"""`deploy.web.run` — the job that sits under *both* group levels.

`image` is deliberately **positional and required** — marked ``Arg()``, so every
surface agrees it is one rather than inferring it from the missing default. A
grouped invocation puts path segments before the job's own arguments::

    glab deploy --env prod web run v1.2

so anything that binds positionals from the raw token list instead of the
resolved one binds `image="web"` — a path segment — and then reports the
command ready to run. That failure needs a positional field to exist at all,
which is why this one is here and why it has no default. `replicas` is the
named counterpart, so both spellings are exercised by one job.
"""

from typing import Annotated

from _options import DeployOptions, WebOptions

from functualize.job import Arg, RunContext, job

JOB_GROUP = "deploy.web"


@job
def run(
    image: Annotated[str, Arg(help="Image tag to deploy")],
    rc: RunContext,
    replicas: int = 1,
    opts: DeployOptions = None,
    web: WebOptions = None,
) -> str:
    """Deploy the web tier.

    Injects both levels. Neither `opts` nor `web` is settable from the job's
    own flags — the engine fills them from each group's resolved layer — so
    the panels must not offer them as editable rows. What the panels *should*
    offer is the group's own fields, attributed to the group that declared
    them.
    """
    prefix = "Would deploy" if opts.dry_run else "Deploying"
    rc.log(f"image    = {image}")
    rc.log(f"replicas = {replicas}")
    rc.log(f"env      = {opts.env}          (from [deploy])")
    rc.log(f"region   = {web.region}   (from [deploy.web])")
    # A Secret refuses to render. Safe to leave in.
    rc.log(f"token    = {opts.token}")
    return f"{prefix} web {image} x{replicas} to {opts.env}/{web.region}"


@job
def rollback(rc: RunContext, to: str = "previous", opts: DeployOptions = None) -> str:
    """Roll the web tier back. A second job under the same group."""
    rc.log(f"env = {opts.env}")
    return f"Rolling web back to {to} in {opts.env}"
