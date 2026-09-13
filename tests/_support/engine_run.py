"""Run a job through the engine's one entry, from a test that holds a function.

``JobExecutionEngine`` used to expose ``execute(job_name, function, ...)``.
run-request-entry/T11 deleted it: the engine resolves the name itself now, so
nothing outside ``_engine/`` holds a job function in order to execute it, and
every surface arrives through ``run(RunRequest(...))``.

Tests are the one place that legitimately has a bare local function and no
registry entry for it — they define ``def my_job(): ...`` three lines above the
call. This helper does what the production doors do: register the entry, then
name it. It is deliberately *not* a shim for the deleted signature — it takes
the request's fields, so a test that wants ``invoke_depth`` or ``force_fresh``
spells them the way every door does.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from functualize._types.descriptors import RegisteredJob
from functualize._types.run_request import RunRequest

if TYPE_CHECKING:
    from collections.abc import Callable

    from functualize._engine.executor import JobExecutionEngine
    from functualize._engine.result import JobResult

__all__ = ["register", "run_job"]


def register(
    engine: JobExecutionEngine,
    name: str,
    function: Callable[..., Any],
    *,
    config_class: type | None = None,
    group: str | None = None,
    module_path: str = "tests",
    job_directory: Any | None = None,
    dependencies: tuple[str, ...] = (),
) -> RegisteredJob:
    """Put ``function`` in the engine's registry under ``name``."""
    entry = RegisteredJob(
        name=name,
        function=function,
        config_class=config_class,
        group=group,
        module_path=module_path,
        job_directory=job_directory,
        dependencies=dependencies,
    )
    engine.register_job(entry)
    return entry


def run_job(
    engine: JobExecutionEngine,
    name: str,
    function: Callable[..., Any],
    *,
    config_class: type | None = None,
    group: str | None = None,
    module_path: str = "tests",
    surface: str = "app.execute",
    **request_fields: Any,
) -> JobResult:
    """Register ``function`` as ``name`` and run it through ``engine.run``.

    ``request_fields`` are :class:`RunRequest` fields — ``kwargs``,
    ``invoke_depth``, ``workflow_scope_id``, ``force``, ``force_fresh``,
    ``run_dependencies``, ``group_option_values``, ``parent_scope``, ``cwd``,
    ``job_directory``.
    """
    register(
        engine,
        name,
        function,
        config_class=config_class,
        group=group,
        module_path=module_path,
        job_directory=request_fields.get("job_directory"),
    )
    return engine.run(
        RunRequest(job_name=name, surface=surface, **request_fields)  # type: ignore[arg-type]
    )
