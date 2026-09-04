"""``func builtin self`` — commands about the installation itself.

Five commands: ``doctor`` reports, ``update`` upgrades, ``install`` adds a
package, and ``python`` / ``uv`` hand the user the owned environment directly.

**Every mutating command prints what it will run before it runs it**, and does
nothing without confirmation. That is not politeness — it is the seam that makes
these commands testable at all, since asserting on the printed command needs no
subprocess and no real installation to mutate.

**Why doctor runs before the app boots.** ``cli_app`` unconditionally resolves
config, loads dotenv, applies ``import_libs``, runs discovery and constructs a
``FunctualizeApp`` before any builtin subcommand is reached. A doctor mounted as
an ordinary builtin would therefore never be *reached* when boot fails — the
one moment it is worth having — and its boot-shaped checks could only ever
report success, because their success is the precondition for arriving at them.
So ``_run_cli`` intercepts ``self doctor`` beside ``--version``, and the checks
that need a booted app run in a **child process** where a crash is a reportable
result rather than doctor's own traceback.

**A check that cannot report ill is not shipped.** Plugin loading is the
concrete case: ``_load_file_plugin`` catches, logs and discards, keeping no
record, so nothing in-process can observe that a plugin failed. Rather than
print a reassuring "plugins: ok" that is true by construction, the check is
absent. It returns when a load-failure record exists to read.

This module is in the ``_cli/`` layer — public API only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import click

from functualize._cli.runtime import Detection, InstallMode, detect_from_process
from functualize.app.utils import ExitCode

# `manifest` and `package_ops` are imported *inside* the commands that need
# them, never at module scope. `builtins._mount` imports this module while
# building the `builtin` group, so a module-level import here would put the
# registry on every warm path — which is exactly what AC9 asserts structurally.

__all__ = ["Check", "CheckStatus", "DoctorReport", "build_report", "self_app"]

#: The floor `pyproject.toml` declares. Below it, nothing else is worth saying.
_MIN_PYTHON = (3, 11)

#: How long the child boot probe gets before it is called hung.
_BOOT_PROBE_TIMEOUT_S = 30.0


class CheckStatus(StrEnum):
    """How a single check came out.

    **There is deliberately no ``SKIPPED``.** A check that cannot be performed
    is not emitted at all, because a skipped line reads as health that was not
    observed — which is the failure this whole module is shaped to avoid.
    """

    OK = "ok"
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class Check:
    """One observation. ``remedy`` is what the user can do about it."""

    name: str
    status: CheckStatus
    detail: str
    remedy: str | None = None


@dataclass(frozen=True)
class DoctorReport:
    """Every check, in the order they were run.

    Text and JSON both render from this one structure, so the two cannot drift
    into disagreeing about the same installation.
    """

    checks: tuple[Check, ...] = field(default_factory=tuple)

    @property
    def worst(self) -> CheckStatus:
        for status in (CheckStatus.CRITICAL, CheckStatus.WARNING):
            if any(c.status is status for c in self.checks):
                return status
        return CheckStatus.OK

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.worst.value,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "detail": c.detail,
                    **({"remedy": c.remedy} if c.remedy else {}),
                }
                for c in self.checks
            ],
        }


def _check_python() -> Check:
    v = sys.version_info
    running = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) < _MIN_PYTHON:
        floor = ".".join(str(p) for p in _MIN_PYTHON)
        return Check(
            "python",
            CheckStatus.CRITICAL,
            f"{running} is below the supported floor of {floor}",
            remedy=f"Install functualize under Python {floor} or newer.",
        )
    return Check("python", CheckStatus.OK, running)


def _check_cli_extras() -> Check:
    """Are the ``[cli]`` extras importable?

    This one can genuinely fail while doctor still runs, because doctor is
    reached pre-boot: a core-only install has no ``rich`` or ``textual``, and
    the TUI silently degrades rather than announcing itself.
    """
    import importlib.util

    missing = [
        name
        for name in ("click", "rich", "textual")
        if importlib.util.find_spec(name) is None
    ]
    if missing:
        return Check(
            "cli-extras",
            CheckStatus.WARNING,
            f"missing: {', '.join(missing)}",
            remedy='Install the CLI extras: pip install "functualize[cli]"',
        )
    return Check("cli-extras", CheckStatus.OK, "present")


def _check_install(detection: Detection) -> list[Check]:
    checks = [
        Check("install-mode", CheckStatus.INFO, detection.mode.value),
    ]
    if detection.mode is InstallMode.STANDALONE:
        # Not a warning, and not "unknown". A standalone binary has no owning
        # distribution *by construction* -- it is a file, not a package -- so
        # reporting the absence as a fault would tell a healthy installation
        # that self-management is unavailable, which it is not. What identifies
        # it is the executable, and that is worth showing.
        checks.append(
            Check(
                "owning-distribution",
                CheckStatus.INFO,
                "not applicable — a standalone binary manages itself",
            )
        )
        if detection.standalone_binary is None:
            checks.append(
                Check(
                    "binary-path",
                    CheckStatus.WARNING,
                    "this binary cannot determine its own location",
                    remedy=(
                        "It was built without PYAPP_PASS_LOCATION=1, so there is "
                        "nothing for `self update` to replace. Reinstall from a "
                        "current release."
                    ),
                )
            )
        else:
            checks.append(
                Check("binary-path", CheckStatus.OK, detection.standalone_binary)
            )
    elif detection.owning_distribution is None:
        checks.append(
            Check(
                "owning-distribution",
                CheckStatus.WARNING,
                "could not be determined from the running console script",
                remedy=(
                    "Self-management is unavailable here. Upgrade with whatever "
                    "installed this interpreter."
                ),
            )
        )
    else:
        checks.append(
            Check(
                "owning-distribution", CheckStatus.INFO, detection.owning_distribution
            )
        )
    if detection.mode.degraded:
        checks.append(
            Check(
                "self-management",
                CheckStatus.WARNING,
                f"{detection.mode.value} installations are not self-managing",
                remedy="Upgrade and add plugins with the tool that installed this.",
            )
        )
    return checks


#: Run in a *child* interpreter, so a boot that dies is data rather than a
#: traceback out of doctor. Prints one JSON line and nothing else.
#:
#: **It drives the real CLI entry point, not a bare `FunctualizeApp`.** An
#: earlier version constructed the app directly, which answered a question
#: nobody asked: a bare app boots with none of the CLI's discovery config, so
#: it reported "the app starts" in a project where `func builtin version` in
#: fact died on a reserved group name. `cli_app` is the boot that matters,
#: because it is the one every other command pays for.
#:
#: `builtin version` is the cheapest command that still traverses the whole
#: chain — `resolve_cli_config` -> `_load_dotenv` -> `_apply_import_libs` ->
#: `auto_discover` -> `FunctualizeApp(...)` -> `refresh()` — and it cannot
#: recurse into doctor.
_BOOT_PROBE = """
import io, json, sys
from contextlib import redirect_stderr, redirect_stdout
sys.argv = ["func", "builtin", "version"]
buf, err = io.StringIO(), io.StringIO()
try:
    from functualize._cli.main import _run_cli
    with redirect_stdout(buf), redirect_stderr(err):
        _run_cli()
except SystemExit as exc:
    code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    if code:
        detail = (err.getvalue() or buf.getvalue()).strip().splitlines()
        print(json.dumps({
            "ok": False,
            "error": detail[-1] if detail else f"exit code {code}",
        }))
    else:
        print(json.dumps({"ok": True}))
except BaseException as exc:
    print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
else:
    print(json.dumps({"ok": True}))
"""

#: Counts jobs, separately, so a discovery failure cannot masquerade as a boot
#: failure. Run only once the boot probe has come back clean.
_JOBS_PROBE = """
import json, pathlib
try:
    from functualize.app import FunctualizeApp
    from functualize.app.utils import auto_discover
    result = auto_discover(pathlib.Path.cwd())
    app = FunctualizeApp(name="doctor-probe", job_sources=result.job_sources)
    app.refresh()
    print(json.dumps({"ok": True, "jobs": len(app.get_jobs())}))
except BaseException as exc:
    print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
"""


def _run_probe(script: str, cwd: Path) -> dict[str, object] | Check:
    """Run one probe in a child and parse its JSON verdict.

    Returns a ``Check`` instead when the child could not be run or did not
    answer at all — those are findings too, not exceptions.
    """
    try:
        completed = subprocess.run(  # noqa: S603
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=_BOOT_PROBE_TIMEOUT_S,
            cwd=cwd,
            # The boot probe drives the real entry point, which would otherwise
            # register a phantom installation under the probe's own argv0 --
            # doctor would add an entry every time it reported on the registry.
            env={**os.environ, "FUNCTUALIZE_NO_REGISTER": "1"},
        )
    except subprocess.TimeoutExpired:
        return Check(
            "boot",
            CheckStatus.CRITICAL,
            f"did not finish within {_BOOT_PROBE_TIMEOUT_S:.0f}s",
            remedy="A job module may block at import time.",
        )
    except OSError as exc:  # pragma: no cover - no interpreter to spawn
        return Check("boot", CheckStatus.CRITICAL, f"could not run a probe: {exc}")

    for line in reversed(completed.stdout.splitlines()):
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    stderr = completed.stderr.strip().splitlines()
    return Check(
        "boot",
        CheckStatus.CRITICAL,
        stderr[-1] if stderr else f"the probe exited {completed.returncode} in silence",
        remedy="Run the failing command directly to see the traceback.",
    )


def _check_boot(cwd: Path) -> list[Check]:
    """Can the CLI actually start here, and how many jobs does it find?

    Observed, not assumed. Running either probe in-process would mean a failure
    took doctor down with it — the report would be a traceback, at exactly the
    moment a report is most useful.

    Job counting is a **separate** probe, run only after boot comes back clean,
    so a discovery problem is never reported as a boot failure and vice versa.
    """
    boot = _run_probe(_BOOT_PROBE, cwd)
    if isinstance(boot, Check):
        return [boot]
    if not boot.get("ok"):
        return [
            Check(
                "boot",
                CheckStatus.CRITICAL,
                str(boot.get("error") or "").strip() or "the CLI did not start",
                remedy="Run `func builtin version` here to see the failure.",
            )
        ]

    checks = [Check("boot", CheckStatus.OK, "the CLI starts")]

    jobs = _run_probe(_JOBS_PROBE, cwd)
    if isinstance(jobs, Check) or not jobs.get("ok"):
        detail = (
            jobs.detail
            if isinstance(jobs, Check)
            else str(jobs.get("error") or "").strip()
        )
        checks.append(
            Check(
                "job-discovery",
                CheckStatus.WARNING,
                detail or "discovery failed",
                remedy="The CLI starts, but jobs cannot be enumerated here.",
            )
        )
    else:
        checks.append(
            Check(
                "job-discovery",
                CheckStatus.INFO,
                f"{jobs.get('jobs', 0)} discovered from {cwd}",
            )
        )
    return checks


def _check_registry() -> list[Check]:
    """What else has run on this machine, and is any of it gone?

    Read only — the registry is never derived. An installation appears here
    because it registered itself when it ran, so a `func` that has never
    executed is legitimately absent.

    A record whose `binary_path` no longer resolves is *reported*, never
    removed: the file is append-only, because two installations coexisting is
    a real state and `PATH` decides which one runs.
    """
    try:
        from functualize._cli import manifest as _manifest
        from functualize.app.utils import resolve_user_config_dir

        config_dir = resolve_user_config_dir()
        registry = _manifest.load(_manifest.manifest_path(config_dir))
    except Exception:  # noqa: BLE001 - an unreadable registry is not an error
        return []

    if not registry.installations:
        return [Check("installations", CheckStatus.INFO, "none registered yet")]

    running = sys.argv[0] if sys.argv else ""
    stale = [r for r in registry.installations if not Path(r.binary_path).exists()]

    checks = [
        Check(
            "installations",
            CheckStatus.INFO,
            f"{len(registry.installations)} registered, {len(stale)} stale",
        )
    ]
    for record in registry.installations:
        marker = " (running)" if record.binary_path == running else ""
        gone = " [stale]" if record in stale else ""
        checks.append(
            Check(
                f"  {record.binary_path}",
                CheckStatus.WARNING if gone else CheckStatus.INFO,
                f"{record.functualize_version}  {record.runtime_mode}{marker}{gone}",
                remedy=(
                    "This binary no longer exists. The record is kept because "
                    "the registry is append-only."
                )
                if gone
                else None,
            )
        )
    return checks


def _check_terminal() -> Check:
    tty = sys.stdout.isatty()
    return Check(
        "terminal",
        CheckStatus.INFO,
        "interactive" if tty else "not a terminal (piped or redirected)",
    )


def build_report(cwd: Path | None = None) -> DoctorReport:
    """Run every check that can observe something and collect the results.

    Note what is *not* here: no "core import" check (this code is running, so
    it could only say yes), no "config resolution" check (the same), and no
    plugin-loading check (nothing records the failures).
    """
    where = cwd if cwd is not None else Path.cwd()
    detection = detect_from_process(cwd=where)
    checks: list[Check] = [_check_python(), _check_cli_extras()]
    checks.extend(_check_install(detection))
    checks.extend(_check_registry())
    checks.extend(_check_boot(where))
    checks.append(_check_terminal())
    return DoctorReport(tuple(checks))


_GLYPH = {
    CheckStatus.OK: "ok",
    CheckStatus.INFO: "  ",
    CheckStatus.WARNING: "!!",
    CheckStatus.CRITICAL: "XX",
}


#: Names longer than this stop widening the column and simply overflow. One
#: registry entry is an absolute path, and letting it set the width pushes
#: every other line off the right of an 80-column terminal.
_NAME_COLUMN_MAX = 22


def render_report_text(report: DoctorReport) -> list[str]:
    width = min(max((len(c.name) for c in report.checks), default=0), _NAME_COLUMN_MAX)
    lines: list[str] = []
    for check in report.checks:
        lines.append(f"  {_GLYPH[check.status]}  {check.name:<{width}}  {check.detail}")
        if check.remedy:
            lines.append(f"      {' ' * width}  -> {check.remedy}")
    return lines


@click.group(name="self", help="Inspect and manage this installation.")
def self_app() -> None:
    """Commands about the installation, as opposed to about your jobs."""


@self_app.command("doctor")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Render the report as text or JSON.",
)
def doctor(output_format: str) -> None:
    """Check this installation and report what is wrong with it."""
    report = build_report()
    if output_format == "json":
        click.echo(json.dumps(report.to_dict(), indent=2))
    else:
        for line in render_report_text(report):
            click.echo(line)
    # A report is a successful run even when it reports problems: exit codes
    # describe the command, and the command worked.


# ---------------------------------------------------------------------------
# The mutating commands, and the escape hatch
# ---------------------------------------------------------------------------


def _this_binary() -> str:
    from functualize._cli import manifest

    return manifest.resolve_binary_path(
        sys.argv[0] if sys.argv else "",
        sys.executable,
        detect_from_process().standalone_binary,
    )


def _config_dir() -> Path:
    from functualize.app.utils import resolve_user_config_dir

    return resolve_user_config_dir()


@self_app.command("update")
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    help="Skip the confirmation prompt. The command is still printed.",
)
def update(assume_yes: bool) -> None:
    """Upgrade this installation, then put back what you added to it."""
    from functualize._cli import package_ops

    detection = detect_from_process()
    if detection.degraded:
        package_ops.refuse(detection, "update")

    binary = _this_binary()
    try:
        commands = package_ops.plan_or_exit(
            lambda: package_ops.update_commands(detection, binary)
        )
    except package_ops.StandaloneUpdateError:
        # A standalone binary has no package manager to delegate to: updating
        # it means fetching a release and replacing one file, which happens
        # in-process. Raised rather than returned as an empty command list, so
        # forgetting this branch fails loudly instead of reporting success
        # having done nothing.
        raise SystemExit(_update_standalone(binary, assume_yes)) from None

    package_ops.announce(commands, assume_yes)

    config_dir = _config_dir()

    # The pre-update capture is persisted *before* anything runs. An update
    # interrupted between rebuilding the environment and restoring it would
    # otherwise lose every user addition -- the one failure reconciliation
    # exists to prevent. A capture already on disk means exactly that happened
    # last time, so it is preferred over a fresh one: the current environment
    # is the half-updated state, not the state worth restoring to.
    resumed = package_ops.load_pending(config_dir)
    if resumed is not None:
        click.echo("Resuming: an earlier update did not finish reconciling.")
        before = resumed
    else:
        before = package_ops.capture_environment()
        package_ops.save_pending(config_dir, before)

    code = package_ops.run_commands(commands)
    if code != 0:
        click.echo(
            "The upgrade command failed; nothing was reconciled. "
            "The pre-update snapshot is kept, so re-running will still restore.",
            err=True,
        )
        raise SystemExit(code)

    _reconcile(detection, config_dir, binary, before)


def _update_standalone(binary: str, assume_yes: bool) -> int:
    """`self update` for a standalone binary. Returns the process exit code.

    Reconciliation is deliberately *not* the in-process kind the other modes
    use. Replacing the executable means the next launch unpacks a different
    distribution at a different path, so packages added to the old one are not
    "removed by an upgrade" -- they are in a directory nothing will look at
    again. The new binary is therefore asked to install them into its own
    distribution, which it can only do after it has unpacked one.
    """
    import functualize
    from functualize._cli import manifest, self_update

    config_dir = _config_dir()
    # Captured before the replacement, for the same reason every other mode
    # persists first: an update interrupted between the two loses the record of
    # what to put back.
    keep = sorted(set(manifest.recorded_additions(config_dir, binary)))

    code = self_update.perform(
        binary=Path(binary),
        prefix=Path(sys.prefix),
        current_version=functualize.__version__,
        assume_yes=assume_yes,
        echo=click.echo,
        confirm=click.confirm,
    )
    if code != int(ExitCode.OK) or not keep:
        return code

    click.echo(f"Reinstalling {len(keep)} package(s) into the new distribution.")
    failed: list[str] = []
    for package in keep:
        result = subprocess.run(  # noqa: S603 - argv list, no shell
            [binary, "builtin", "self", "install", package, "--yes"],
            check=False,
        )
        if result.returncode != 0:
            failed.append(package)

    for package in failed:
        click.echo(f"  could not reinstall {package}", err=True)
    if failed:
        # Reported, not fatal: the update itself succeeded, and turning one
        # unreachable package into a failed update would misdescribe the state
        # of the installation.
        click.echo(
            f"{len(failed)} package(s) need reinstalling by hand.",
            err=True,
        )
    return int(ExitCode.OK)


def _reconcile(
    detection: Detection,
    config_dir: Path,
    binary: str,
    before: dict[str, str],
) -> None:
    """Reinstall what the upgrade removed, and say what happened to each.

    A package that cannot be reinstalled is **reported, not fatal**: the
    upgrade itself succeeded, and turning one unreachable package into a failed
    update would misdescribe the state of the installation.
    """
    from functualize._cli import manifest, package_ops

    after = package_ops.capture_environment()
    recorded = manifest.recorded_additions(config_dir, binary)
    names = package_ops.names_to_restore(before, after, recorded)

    if not names:
        click.echo("Up to date. Nothing needed restoring.")
        package_ops.clear_pending(config_dir)
        return

    click.echo(f"Restoring {len(names)} package(s) the upgrade removed:")
    failures: list[tuple[str, str]] = []
    for name in names:
        try:
            commands = package_ops.install_commands(detection, name)
        except (
            package_ops.MissingToolError,
            package_ops.LossyReceiptError,
            ValueError,
        ) as exc:
            failures.append((name, str(exc)))
            continue
        code = package_ops.run_commands(commands)
        if code == 0:
            click.echo(f"  restored  {name}")
        else:
            failures.append((name, f"the install command exited {code}"))

    for name, reason in failures:
        click.echo(f"  FAILED    {name}: {reason}", err=True)
    if failures:
        click.echo(
            f"{len(failures)} package(s) could not be restored. The upgrade "
            f"itself succeeded; reinstall them yourself when you can.",
            err=True,
        )

    package_ops.clear_pending(config_dir)


@self_app.command("install")
@click.argument("package")
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    help="Skip the confirmation prompt. The command is still printed.",
)
def install(package: str, assume_yes: bool) -> None:
    """Install a package into this installation's environment.

    For dependencies your jobs import. Extensions to functualize itself go
    through `plugin install`, which records them where `plugin list` can see
    them.
    """
    from functualize._cli import manifest, package_ops

    detection = detect_from_process()
    if detection.degraded:
        package_ops.refuse(detection, f"install {package}")

    commands = package_ops.plan_or_exit(
        lambda: package_ops.install_commands(detection, package)
    )
    package_ops.announce(commands, assume_yes)

    code = package_ops.run_commands(commands)
    if code != 0:
        raise SystemExit(code)

    # Recorded only now. A record of a package that failed to install is worse
    # than no record: the next update would faithfully reinstall it.
    if manifest.record_addition(
        _config_dir(), binary_path=_this_binary(), key="packages", name=package
    ):
        click.echo(f"Recorded {package}; `self update` will restore it.")


def _owned_environment(detection: Detection, what: str) -> None:
    """Refuse unless there is an environment this installation owns."""
    from functualize._cli import package_ops

    if detection.degraded:
        package_ops.refuse(detection, f"run {what}")


@self_app.command(
    "python",
    context_settings={"ignore_unknown_options": True},
    short_help="Run this installation's interpreter, or print its path.",
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def python_(args: tuple[str, ...]) -> None:
    """Run the interpreter this installation owns.

    \b
      func builtin self python -- -m pip debug    run it
      func builtin self python                    print its path

    Everything after `--` is passed through untouched and the exit code is
    proxied back. Bare, it prints exactly one absolute path and nothing else,
    so it stays capturable.
    """
    from functualize._cli import package_ops

    detection = detect_from_process()
    _owned_environment(detection, "python")

    interpreter = package_ops.owned_python()
    if not args:
        click.echo(interpreter)
        return
    raise SystemExit(package_ops.run_commands([[interpreter, *args]]))


@self_app.command(
    "uv",
    context_settings={"ignore_unknown_options": True},
    short_help="Run the uv this installation uses, or print its path.",
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def uv_(args: tuple[str, ...]) -> None:
    """Run the uv this installation manages itself with.

    \b
      func builtin self uv -- pip install requests    run it
      func builtin self uv                            print its path

    The escape hatch: anything this command tree declines to do — a git
    requirement, an index URL, a receipt shape a future uv introduces — you can
    still do by driving uv yourself.
    """
    from functualize._cli import package_ops

    detection = detect_from_process()
    _owned_environment(detection, "uv")

    try:
        uv = package_ops.resolve_uv()
    except package_ops.MissingToolError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(ExitCode.USAGE) from None

    if not args:
        click.echo(uv)
        return
    raise SystemExit(package_ops.run_commands([[uv, *args]]))
