"""15 §1 - a job whose import fails does not error; it vanishes from the CLI."""
import logging
import sys
import tempfile
from pathlib import Path

from functualize.app import FunctualizeApp, JobSources

d = Path(tempfile.mkdtemp()) / "jobs"
d.mkdir(parents=True)
(d / "needs_dep.py").write_text(
    "import nonexistent_package_xyz  # a dependency nobody installed\n\n"
    "def fetch() -> str:\n"
    '    """Fetch something."""\n'
    "    return nonexistent_package_xyz.go()\n"
)
(d / "ok.py").write_text('def hello() -> str:\n    """Works fine."""\n    return "hi"\n')

logging.basicConfig(level=logging.WARNING, stream=sys.stdout)
app = FunctualizeApp("dp", job_sources=JobSources(directories=[str(d)], lazy=False))
print("discovered:", [j.name for j in app.get_jobs()])
print("`fetch` is present:", any(j.name == "fetch" for j in app.get_jobs()))
