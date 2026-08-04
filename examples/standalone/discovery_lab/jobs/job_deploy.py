"""Deployment jobs — passes prefix ("job_"), import, and decorator filters.

- Filename starts with ``job_``      → passes require_file_prefix = "job_"
- Imports functualize                → passes require_file_import = "functualize"
- ``deploy`` is decorated            → passes require_job_decorators, which is
  function-level: undecorated ``rollback`` shares the file but is NOT
  registered under that filter (file-level filters take both)
"""

from functualize.job.decorators import job


@job(extra_description="Deploy the application")
def deploy(target: str = "staging") -> str:
    """Deploy the application to the specified environment."""
    print(msg := f"Deployed to {target}")
    return msg


def rollback(version: str = "previous") -> str:
    """Rollback to a previous deployment version (undecorated on purpose)."""
    print(msg := f"Rolled back to {version}")
    return msg
