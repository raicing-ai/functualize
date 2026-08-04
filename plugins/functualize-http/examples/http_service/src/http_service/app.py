"""Application entry point — configures FunctualizeApp with HTTP adapter.

This module wires together job discovery, configuration, and the HTTP
delivery adapter. The same jobs are accessible via both CLI and HTTP.
"""

from pathlib import Path

from functualize_http import HttpAdapter

from functualize.app import FunctualizeApp, JobSources, twelve_factor

JOBS_DIR = str(Path(__file__).parent / "jobs")

# Create the app with twelve-factor config (env vars, no files)
app = FunctualizeApp(
    name="http-service",
    job_sources=JobSources(directories=[JOBS_DIR]),
    config_sources=twelve_factor(dotenv=True),
)


def run_http(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Start the HTTP server."""
    adapter = HttpAdapter()
    adapter(app)
    adapter.run(host=host, port=port)


def run_cli() -> None:
    """Start the CLI interface (same jobs, different delivery)."""
    app.run()


if __name__ == "__main__":
    run_http()
