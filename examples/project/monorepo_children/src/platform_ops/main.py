"""Entry point for the platform-ops CLI application.

Wires job discovery from a local `jobs/` directory plus two child projects
(auth and billing services) composed under namespace prefixes.
"""

from pathlib import Path

from functualize.app import FunctualizeApp, JobSources, classic

PROJECT_ROOT = Path(__file__).parent.parent.parent
JOBS_DIR = str(Path(__file__).parent / "jobs")

app = FunctualizeApp(
    name="platform-ops",
    job_sources=JobSources(
        directories=[JOBS_DIR],
        children={
            "auth": str(PROJECT_ROOT / "services" / "auth"),
            "billing": str(PROJECT_ROOT / "services" / "billing"),
        },
    ),
    config_sources=classic(),
)


def run() -> None:
    """Console script entry point (`platform-ops` after install)."""
    app.run()


if __name__ == "__main__":
    run()
