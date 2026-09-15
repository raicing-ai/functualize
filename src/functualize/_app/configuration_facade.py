"""Reading what configuration resolved to — `app.configuration`.

Extracted from :class:`~functualize.app.core.FunctualizeApp`
(engine-sealed-construction/T9). Six read-only questions about the resolved
config: which files fed it, which environment is active and how that was
decided, what section a job reads, what a job's config resolves to, and how to
build a model out of a section.

**Not here:** ``resolution_chain``, which is the live chain itself and a member
of the ``EngineHost`` protocol — the engine reads it through the port on every
run. And ``refresh``, which *rebuilds* rather than reads, and is a lifecycle
verb on the app.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize._types.descriptors import ConfigFileInfo
    from functualize._types.enums import EnvironmentSource
    from functualize.app.core import FunctualizeApp

__all__ = ["ConfigurationFacade"]


class ConfigurationFacade:
    """`app.configuration` — read what configuration resolved to."""

    __slots__ = ("_app",)

    def __init__(self, app: FunctualizeApp) -> None:
        self._app = app

    def config_files(self, job_name: str | None = None) -> list[ConfigFileInfo]:
        """Return every config file the kernel discovered, and its role."""
        from functualize._app.impl import config_files

        return config_files(self._app, job_name)

    def active_environment(self) -> str:
        """Return the active environment name (e.g. ``"prod"``).

        Selects which ``config.<slot>.*`` overlay is merged on top of
        ``config.base.*``. See :meth:`environment_source` for whether it was
        chosen explicitly or defaulted.
        """
        return self._app._environment

    def environment_source(self) -> EnvironmentSource:
        """Return where the active environment name came from.

        ``EnvironmentSource.DEFAULT`` means nothing selected it — a
        meaningfully different state to show a user than an explicit choice,
        since it is the usual reason an overlay file "isn't working".
        """
        return self._app._environment_source

    def get_job_config_section(self, job_name: str) -> str:
        """Return the TOML config section name used by the kernel for a job.

        Mirrors the kernel's config_prefix logic: grouped jobs use the group
        path as their section (shared by all jobs in the group); ungrouped
        jobs use the job's own name. This accounts for custom config_prefix
        on grouped jobs where the group may differ from the job name prefix.

        Args:
            job_name: Qualified job name (e.g., "infra.deploy" or "serve").

        Returns:
            The TOML section name (e.g., "infra" for a grouped job, "serve"
            for an ungrouped job).
        """
        descriptor = self._app.get_job(job_name)
        if descriptor is not None and descriptor.group is not None:
            return descriptor.group
        # Ungrouped job or not found — use the job name itself._app.
        # For qualified names not found in the registry, extract bare name.
        if descriptor is not None:
            return descriptor.name
        return job_name

    def resolved_job_config(self, job_name: str) -> Any | None:
        """A job's config model, resolved through the full ladder but not run (T43).

        The public seam for ``func builtin env`` and ``func builtin info --job``:
        both need "what config would this job see?" without executing it, and
        both must agree with each other and with a real run — so they resolve
        through the one path the engine uses, not a re-implementation.

        Returns ``None`` when the job declares no config model. May raise
        ``ValidationError`` if a required field is unresolved (a caller asking
        for the config is better told it is incomplete than given a partial).
        """
        self._app.get_jobs()  # lazy boot: nothing is materialized until asked
        return self._app.execution_engine.resolve_config_model(job_name)

    def resolve_model(self, section: str, model_class: type[object]) -> object:
        """Resolve a configuration model through the Resolution_Chain."""
        from functualize._app.impl import resolve_model

        return resolve_model(self._app, section, model_class)
