"""Shared helpers for built-in command registration."""

from __future__ import annotations

import contextlib
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

from functualize.app.utils import (
    ExitCode,
    Family,
    is_failure,
)


def _resolve_editor() -> str | None:
    """Resolve editor from $VISUAL → $EDITOR → platform default.

    Returns the editor command string, or None if no editor is found.
    """
    # Check $VISUAL first, then $EDITOR
    editor = os.environ.get("VISUAL", "").strip()
    if editor:
        return editor

    editor = os.environ.get("EDITOR", "").strip()
    if editor:
        return editor

    # Platform default
    system = platform.system()
    if system == "Windows":
        return "notepad"
    elif system == "Darwin":
        # macOS: use 'open -t' for default text editor? No, requirement says vi.
        # Requirement 16.3: platform default is vi on POSIX
        if shutil.which("vi"):
            return "vi"
        return None
    else:
        # Linux / other POSIX: vi
        if shutil.which("vi"):
            return "vi"
        return None


# Template for initial global config file
_CONFIG_TEMPLATE = """\
# Functualize global configuration
# See: https://functualize.dev/docs/cli/config

[discovery]
# require_file_prefix = "job_"
# require_file_postfix = "_task"
# require_file_import = "functualize"
# require_file_marker = "__functualize__"
# require_job_decorators = ["job", "workflow"]
# require_job_prefix = "run_"
# require_job_postfix = "_job"
# extra_directories = ["~/.config/functualize/jobs"]
# exclude_patterns = ["**/test_*.py", "**/migrations/*.py"]

[cli]
# output = "rich"      # "rich" | "plain" | "json"
# show_timing = false

[aliases]
# d = "deploy"
# r = "run"
"""


def _toml_value(value: Any) -> str:
    """Format a Python value as a TOML value string."""
    if value is None:
        return "# (not set)"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, list | tuple):
        if not value:
            return "[]"
        items = ", ".join(f'"{v}"' for v in value)
        return f"[{items}]"
    return str(value)


def _determine_source(
    key: str,
    resolved_value: Any,
    project_config: dict[str, Any],
    global_config: dict[str, Any],
    section: str,
) -> str:
    """Determine which source a resolved value came from."""
    # Check project config
    proj_section = project_config.get(section, {})
    if isinstance(proj_section, dict) and key in proj_section:
        return "project"

    # Check global config
    glob_section = global_config.get(section, {})
    if isinstance(glob_section, dict) and key in glob_section:
        return "global"

    # Check env var
    env_key = f"FUNCTUALIZE_{section.upper()}_{key.upper()}"
    if os.environ.get(env_key):
        return "env"

    return "default"


def _emit_config_field(
    lines: list[str],
    key: str,
    display_value: Any,
    resolved_value: Any,
    project_config: dict[str, Any],
    global_config: dict[str, Any],
    section: str,
) -> None:
    """Emit a config field line with source annotation."""
    source = _determine_source(
        key, resolved_value, project_config, global_config, section
    )
    toml_val = _toml_value(display_value)
    if display_value is None:
        lines.append(f"# {key} = (not set)")
    else:
        lines.append(f"{key} = {toml_val}  # source: {source}")


def _resolve_env_vars(app: Any, job_name: str) -> list[Any]:
    """A job's config as :class:`ResolvedField` rows, for export (T43).

    Reads the one resolution seam, so the names and values match a real run and
    ``info --job``. Two things this deliberately does *not* do:

    - It does not construct the Pydantic model, so a job with a required field
      that nothing sets is reported rather than raising ``ValidationError``.
      The command exists to tell an operator what is missing; a traceback in
      exactly that case made it useless when it was most needed.
    - It does not drop unresolved fields. They are the answer, not noise.
    """
    from functualize.app.utils import job_config_fields

    return job_config_fields(app, job_name)


def _env_print(env_vars: list[Any], include_secrets: bool) -> None:
    """Print ``export NAME=value`` lines for ``eval`` (T43).

    A secret is masked unless the caller opted in, so the default output is safe
    to paste into a bug report or read off a shared screen; ``eval``-ing it with
    a masked secret would set the variable to ``•••``, which is the point — the
    real value takes a deliberate ``--include-secrets``.

    An unresolved field is emitted **commented out**, with why. Masking used to
    make a set secret and an unset one byte-identical (``SYNC_TOKEN='•••'``
    either way), so the one command an operator would reach for to answer "is
    the credential configured?" could not answer it. Commenting the unset ones
    also makes the output a ready ``.env`` skeleton, which is what the
    ``--template`` flag was going to be for.
    """
    import shlex

    import click

    from functualize.app.utils import display_value, reveal

    for f in env_vars:
        if not f.is_set:
            note = "REQUIRED — not set" if f.required else "not set"
            click.echo(f"# {f.env_name}=  # {note}")
            continue
        # `reveal` unwraps a `Secret`; whether that real value is shown is the
        # caller's opt-in, decided here rather than at resolution time.
        shown = (
            str(reveal(f.value))
            if include_secrets
            else display_value(f.value, secret=f.secret)
        )
        source = f"  # source: {f.source}" if f.source else ""
        click.echo(f"export {f.env_name}={shlex.quote(shown)}{source}")


def _env_exec(
    env_vars: list[Any],
    command: list[str],
    include_secrets: bool,
) -> None:
    """Run ``command`` with the resolved vars injected (T43).

    A secret is **omitted** from the child environment unless the caller opted
    in — never masked, because ``•••`` is not the value the tool needs and a
    masked secret silently breaks it. Omission is the honest default: the tool
    sees the non-secret config and fails loudly on the missing credential,
    rather than mysteriously on a corrupted one.
    """
    import os

    import click

    from functualize.app.utils import reveal

    child_env = dict(os.environ)
    for f in env_vars:
        if not f.is_set:
            continue
        if f.secret and not include_secrets:
            continue
        child_env[f.env_name] = str(reveal(f.value))

    try:
        completed = subprocess.run(command, env=child_env, check=False)
    except FileNotFoundError:
        click.echo(f"Error: command not found: {command[0]}", err=True)
        raise SystemExit(ExitCode.USAGE) from None
    raise SystemExit(completed.returncode)


def _completions_install_path(shell: str) -> Path:
    """Where ``--install`` writes ``init.{bash,zsh,fish}`` (T44b).

    ``<cache dir>/completions/init.<shell>``, where the cache dir is exactly
    what ``resolve_cache_path`` resolves to (its parent) — so the completion
    script lands beside the discovery cache in project mode and under the XDG
    cache in standalone mode, with **no** second path-resolution rule to drift
    from the one the rest of the tool uses.
    """
    from pathlib import Path

    from functualize.app.utils import resolve_cache_path

    cache_dir = resolve_cache_path(Path.cwd()).parent
    return cache_dir / "completions" / f"init.{shell}"


def _render_history(records: list[dict[str, Any]]) -> list[str]:
    """One line per run record, across both namespaces (T42).

    The ring holds two record shapes — a job run (``job`` + ``status`` +
    ``duration_ms``) and a shell command (``command`` + ``exit_code``) — because
    both are "something that ran here". Rather than a schema-per-namespace
    renderer that would need editing every time a namespace is added, each line
    is built from whatever fields a record carries: the namespace tag, the
    timestamp, an outcome, and a label. A record missing a field degrades to a
    blank column, never a crash — this is a convenience log, and a malformed
    entry must not make the whole command unusable.
    """
    lines: list[str] = []
    for record in records:
        namespace = str(record.get("namespace", "-"))
        at = str(record.get("at", ""))
        # Outcome: a job carries a status word; a shell command carries an exit
        # code. Show whichever is present so both read as "did it work?".
        if "status" in record:
            outcome = str(record["status"])
        elif "exit_code" in record:
            code = record["exit_code"]
            outcome = "ok" if code == 0 else f"exit {code}"
        else:
            outcome = "-"
        # Label: the job name, or the shell command line.
        label = str(record.get("job") or record.get("command") or "-")
        duration = record.get("duration_ms")
        timing = f"  {duration:.0f}ms" if isinstance(duration, (int, float)) else ""
        lines.append(f"{namespace:<7} {outcome:<9} {label}{timing}  {at}")
    return lines


def _report_parallel(job_names: tuple[str, ...], results: list[Any]) -> None:
    """Print the per-job summary and exit non-zero if any job failed (T40).

    The summary goes to **stderr** and the exit code carries the verdict, so a
    batch stays composable: ``func builtin parallel a b | jq`` still sees only
    what the jobs emitted. A summary written to stdout would corrupt exactly
    the pipelines this command exists to feed.
    """
    import click

    from functualize.app.utils import RunStatus, exit_code_for_status

    failed: list[Any] = []
    for name, result in zip(job_names, results, strict=False):
        status = getattr(result, "status", RunStatus.UNKNOWN)
        detail = ""
        if status is not RunStatus.SUCCESS and result.exception is not None:
            detail = f" — {type(result.exception).__name__}: {result.exception}"
        click.echo(f"{status.value:<8} {name}{detail}", err=True)
        # `func builtin parallel` is a PROCESS surface: it terminates the
        # process with an exit code a shell reads. The family answers, this
        # site does not.
        #
        # This *changes* one answer, deliberately. The tuple that used to live
        # here counted BLOCKED as not-a-failure, so a batch in which a job
        # paused at a gate exited 0 — "all good" — and the pause was invisible
        # to anything reading only the exit code. That is the same false clean
        # as D-7, and the reason the exit-code table reserves 5 for it.
        if is_failure(status, family=Family.PROCESS):
            failed.append(result)

    if not failed:
        return

    # One batch, one exit code. With several distinct failures there is no
    # single honest answer, so the *first* one is reported rather than an
    # invented aggregate — it is the one whose message was printed first, and
    # re-running after fixing it surfaces the next.
    raise SystemExit(exit_code_for_status(failed[0].status))


def _project_substrate(ctx: Any | None) -> Any:
    """The storage this project is actually using, not the filesystem default.

    `plugin-taxonomy`/T5. Every store under `func builtin data`, `run` and
    `history` was built with ``Store.for_project(Path.cwd())``, which routes
    through ``substrate_for_project`` and **always** answers
    `JsonFileSubstrate`. A plugin does not choose storage that way — it calls
    ``app.install_substrate`` at ``APP_READY`` — so with a substrate plugin
    installed these commands read a different backend from the one the run
    wrote to.

    Measured, in one project, immediately after one successful run::

        func builtin why <job>   ->  SKIP (up to date)   # reads the database
        func builtin data show   ->  Fingerprints: 0     # reads the files

    The command whose whole job is *tell me where my data is and how much of it
    there is* reported none, about a project that had some. `why` was right
    because it takes its app from the Click context; these now do the same.

    ``None`` when there is no app in the context, which is not a failure: `func`
    builds that context for the builtins that need one, and without it the
    caller falls back to the cwd walk — the correct answer when no plugin
    installed anything.
    """
    obj = ctx.find_root().obj if ctx is not None else None
    app = obj.get("app") if isinstance(obj, dict) else None
    if app is None:
        return None
    with contextlib.suppress(Exception):
        return app.substrate
    return None


def _state_location() -> tuple[Path, str, Path | None]:
    """The resolved state path, its mode, and the directory that decided it.

    One upward walk through the same function the engine uses, so the CLI
    cannot report a path the engine would not write to.
    """
    from functualize.app.utils import resolve_fresh_location

    return resolve_fresh_location(Path.cwd())


def _state_mode_line(mode: str, marker: Path | None) -> str:
    """Render the state-store mode for a human.

    Both modes name what put them there, because "which mode am I in" was
    undiscoverable and the answer decides where to look for the file. In
    standalone mode the line also names the switch — a project that wants its
    ledger versioned with the code only needs `mkdir .functualize`.
    """
    if mode == "project":
        return f"project (.functualize/ found at {marker})"
    return (
        "standalone (no .functualize/ found; create one to keep state in the project)"
    )


def _mount(cli_group: Any, command: Any, name: str) -> None:
    """Add a builtin command/group under the 'Functualize Commands' help panel."""
    command._functualize_panel = "Functualize Commands"
    cli_group.add_command(command, name=name)
