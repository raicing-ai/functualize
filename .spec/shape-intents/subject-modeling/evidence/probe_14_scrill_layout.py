"""Probe 14: a job discovered from a skill directory knows where its skill is.

Layout under test (the "scrill" shape):

    pgops/
      SKILL.md
      scripts/jobs.py      <- ordinary functualize job file

Claim: JobDescriptor.source_file is populated for directory-scanned jobs, so
``Path(source_file).parent.parent / "SKILL.md"`` locates the skill with no
manifest, no registry, and no new declaration. Also checks that a
``@job(tags=...)`` declaration survives discovery.

Run:
    cd functualize
    PYTHONPATH=/tmp/fz023/src .venv/bin/python <this file>
"""

import tempfile
from pathlib import Path

from functualize.app import FunctualizeApp, JobSources

ROOT = Path(tempfile.mkdtemp()) / "pgops"
(ROOT / "scripts").mkdir(parents=True)
(ROOT / "SKILL.md").write_text(
    "---\nname: pgops\ndescription: Operate a local postgres.\n---\n# pgops\n"
)
(ROOT / "scripts" / "jobs.py").write_text(
    '"""Postgres operations."""\n'
    "from functualize.job import job\n\n"
    'JOB_GROUP = "pg"\n\n'
    '@job(tags=("scrill:pgops",), extra_description="Judgment lives in the skill.")\n'
    'def backup(to: str = "/tmp") -> None:\n'
    '    """Back up the database."""\n'
)

app = FunctualizeApp(
    "p", job_sources=JobSources(directories=[str(ROOT / "scripts")], lazy=False)
)

for d in app.get_jobs():
    print(d.name, "| group:", d.group)
    print("  source_file:", d.source_file)
    print("  declaration.tags:", d.declaration.tags if d.declaration else None)
    sidecar = Path(d.source_file).parent.parent / "SKILL.md"
    print("  derived skill path:", sidecar)
    print("  skill exists:", sidecar.is_file())
