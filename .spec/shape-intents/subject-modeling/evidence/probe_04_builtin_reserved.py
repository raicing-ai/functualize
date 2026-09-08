"""F5 — claiming the `builtin` namespace is a hard boot error."""
from functualize.app import FunctualizeApp, JobSources
from functualize.app.adapters.cli import CliAdapter


def diagnose() -> str:
    """Tree-wide diagnose."""
    return "ok"


app = FunctualizeApp("rise", job_sources=JobSources(directories=[], lazy=False))
app.register_dynamic_job(name="builtin.diagnose", function=diagnose, group="builtin")

try:
    CliAdapter()(app)
    print("adapter wired OK (unexpected)")
except ValueError as e:
    print("adapter raised ValueError:")
    print("  ", e)

# The same job under a non-reserved top-level name wires fine.
app2 = FunctualizeApp("rise", job_sources=JobSources(directories=[], lazy=False))
app2.register_dynamic_job(name="diagnose", function=diagnose)
a2 = CliAdapter()
a2(app2)
print("top-level `rise diagnose` wired OK:", "diagnose" in a2.cli_command.commands)
