"""13 §2.3 — a downstream app inherits `builtin self` / `builtin plugin` (functualize >= 0.2.0).

Also shows install-mode detection and the refusal path. Read-only: never runs
`self update` or `self install`.
"""
from click.testing import CliRunner
from functualize.app import FunctualizeApp, JobSources
from functualize.app.adapters.cli import CliAdapter

# Was `functualize._cli.runtime` — a private path — when this probe was written
# against 0.2.3 (`a2f453d`). Upstream ask 4 (`13` §4) asked for install
# detection to become importable, and it landed: the module no longer exists and
# `detect_from_process` is public in `functualize.app.packaging.__all__`. That
# this import now works *is* the ask's acceptance test.
from functualize.app.packaging import detect_from_process

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
