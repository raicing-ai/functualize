"""Deciding and executing what :mod:`functualize.app.packaging` planned.

The planning half -- which command upgrades this installation, adds a package
to it, or removes one, and what the environment looked like beforehand -- is
public and lives in :mod:`functualize.app.packaging`. A host asks it those
questions with no terminal in sight.

What stays here is everything that needs one:

- **the refusal** (:func:`refuse`) and the confirmation prompt
  (:func:`announce`), which print and exit;
- **the exit-code mapping** (:func:`plan_or_exit`), which turns a planning
  refusal into ``ExitCode.USAGE``;
- **the single execution seam** (:func:`_call`), and :func:`run_commands` over
  it;
- **the pending-update file**, which is bookkeeping under the CLI's own config
  directory rather than a fact about the installation.

**Nothing in this module executes anything except through :func:`_call`.** That
is deliberate: it is the single seam a test replaces to exercise a mutating
command without mutating the developer's real installation.

This module is in the ``_cli/`` layer -- stdlib + ``_cli`` siblings + public API.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

from functualize.app.packaging import (
    Detection,
    InstallMode,
    LossyReceiptError,
    MissingToolError,
)
from functualize.app.utils import ExitCode

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

__all__ = [
    "announce",
    "clear_pending",
    "load_pending",
    "plan_or_exit",
    "refuse",
    "render",
    "run_commands",
    "save_pending",
    "script_name",
]

_PENDING_NAME = "pending-update.json"


def pending_path(config_dir: Path) -> Path:
    return config_dir / _PENDING_NAME


def save_pending(config_dir: Path, snapshot: dict[str, str]) -> bool:
    """Persist the pre-update capture. ``False`` when it could not be written.

    **Written before the update runs.** Held only in memory, an update
    interrupted between rebuilding the environment and restoring it loses every
    user addition — which is the one failure the whole mechanism exists to
    prevent (`spec.md` AC14h).
    """
    path = pending_path(config_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=".pending-", suffix=".json"
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(snapshot, stream, indent=2)
                stream.write("\n")
            os.replace(tmp_name, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise
    except OSError:
        return False
    return True


def load_pending(config_dir: Path) -> dict[str, str] | None:
    """The capture left by an update that did not finish, if there is one."""
    try:
        raw = json.loads(pending_path(config_dir).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    return {str(k): str(v) for k, v in raw.items()}


def clear_pending(config_dir: Path) -> None:
    with contextlib.suppress(OSError):
        pending_path(config_dir).unlink()


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def render(argv: Sequence[str]) -> str:
    """One shell-ish line, for printing a command before it is run."""
    parts: list[str] = []
    for token in argv:
        parts.append(f'"{token}"' if " " in token else token)
    return " ".join(parts)


def script_name(environ: Mapping[str, str] | None = None) -> str:
    """The console script the user actually typed, for use in guidance.

    Never a hard-coded ``func``: in a consumer application this text has to
    name *that* application's script or it tells the user to run a command they
    do not have.

    And never ``-c``. PyApp launches a standalone binary as ``python -c "..."``,
    so ``argv[0]`` is that literal string and guidance built from it reads
    ``Run `-c builtin self doctor` `` -- a command nobody can type. PyApp
    supplies the real name in ``PYAPP_COMMAND_NAME``; falling back to the
    binary's own basename covers a build that did not expose one.
    """
    env = os.environ if environ is None else environ

    exposed = env.get("PYAPP_COMMAND_NAME", "")
    if exposed:
        return exposed

    argv0 = sys.argv[0] if sys.argv else ""
    name = argv0.replace("\\", "/").rsplit("/", 1)[-1]
    if name and name != "-c":
        return name

    binary = env.get("PYAPP", "")
    if binary and binary != "1":
        basename = binary.replace("\\", "/").rsplit("/", 1)[-1]
        if basename:
            return basename

    return "func"


def refuse(detection: Detection, what: str) -> NoReturn:
    """Explain why functualize will not manage this installation, and stop.

    Guidance names the tool that *does* own it. A refusal that only says no
    leaves the user with a broken command and no next step, and the whole
    reason detection resolves the owning distribution is so this message can be
    specific.

    Nothing is written to stdout: a script capturing this command's output must
    get an empty capture and a non-zero status, not a paragraph of prose.
    """
    import click

    mode = detection.mode.value
    distribution = detection.owning_distribution

    if distribution is None:
        click.echo(
            f"Cannot {what}: this console script maps to no installed "
            f"distribution, so there is nothing to name as the thing to change.",
            err=True,
        )
        click.echo(
            "Manage this installation with whatever put this interpreter here.",
            err=True,
        )
    else:
        click.echo(
            f"Cannot {what}: {distribution} was installed in {mode!r} mode, "
            f"which functualize does not manage.",
            err=True,
        )
        hint = (
            f"pip install --upgrade {distribution}"
            if detection.mode is InstallMode.TOOL_PIP
            else f"the tool that installed {distribution}"
        )
        click.echo(f"Use {hint} instead.", err=True)

    click.echo(
        f"Run `{script_name()} builtin self doctor` to see how this was detected.",
        err=True,
    )
    raise SystemExit(ExitCode.REFUSED)


def announce(commands: Sequence[Sequence[str]], yes: bool) -> None:
    """Print the exact commands, then ask — unless ``--yes`` was given.

    ``--yes`` skips the *prompt*, never the printing (`contracts.md` §1). A
    user who automates this still gets a log of what ran.

    Declining aborts with click's own non-zero status rather than exiting 0.
    "I asked and you said no" must not look like "I updated you" to
    ``self update && deploy``.
    """
    import click

    click.echo("This will run:")
    for argv in commands:
        click.echo(f"  {render(argv)}")
    if not yes:
        click.confirm("Proceed?", abort=True)


def plan_or_exit(
    build: Callable[[], tuple[tuple[str, ...], ...]],
) -> tuple[tuple[str, ...], ...]:
    """Run a command-planning call, mapping its refusals onto exit codes.

    Both failures are *usage* rather than refusal: the installation is
    manageable, and either the manager is absent or its receipt cannot be
    reproduced. `contracts.md` §2 assigns exit 2 to an absent external tool,
    and a receipt this cannot round-trip is the same kind of "I cannot do this
    safely, here is what you can do instead".
    """
    import click

    try:
        return build()
    except MissingToolError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(ExitCode.USAGE) from None
    except LossyReceiptError as exc:
        click.echo(str(exc), err=True)
        click.echo(
            f"Drive uv directly instead: "
            f"`{script_name()} builtin self uv -- tool install ...`",
            err=True,
        )
        raise SystemExit(ExitCode.USAGE) from None


def _call(argv: Sequence[str]) -> int:
    """Run one command, inheriting fd 0/1/2.

    **The single place this module executes anything.** Inheriting the standard
    descriptors is what lets ``uv`` draw its progress and prompt for
    credentials, exactly as ``skills install`` does — which is also why every
    command routed through here is declared terminal-owning.

    Tests replace this attribute rather than the commands that call it, so a
    mutating command can be exercised end to end without mutating the
    developer's real installation.
    """
    return subprocess.call(list(argv))  # noqa: S603


def run_commands(commands: Sequence[Sequence[str]]) -> int:
    """Run each command in order, stopping at the first non-zero exit."""
    for argv in commands:
        code = _call(argv)
        if code != 0:
            return code
    return 0
