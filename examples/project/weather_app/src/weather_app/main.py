"""Entry point for the weather-app CLI application.

Wires job discovery and layered config (classic preset: CLI flags →
env vars → config.base.toml + ENVIRONMENT overlay → model defaults).
The same jobs remain runnable with plain `func` from this directory.
"""

from pathlib import Path

from functualize.app import FunctualizeApp, JobSources, classic

JOBS_DIR = str(Path(__file__).parent / "jobs")

app = FunctualizeApp(
    name="weather-app",
    job_sources=JobSources(directories=[JOBS_DIR]),
    config_sources=classic(),
)


def run() -> None:
    """Console script entry point (`weather-app` after install)."""
    app.run()


if __name__ == "__main__":
    run()
