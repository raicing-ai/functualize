"""13 §2.1 — booleans on a bound method render as `--flag / --no-flag` (functualize >= 0.2.0)."""
from click.testing import CliRunner
from functualize.app import FunctualizeApp, JobSources
from functualize.app.adapters.cli import CliAdapter
from functualize.job import Log

class Tool:
    group = "apps.tool"
    def install(self, log: Log, variant: str = "pip",
                force: bool = False, cache: bool = True) -> None:
        """Install the tool."""
        log(f"variant={variant} force={force} cache={cache}")

inst = Tool()
app = FunctualizeApp("rise", job_sources=JobSources(directories=[], lazy=False))
app.register_dynamic_job(name="apps.tool.install", function=inst.install, group="apps.tool")
a = CliAdapter(); a(app); r = CliRunner()

print("--- install --help")
print(r.invoke(a.cli_command, ["apps","tool","install","--help"]).output.strip())
for args in (["apps","tool","install","--no-cache"], ["apps","tool","install","--force"]):
    res = r.invoke(a.cli_command, args)
    print(f"--- {' '.join(args)} exit={res.exit_code}: {(res.output or '').strip()[:120]}")
