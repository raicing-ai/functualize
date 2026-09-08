"""F2 — the interactivity signal and the exact off-terminal prompt semantics."""
from click.testing import CliRunner

from functualize.app import FunctualizeApp, JobSources
from functualize.app.adapters.cli import CliAdapter
from functualize.job import TTY, RunContext


def host_guard_probe(rc: RunContext, tty: TTY | None = None) -> None:
    """Host-guard probe."""
    print("rc has is_interactive attribute:", hasattr(rc, "is_interactive"))
    print("tty is None (i.e. non-interactive):", tty is None)
    print("prompt_confirm(default=False) ->", rc.prompt_confirm("proceed?", default=False))
    print("prompt_confirm(default=True)  ->", rc.prompt_confirm("proceed?", default=True))
    try:
        rc.prompt_confirm("required?")
        print("prompt_confirm(no default)    -> returned (unexpected)")
    except Exception as e:
        print("prompt_confirm(no default)    ->", type(e).__name__)


app = FunctualizeApp("rise", job_sources=JobSources(directories=[], lazy=False))
app.register_dynamic_job(name="host-guard-probe", function=host_guard_probe)
adapter = CliAdapter()
adapter(app)
res = CliRunner().invoke(adapter.cli_command, ["host-guard-probe"])
print(res.output.strip())
print("exit:", res.exit_code)
