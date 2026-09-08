"""13 §2.3 — a downstream app inherits `builtin self` / `builtin plugin` (functualize >= 0.2.0).

Also shows install-mode detection and the refusal path. Read-only: never runs
`self update` or `self install`.
"""
from click.testing import CliRunner
from functualize.app import FunctualizeApp, JobSources
from functualize.app.adapters.cli import CliAdapter
from functualize._cli.runtime import detect_from_process

def hello() -> str:
    """A rise job."""
    return "hi"

app = FunctualizeApp("rise", job_sources=JobSources(directories=[], lazy=False))
app.register_dynamic_job(name="hello", function=hello)
a = CliAdapter(); a(app)
r = CliRunner()

print("top-level commands:", sorted(a.cli_command.commands))
for args in (["builtin","--help"], ["builtin","self","--help"], ["builtin","plugin","--help"],
             ["builtin","self","doctor"]):
    res = r.invoke(a.cli_command, args)
    print(f"\n--- {' '.join(args)}  exit={res.exit_code}")
    print((res.output or "").strip()[:600])

d = detect_from_process()
print("\ndetect(): mode=", d.mode, "| owning_distribution=", d.owning_distribution,
      "| degraded=", d.degraded)
