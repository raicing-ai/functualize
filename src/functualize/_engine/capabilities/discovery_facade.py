"""What a job can ask about *other* jobs — `rc.discovery`.

Extracted from :class:`~functualize._engine.capabilities.runcontext.RunContext`
(engine-sealed-construction/T8). Browsing the registry is a real capability and
a rare one: a launcher, a picker, a job that dispatches to another. It was two
methods on the object every job holds, which is how `RunContext` reached 800
lines — each individually reasonable, none of them the *core* a job reaches for.

The two answers stay deliberately **flat and read-only**: plain dicts and a
descriptor, never a callable or a registry handle, so a UI built on this cannot
reach into the registry or force a lazy job to materialize by asking about it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize._engine.capabilities.runcontext import RunContext

__all__ = ["DiscoveryFacade"]


class DiscoveryFacade:
    """`rc.discovery` — read-only questions about the registered jobs."""

    __slots__ = ("_rc",)

    def __init__(self, rc: RunContext) -> None:
        self._rc = rc

    def get_job_schema(self, job_name: str) -> Any:
        """The descriptor for ``job_name``.

        Raises:
            JobNotFoundError: Nothing is registered under that name.
            RuntimeError: This context was not built by the engine, so there
                is no registry to ask.
        """
        from functualize._engine.errors import JobNotFoundError

        engine = self._rc._execution_engine
        if engine is None:
            raise RuntimeError(
                "Cannot get job schema: RunContext was not created by JobExecutionEngine"
            )
        host = engine.host
        descriptor = host.get_descriptor(job_name) if host is not None else None
        if descriptor is None:
            raise JobNotFoundError(job_name)
        return descriptor

    def list_jobs(self) -> list[dict[str, Any]]:
        """Read-only summaries of every registered job.

        For job-owned UIs that browse jobs (a launcher, a picker) — the
        counterpart to :meth:`get_job_schema` for one job. Returns plain
        dicts, not callables or descriptors, so a UI cannot accidentally
        reach into the registry or force a lazy job to materialize::

            for job in rc.discovery.list_jobs():
                print(job["name"], "—", job["description"])

        Each entry has ``name``, ``group``, ``description`` (the docstring's
        first line), and ``requires_tty``. Returns an empty list outside a
        real execution context.
        """
        engine = self._rc._execution_engine
        if engine is None:
            return []
        host = engine.host
        if host is None:
            return []

        try:
            names = list(host.registered_jobs())
        except Exception:
            return []

        summaries: list[dict[str, Any]] = []
        for name in names:
            if not name:
                continue
            descriptor = host.get_descriptor(name)
            docstring = getattr(descriptor, "docstring", "") or ""
            summaries.append(
                {
                    "name": name,
                    "group": name.rsplit(".", 1)[0] if "." in name else "",
                    "description": docstring.strip().splitlines()[0]
                    if docstring.strip()
                    else "",
                    "requires_tty": bool(getattr(descriptor, "requires_tty", False)),
                }
            )
        return summaries
