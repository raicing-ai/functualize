"""``func builtin self`` — commands about the installation itself.

Doctor is the whole of this module for now; ``update``, ``install``, ``python``
and ``uv`` land in a later task.

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
import subprocess
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import click

from functualize._cli.runtime import Detection, detect_from_process

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
    if detection.owning_distribution is None:
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
_BOOT_PROBE = """
import json, sys
try:
    from functualize.app import FunctualizeApp
    app = FunctualizeApp(name="doctor-probe")
    app.refresh()
    n = len(app.get_jobs())
    print(json.dumps({"ok": True, "jobs": n}))
except BaseException as exc:
    print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
"""


def _check_boot(cwd: Path) -> list[Check]:
    """Can the application actually start here, and does it find jobs?

    Observed, not assumed. Running it in-process would mean a failure took
    doctor down with it — the report would be a traceback, at exactly the
    moment a report is most useful.
    """
    try:
        completed = subprocess.run(  # noqa: S603
            [sys.executable, "-c", _BOOT_PROBE],
            capture_output=True,
            text=True,
            timeout=_BOOT_PROBE_TIMEOUT_S,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired:
        return [
            Check(
                "boot",
                CheckStatus.CRITICAL,
                f"did not finish within {_BOOT_PROBE_TIMEOUT_S:.0f}s",
                remedy="A job module may block at import time.",
            )
        ]
    except OSError as exc:  # pragma: no cover - no interpreter to spawn
        return [Check("boot", CheckStatus.CRITICAL, f"could not run a probe: {exc}")]

    payload: dict[str, object] = {}
    for line in reversed(completed.stdout.splitlines()):
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        break

    if not payload.get("ok"):
        detail = str(payload.get("error") or "").strip()
        if not detail:
            stderr = completed.stderr.strip().splitlines()
            detail = stderr[-1] if stderr else f"exit code {completed.returncode}"
        return [
            Check(
                "boot",
                CheckStatus.CRITICAL,
                detail,
                remedy="Run the failing command directly to see the traceback.",
            )
        ]

    jobs = payload.get("jobs", 0)
    return [
        Check("boot", CheckStatus.OK, "the app starts"),
        Check("job-discovery", CheckStatus.INFO, f"{jobs} discovered from {cwd}"),
    ]


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
    checks.extend(_check_boot(where))
    checks.append(_check_terminal())
    return DoctorReport(tuple(checks))


_GLYPH = {
    CheckStatus.OK: "ok",
    CheckStatus.INFO: "  ",
    CheckStatus.WARNING: "!!",
    CheckStatus.CRITICAL: "XX",
}


def render_report_text(report: DoctorReport) -> list[str]:
    width = max((len(c.name) for c in report.checks), default=0)
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
