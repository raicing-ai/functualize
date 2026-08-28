"""`glab` — an app whose whole point is that flags live at the *group*.

Every other example declares flags on a job. This one declares them on the
path between the root and the job::

    glab deploy --env prod web --region eu-west-1 run --image v1.2

`--env` belongs to `deploy`, `--region` to `deploy.web`, `--image` to the job
itself, and all three arrive in one invocation. The job never declares `env` or
`region`; it receives them by asking for the options class.

Run it with ``uv run glab``, or with no arguments at a TTY to open the shell —
which is where the panels this example exists to exercise actually render.
"""

from __future__ import annotations

from functualize.app import FunctualizeApp, JobSources
from functualize.app.adapters import CliAdapter

APP_NAME = "glab"


def build_app() -> FunctualizeApp:
    """Construct the app.

    Deliberately minimal: no custom settings identity, no generated root
    flags. `deploy_tool` is the example for those. Everything interesting here
    comes from the two `GroupOptions` subclasses in ``jobs/_options.py``, which
    discovery finds by scanning the same directory it scans for jobs.
    """
    return FunctualizeApp(
        name=APP_NAME,
        job_sources=JobSources(directories=["jobs"], lazy=True),
    )


def main() -> None:
    """Entry point."""
    app = build_app()
    adapter = CliAdapter()
    adapter(app)
    adapter.run()


if __name__ == "__main__":
    main()
