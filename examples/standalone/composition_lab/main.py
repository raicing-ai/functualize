"""The lab's *second* surface: an app entry point, not the bare `func` CLI.

`func` has a pre-boot dispatch layer — it resolves the command, renders
listings, expands aliases and parses pre-command globals before an app is ever
built. A `FunctualizeApp` entry point has none of that; click owns its tree, and
its job commands are built from cached descriptors on a warm boot rather than
from the live signature.

Those are two different builders over one declaration set, and they have
disagreed: on a config field's default, and on whether `--scope-id` existed at
all. The gated walk in `jobs/release.py` could be blocked from here and then
never resumed, because the flag was a pre-command global of `func` alone.

So the lab ships both surfaces and `tests/test_composition_lab_e2e.py` runs
every claim against each of them. Anything that passes on one and fails on the
other is the finding.

    python main.py lab publish
    python main.py builtin why lab.publish
"""

from functualize.app import FunctualizeApp, JobSources
from functualize.app.adapters import CliAdapter

app = FunctualizeApp("composition-lab", job_sources=JobSources(directories=["jobs"]))
adapter = CliAdapter()


def run() -> None:
    adapter(app)
    adapter.run()


if __name__ == "__main__":
    run()
