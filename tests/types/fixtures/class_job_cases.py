"""A class job method fixture for `tests/types/test_class_job.py`.

Not a test module: the suite builds a `ClassJobMethod` around `ExampleJob.run`
and inspects the proxy. Nothing here is executed — `run` bodies are `...`.

`from __future__ import annotations` is the point (plan.md §4.4): every
annotation is a PEP 563 string, so the proxy's `__signature__` only shows live
types because it resolves them through `resolved_hints`. The `Annotated[int,
Field(ge=0)]` parameter proves `include_extras=True` keeps `Field()` metadata.

`unresolvable` is annotated `Missing_` — a name this module never defines
(`# noqa: F821` is the repo idiom for that, cf.
`tests/discovery/test_capability_markers.py`). `resolved_hints` falls back to
`{}` on that unimportable reference (its documented contract), which is what
pins `resolved_hints(proxy) == {}` on the proxy that wraps it.

Markers are attached to the *functions*: `ClassJobMethod.__getattr__` delegates
to the underlying function, so that is where a workflow declaration, a surface
hint and a lazy flag have to live to exercise delegation.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from functualize._types.job_declaration import JobDeclaration


class ExampleJob:
    """A class carrying the method the proxy wraps."""

    def run(self, count: Annotated[int, Field(ge=0)], label: str = "x") -> int: ...

    def unresolvable(self, value: Missing_) -> None: ...  # noqa: F821


class MarkeredJob:
    """A class whose method carries the markers delegation must serve."""

    def run(self, count: int = 0) -> None: ...


def merged_declaration() -> JobDeclaration:
    """A declaration distinct from anything the methods carry, to prove identity."""
    return JobDeclaration(tags=("merged",))


# Function-attached markers — the shape `workflow/_decorator.py` and the
# `functualize.job` decorators produce.
MarkeredJob.run.__functualize_workflow__ = "workflow-marker"  # type: ignore[attr-defined]
MarkeredJob.run.__functualize_surface_hint__ = "stdout"  # type: ignore[attr-defined]
MarkeredJob.run.__functualize_lazy__ = True  # type: ignore[attr-defined]
