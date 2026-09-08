"""F7 — a class-only module is never imported by directory discovery."""
import tempfile
from pathlib import Path

from functualize.app import FunctualizeApp, JobSources
from functualize._primitives.pre_filter import ASTModulePreFilter

d = Path(tempfile.mkdtemp()) / "jobs"
d.mkdir(parents=True)
(d / "bifrost.py").write_text(
    '"""A class-only rise module."""\n'
    "class Bifrost:\n"
    '    group = "apps.bifrost"\n'
    "    def start(self) -> None:\n"
    '        """Start it."""\n'
    "    def status(self) -> str:\n"
    '        """Status."""\n'
    '        return "ok"\n'
)
(d / "plain.py").write_text('def hello() -> str:\n    """A plain function job."""\n    return "hi"\n')

app = FunctualizeApp("probe2", job_sources=JobSources(directories=[str(d)], lazy=False))
print("discovered:", [(x.name, x.group) for x in app.get_jobs()])

f = ASTModulePreFilter()
for m in ("bifrost.py", "plain.py"):
    print(f"{m:12} should_import: {f.should_import(d / m)}")
