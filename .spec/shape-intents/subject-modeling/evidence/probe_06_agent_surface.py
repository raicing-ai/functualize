"""F10 — register_dynamic_job records no parameters; the three-line patch restores them."""
import json

from click.testing import CliRunner

import functualize._app.impl as impl
from functualize.app import FunctualizeApp, JobSources
from functualize.app.adapters.cli import CliAdapter
from functualize._discovery.providers import extract_parameters_from_signature
from functualize.job import Log


class Tool:
    group = "apps.tool"

    def install(self, log: Log, variant: str = "pip", force: bool = False) -> None:
        """Install the tool."""
        log(f"install {variant} force={force}")


inst = Tool()


def build(patched: bool):
    app = FunctualizeApp("rise", job_sources=JobSources(directories=[], lazy=False))
    app.register_dynamic_job(name="apps.tool.install", function=inst.install, group="apps.tool")
    if patched:
        # THE PATCH, in effect: _app/impl.py:732 `parameters=[]` →
        #                      `parameters=extract_parameters_from_signature(function)`
        import dataclasses

        descs = app.job_registry._job_descriptors
        descs[-1] = dataclasses.replace(
            descs[-1], parameters=extract_parameters_from_signature(inst.install)
        )
    a = CliAdapter()
    a(app)
    return a


for label, patched in (("UNPATCHED", False), ("PATCHED", True)):
    a = build(patched)
    out = CliRunner().invoke(a.cli_command, ["builtin", "info", "schema", "apps.tool.install"]).output
    props = json.loads(out).get("inputSchema", {}).get("properties", {})
    print(f"{label:10} info schema properties: {sorted(props)}")
    cli = CliRunner().invoke(a.cli_command, ["apps", "tool", "install", "--help"]).output
    print(f"{label:10} CLI accepts --variant:  {'--variant' in cli}")
