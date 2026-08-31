"""Real-app fixtures for the TUI's group-options behaviour.

Two projects, and the difference between them is the point.

``glab_tui`` boots the **shipped example**, `examples/standalone/group_options_lab/`,
by copying its `jobs/` directory into an XDG-isolated tmp_path. The declarations
are the real ones — including the ``Secret[str]`` group option — because a test
that proves masking from a stub proves only that the formatter masks when told
to, not that anything tells it (`contributor/guides/wiring-discipline.md` §8).

``flag_shapes_tui`` boots a project built around the *shapes* click renders
differently — a bool with a short flag (no ``--no-`` pair), a plain bool (which
has one), a required positional (a ``click.Argument``, with no flag spelling at
all). The readiness check's notion of "a flag this job accepts" has to agree
with the click param builder for every one of them, and the shipped example
contains only some of the shapes.

``ungrouped_tui`` boots the same example with the ``GroupOptions``
declarations *removed*, so any behaviour gated on ``trie is not None`` can be
asserted on both sides of that gate rather than only the armed one.

``collision_tui`` boots a project the example deliberately does *not* contain:
the same field name declared twice — ``tier`` at both group levels, and
``region`` at the deeper group *and* on the job. The round-trip's "a flat
values dict is enough" conclusion rests on a design docstring
(``_engine/executor.py``), not on a reproduction; and a name shared between a
group and its job is what makes "whose flag is this?" observable at all. This
fixture is what turns both into enforced invariants.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

_EXAMPLE = (
    Path(__file__).parent.parent.parent
    / "examples"
    / "standalone"
    / "group_options_lab"
)


def _boot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str):
    """XDG-isolate, chdir, boot the app, warm the cache the trie reads."""
    from functualize._cli.tui.app import FunctualizeInlineTUI
    from functualize.app.config import JobSources
    from functualize.app.core import FunctualizeApp

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.chdir(tmp_path)

    func_app = FunctualizeApp(
        name=name, job_sources=JobSources(directories=[str(tmp_path / "jobs")])
    )
    func_app.get_jobs()  # the scan that *writes* the cache's group_options section
    return FunctualizeInlineTUI(func_app)


@pytest.fixture()
def glab_tui(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The shipped example, booted. Real declarations, real trie."""
    shutil.copytree(_EXAMPLE / "jobs", tmp_path / "jobs")
    shutil.copy(_EXAMPLE / "config.base.toml", tmp_path / "config.base.toml")
    return _boot(tmp_path, monkeypatch, "glab")


_COLLIDING_OPTIONS = '''\
"""Two levels declaring the same field name. Deliberately not in the example."""

from functualize.job import GroupOptions


class OuterOptions(GroupOptions, group="deploy"):
    env: str = "staging"
    tier: str = "outer"


class InnerOptions(GroupOptions, group="deploy.web"):
    tier: str = "inner"

    # Collides with the job's own `region`, one level down. The CLI resolves
    # the clash in the job's favour, so these are two distinct flags that
    # share a name — and neither may retire the other from completion.
    region: str = "group-region"
'''

_COLLIDING_JOB = '''\
from typing import Annotated

from functualize.job import Arg, job

from _collide import InnerOptions, OuterOptions

JOB_GROUP = "deploy.web"


@job
def run(
    image: Annotated[str, Arg()] = "nginx",
    region: str = "job-region",
    outer: OuterOptions = None,
    inner: InnerOptions = None,
):
    """Deploy the web tier."""
    return image
'''


@pytest.fixture()
def collision_tui(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A project where `tier` is declared at both `deploy` and `deploy.web`."""
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "_collide.py").write_text(_COLLIDING_OPTIONS, encoding="utf-8")
    (jobs / "web.py").write_text(_COLLIDING_JOB, encoding="utf-8")
    return _boot(tmp_path, monkeypatch, "collide")


_CONFIG_WITH_CREDENTIAL = """\
[deploy]
env = "staging"
token = "hunter2-real-credential"

[deploy.web]
region = "us-east-1"

[status]
verbose = false
"""


@pytest.fixture()
def glab_tui_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The example, with the group's credential actually set.

    The declaration stays the shipped one — `DeployOptions.token` is
    `Secret[str]` in `_options.py` and nothing here says so a second time.
    Only the *value* is supplied, which is what a masking test needs: a blank
    field masks trivially and proves nothing.
    """
    shutil.copytree(_EXAMPLE / "jobs", tmp_path / "jobs")
    (tmp_path / "config.base.toml").write_text(
        _CONFIG_WITH_CREDENTIAL, encoding="utf-8"
    )
    return _boot(tmp_path, monkeypatch, "glab")


_FLAG_SHAPES_JOB = '''from typing import Annotated

from functualize.job import Arg, Option, RunContext, job


@job
def shapes(
    image: Annotated[str, Arg(help="Required positional — a click.Argument")],
    rc: RunContext,
    verbose: bool = False,
    quiet: Annotated[bool, Option("-q", help="Bool WITH a short flag")] = False,
    tag: Annotated[str, Option("-t")] = "latest",
    count: int = 1,
) -> str:
    """Every field shape click renders differently, in one job."""
    return image
'''


@pytest.fixture()
def flag_shapes_tui(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """One job carrying every field shape the click param builder branches on.

    The readiness check answers "would this line reach the job?" and the only
    correct source for that answer is the params click actually builds. The
    example project happens not to contain a bool with a short flag, which is
    exactly the shape whose negative spelling does **not** exist.
    """
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "shapes.py").write_text(_FLAG_SHAPES_JOB, encoding="utf-8")
    return _boot(tmp_path, monkeypatch, "shapes")


@pytest.fixture()
def ungrouped_tui(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The example with every ``GroupOptions`` declaration removed.

    The trie is ``None`` here, which is the pre-S6b world every other project
    still lives in. Behaviour gated on the trie existing has two sides and this
    is the one the group-options fixtures cannot reach: `status` proves an
    ungrouped *job* is unaffected, and says nothing about a *builtin*.
    """
    shutil.copytree(_EXAMPLE / "jobs", tmp_path / "jobs")
    for name in ("_options.py", "web.py", "worker.py"):
        (tmp_path / "jobs" / name).unlink()
    return _boot(tmp_path, monkeypatch, "glab")
