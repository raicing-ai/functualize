"""`status` — the control.

No ``JOB_GROUP``, no options class, nothing under it. Its rendering in all six
panels must be byte-identical whether or not a `GroupOptions` subclass exists
anywhere in the project. Every change this example exists to exercise is
supposed to be invisible from here.
"""

from functualize.job import RunContext, job


@job
def status(rc: RunContext, verbose: bool = False) -> str:
    """Report deployment status."""
    rc.log("3 services up, 0 degraded" if verbose else "ok")
    return "ok"
