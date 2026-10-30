"""The group rule's other half: no `group=`, so the class name becomes it.

A bare `@job` takes the class name as the group and normalizes it — `Reports`
becomes `reports` — and the module's `JOB_GROUP` stays the namespace above it,
so the job is `data.reports.generate`. Same tree, two levels, and the module's
`JOB_GROUP` is what makes the second one.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel

from functualize.job import job

JOB_GROUP = "data"


@job
class Reports(BaseModel):
    """A second job class, grouped by its own name."""

    JOB_TAGS: ClassVar[tuple[str, ...]] = ("nightly",)

    month: str = "current"

    def generate(self, kind: str = "json") -> None:
        """Render one month's report."""
        print(f"generated {self.month} report as {kind}")
