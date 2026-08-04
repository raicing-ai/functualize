"""Public application construction API.

This package provides the entry points for constructing and configuring
a FunctualizeApp instance, including preset factory functions for common
deployment strategies and grouped configuration objects.

Usage:
    from functualize.app import FunctualizeApp, JobSources, ConfigSources
    from functualize.app import classic, twelve_factor

    app = FunctualizeApp(
        "myapp",
        job_sources=JobSources(directories=["./jobs"]),
        config_sources=twelve_factor(dotenv=True),
    )
"""

from functualize._events.perf import PerfTimeline
from functualize._events.perf import perf_timeline as _perf_timeline
from functualize.app.config import (
    ConfigSources,
    DiscoveryConfig,
    ExecutionConfig,
    JobSources,
    PluginSources,
)
from functualize.app.core import FunctualizeApp
from functualize.app.fallback import FallbackCommand
from functualize.app.presets import classic, env_only, remote_first, twelve_factor


def get_perf_timeline() -> PerfTimeline:
    """Return the global performance timeline singleton.

    This provides public access to the framework-level PerfTimeline instance
    that records startup and runtime performance marks. The timeline exists
    as a module-level singleton before any FunctualizeApp is constructed,
    making it suitable for pre-boot instrumentation in the CLI layer.

    Returns:
        The global PerfTimeline instance.
    """
    return _perf_timeline


__all__ = [
    "FunctualizeApp",
    "FallbackCommand",
    "DiscoveryConfig",
    "JobSources",
    "ConfigSources",
    "PluginSources",
    "ExecutionConfig",
    "classic",
    "twelve_factor",
    "env_only",
    "remote_first",
    "get_perf_timeline",
]
