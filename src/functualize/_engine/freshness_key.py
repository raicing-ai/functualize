"""The writer and reader derive a fingerprint key from the same inputs.

By the time the pre-flight runs, ``call_kwargs`` holds five different kinds
of thing, and the key must say for each whether it belongs:

  DI-injected capabilities   no — unreconstructable, and ``repr`` carries a
                             memory address, so a job with a ``Log``
                             parameter would get a new key every run
  the resolved config model  yes — hashed as ``config``; a reader re-runs
                             the same chain from a job name
  resolved GroupOptions      yes — on their own. They are *injected*, so the
                             injected-set subtraction drops them, and they
                             resolve against the **group's** config scope,
                             never the job's config model — nothing about
                             ``config`` carries them. A reader rebuilds them
                             with the same resolver, section and option
                             layer the writer's run used
  FromJob upstream values    no — derived from an upstream whose own
                             freshness is separately checked, and circular
                             for a reader to reconstruct
  what the CALLER passed     yes — hashed as ``args``

The "resolved GroupOptions" row is the correction: this derivation used to
claim they were covered "via config resolution", and no code made that true
— a changed option answered with the previous run's record.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from functualize._primitives.fingerprint import compute_args_hash, config_payload

if TYPE_CHECKING:
    from functualize._engine.executor import JobExecutionEngine

logger = logging.getLogger(__name__)


class FreshnessKeys:
    """Hash resolved job config, caller arguments, and resolved group options.

    The executor injects capabilities, config, FromJob values, and group
    options into ``call_kwargs``. Only the group options are an additional
    user-selected input: they are resolved against the group's config scope,
    not the job's config model. A reader with a job name reconstructs them
    through the same resolver used by a run, without prompting.
    """

    def __init__(self, engine: JobExecutionEngine) -> None:
        self._engine = engine

    def for_run(self, context: Any) -> str:
        rc = self._engine._run_context_of(context)
        config = getattr(rc, "job_config", None) if rc is not None else None
        injected = getattr(context, "injected", None) or set()
        explicit = {
            name: value
            for name, value in context.call_kwargs.items()
            if name not in injected
        }
        options = {
            name: config_payload(context.call_kwargs[name])
            for name, _ in self._engine._group_options_params(context.function)
            if name in context.call_kwargs
        }
        return compute_args_hash(config_payload(config), explicit, options)

    def for_job(
        self, job_name: str, group_option_values: dict[str, Any] | None = None
    ) -> str:
        """Reconstruct an engine-triggered run's key without executing it.

        A missing required option cannot match any recorded resolved value:
        ``None`` occupies its slot. Read paths never prompt for it.
        """
        try:
            config = self._engine.resolve_config_model(job_name)
        except Exception as exc:
            logger.debug("config for %r could not be resolved: %s", job_name, exc)
            config = None

        options: dict[str, Any] = {}
        try:
            entry = self._engine.materialize_job(job_name)
            declared = self._engine._group_options_params(entry.function)
        except Exception as exc:
            logger.debug(
                "group options for %r could not be inspected: %s", job_name, exc
            )
            declared = ()
        for name, options_class in declared:
            try:
                resolved = self._engine._build_group_options(
                    options_class, group_option_values
                )
            except Exception as exc:
                logger.debug(
                    "group option %r for %r could not be resolved: %s",
                    name,
                    job_name,
                    exc,
                )
                options[name] = None
            else:
                options[name] = config_payload(resolved)
        return compute_args_hash(config_payload(config), {}, options)
