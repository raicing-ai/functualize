"""A job class: one class, one configuration section, one job per method.

`Database` carries no `@job` of its own, so it is not a job class — the opt-in
is read from each class's own definition, never through a base. Its fields
still arrive on the concrete class, and its `JOB_TAGS` still contributes to
every method job below: the method's own tags first, then the class's, then
`JOB_TAGS` outward along the MRO.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel

from functualize.job import job


class Database(BaseModel):
    """Shared fields and tags for the concrete cluster classes."""

    JOB_TAGS: ClassVar[tuple[str, ...]] = ("database",)

    host: str = "localhost"
    port: int = 5432


@job(group="pg", tags=["class-tag"])
class Postgres(Database):
    """Three methods, so three jobs: pg.start, pg.stop and pg.backup.

    start is the one that collides: jobs/legacy.py declares a function with the
    same canonical name, and a class-derived claimant makes the collision
    strict, so neither definition runs.
    """

    def start(self) -> None:
        """Never runs: the collision takes this name out of the CLI."""
        print(f"class start ran on {self.host}")

    def stop(self, force: bool = False) -> None:
        """Stop the cluster."""
        print(f"stopped {self.host}:{self.port} (force={force})")

    @job(tags=["method-tag"])
    def backup(self, target: str = "s3://backups") -> None:
        """Back the cluster up."""
        print(f"backed up {self.host}:{self.port} to {target}")
