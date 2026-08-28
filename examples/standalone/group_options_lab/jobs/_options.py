"""The group declarations. Two levels, so inheritance is observable.

Underscore-prefixed because it holds no jobs — the scan reads it for
``GroupOptions`` subclasses and finds nothing job-shaped. (That it is read at
all was once a bug: an early pre-filter skipped `_`-prefixed modules and hid
group declarations from discovery entirely.)

Each class binds to a dotted path with the ``group=`` class keyword. The path
is recorded on ``__group_path__`` at class-creation time, and discovery *also*
recovers it from the source AST, so the cached spec — what the TUI and
completion read — never needs to import this module.
"""

from typing import Annotated

from functualize.job import GroupOptions, Option
from functualize.types import Secret


class DeployOptions(GroupOptions, group="deploy"):
    """Flags accepted at `deploy`, inherited by every job beneath it."""

    env: Annotated[str, Option("-e", help="Target environment")] = "staging"

    dry_run: Annotated[bool, Option("--dry-run", help="Preview only")] = False

    # A group option is a config field like any other, so it is a credential
    # like any other. Detection follows the declaration, not the name, and
    # every surface that renders a field asks the same question of it — which
    # is what the panel work has to keep true for group rows as well as job
    # rows.
    token: Annotated[Secret[str], Option(help="Registry credential")] = Secret("")


class WebOptions(GroupOptions, group="deploy.web"):
    """Flags accepted at `deploy.web` — the deeper of the two levels.

    A job under `deploy.web` can inject both this and ``DeployOptions``; a job
    under `deploy.worker` can only inject ``DeployOptions``. That asymmetry is
    the thing to look at when reading the panels: the field list for
    `deploy.web.run` is longer than the one for `deploy.worker.run`, and the
    extra rows are attributed to the deeper group.
    """

    region: Annotated[str, Option("-r", help="Cloud region")] = "us-east-1"
