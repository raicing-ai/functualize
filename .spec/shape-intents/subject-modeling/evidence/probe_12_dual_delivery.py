"""04 — one plugin object, two deliveries.

  * own CLI      : rise is the root app; groups mount at root.
  * guest in func: the same plugin mounts under a namespace.

The namespace must be composed into the GROUP, not applied with
NamespaceTransform: that transform prefixes the descriptor's *name* only, so
name and group disagree and the CLI trie still files the job under its
un-prefixed group (shown below as the `transform` row).
"""

from click.testing import CliRunner

from functualize._discovery.providers import Job, StaticProvider
from functualize._discovery.transforms import NamespaceTransform
from functualize.app import FunctualizeApp, JobSources, PluginSources
from functualize.app.adapters.cli import CliAdapter
from functualize.job import Log


class Bifrost:
    group = "apps.bifrost"

    def start(self, log: Log) -> None:
        """Start bifrost."""
        log("started")


class RisePlugin:
    name = "rise"
    version = "0.1.0"
    description = "rise"

    def __init__(self, namespace=None, use_transform=False):
        self.namespace, self.use_transform = namespace, use_transform

    def __call__(self, app) -> None:
        inst = Bifrost()
        if self.namespace and not self.use_transform:
            grp = f"{self.namespace}.{inst.group}"
        else:
            grp = inst.group
        provider = StaticProvider(
            [Job(function=inst.start, name=f"{grp}.start", group=grp)]
        )
        transforms = (
            [NamespaceTransform(self.namespace)]
            if (self.namespace and self.use_transform)
            else None
        )
        app.add_job_provider(provider, transforms)


cases = [
    ("own CLI (root)", None, False, ["apps", "bifrost", "start"]),
    ("guest, group-composed", "rise", False, ["rise", "apps", "bifrost", "start"]),
    ("guest, NamespaceTransform", "rise", True, ["rise", "apps", "bifrost", "start"]),
]
for label, ns, xf, path in cases:
    app = FunctualizeApp(
        "host",
        job_sources=JobSources(directories=[], lazy=False),
        plugin_sources=PluginSources(
            entry_point_group="", explicit_plugins=[RisePlugin(ns, xf)]
        ),
    )
    a = CliAdapter()
    a(app)
    res = CliRunner().invoke(a.cli_command, path)
    print(
        f"{label:28} top={sorted(a.cli_command.commands)}  "
        f"`{' '.join(path)}` -> exit={res.exit_code}"
    )
