"""How this ``func`` was installed, and which distribution owns it.

Two independent facts, answered together because every self-management command
needs both and resolving one without the other is how a command ends up naming
the wrong tool:

- **environment kind** — a downloaded binary, a uv tool, a pipx tool, a project
  checkout, or one of two degraded shapes;
- **owning distribution** — which distribution provides the console script that
  is running. For ``func`` that is ``functualize``; for an application built on
  functualize it is *that application*, because ``CliAdapter`` mounts the whole
  ``builtin`` subtree into it by default.

The point of knowing both is refusal. An installation whose owner cannot be
determined gets guidance and a non-zero exit, never a guess: a wrong guess
prints commands that do not exist and runs updaters against binaries they do
not own.

This module is in the ``_cli/`` layer — stdlib + ``_cli`` siblings only.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["Detection", "InstallMode", "RuntimeOverrideError", "detect"]

#: How far up from the working directory rung 5 looks for a project that
#: declares functualize. Bounded on purpose: the rung is a directory walk plus
#: a TOML parse on a path whose whole budget is a few microseconds, and an
#: unbounded walk is the shape that once cost 63% of boot
#: (``contributor/reference/pitfalls.md`` #16).
_PROJECT_WALK_LIMIT = 6

#: The environment variable a test or CI job sets to pin the answer.
_OVERRIDE_VAR = "FUNCTUALIZE_RUNTIME"


class InstallMode(StrEnum):
    """The vocabulary that reaches JSON output and the override variable.

    A :class:`~enum.StrEnum` so members serialize to the documented spelling
    without a translation table. Named ``InstallMode`` and never ``Mode``: ``_cli.dispatch``
    already exports a live ``Mode`` whose members include ``UNKNOWN``, and the
    two sit one import apart.
    """

    STANDALONE = "standalone"
    TOOL_UV = "tool_uv"
    TOOL_PIPX = "tool_pipx"
    PROJECT = "project"
    TOOL_PIP = "tool_pip"
    UNKNOWN = "unknown"

    @property
    def degraded(self) -> bool:
        """Whether functualize declines to manage this installation.

        Derived rather than stored: this is the sole input to the refusal
        branch, so it gets exactly one definition.
        """
        return self in (InstallMode.TOOL_PIP, InstallMode.UNKNOWN)


class RuntimeOverrideError(ValueError):
    """``FUNCTUALIZE_RUNTIME`` was set to something that is not a mode.

    Raised rather than ignored. A silent fallback would report a mistyped CI
    variable as a degraded installation — a real-looking answer to a question
    nobody asked.
    """


@dataclass(frozen=True)
class Detection:
    """The pair every mutating command needs before it can name a tool."""

    mode: InstallMode
    #: ``None`` when ``argv0`` maps to no installed distribution — a ``python
    #: -m`` invocation, a renamed script, a source checkout run in place.
    #: Nullable on purpose: guessing ``functualize`` here is precisely the
    #: wrong-owner failure this module exists to prevent, so ``None`` forces
    #: the refusal path.
    owning_distribution: str | None
    #: The standalone binary's own absolute path, as PyApp reports it in
    #: ``PYAPP`` when built with ``PYAPP_PASS_LOCATION=1``. ``None`` for every
    #: other mode, and for a standalone binary built without that flag or whose
    #: ``current_exe()`` lookup failed.
    standalone_binary: str | None = None

    @property
    def degraded(self) -> bool:
        """Either the environment or the owner is unusable for management."""
        if self.mode is InstallMode.STANDALONE:
            # A standalone binary has no owning distribution *by construction*
            # -- it is a file, not a package -- so the absence that degrades
            # every other mode says nothing here. What a mutating command needs
            # is the executable to act on, and PyApp launches the application
            # through `python -c`, so `argv[0]` is the literal string `-c` and
            # can never supply it. The binary's own path is the discriminator.
            return self.standalone_binary is None
        return self.mode.degraded or self.owning_distribution is None


def _uv_tools_dir(environ: Mapping[str, str]) -> Path | None:
    """Where ``uv tool install`` puts its environments, per ``uv tool dir``."""
    explicit = environ.get("UV_TOOL_DIR", "")
    if explicit:
        return Path(explicit)
    xdg_data = environ.get("XDG_DATA_HOME", "")
    if xdg_data:
        return Path(xdg_data) / "uv" / "tools"
    home = environ.get("HOME", "")
    if home:
        return Path(home) / ".local" / "share" / "uv" / "tools"
    return None


def _is_under(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
    except ValueError:
        return False
    return True


def _declares_functualize(pyproject: Path) -> bool:
    """Does this ``pyproject.toml`` name functualize as a dependency?

    Unreadable or malformed files answer ``False``. A project whose manifest
    cannot be parsed is not evidence of anything, and detection must not raise
    into a command that merely wanted to know how it was installed.
    """
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return False

    project = data.get("project")
    if isinstance(project, dict):
        deps = project.get("dependencies")
        if isinstance(deps, list) and any(
            isinstance(d, str) and d.lower().startswith("functualize") for d in deps
        ):
            return True
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            for group in optional.values():
                if isinstance(group, list) and any(
                    isinstance(d, str) and d.lower().startswith("functualize")
                    for d in group
                ):
                    return True
    # A project configuring functualize is using it, whether or not the
    # dependency is declared here (a workspace member, an editable install).
    tool = data.get("tool")
    return isinstance(tool, dict) and "functualize" in tool


def _walk_to_project(cwd: Path) -> bool:
    """Rung 5: is there a nearby project that declares functualize?

    **This is the only rung that touches the filesystem, and it stays last of
    the non-trivial ones for that reason.** Rungs 1-4 are environment and
    string comparisons that answer first in every non-project case, so the
    walk is reached only when nothing cheaper matched.
    """
    current = cwd
    for _ in range(_PROJECT_WALK_LIMIT):
        if _declares_functualize(current / "pyproject.toml"):
            return True
        if current.parent == current:
            break
        current = current.parent
    return False


def _owning_distribution(argv0: str) -> str | None:
    """Which distribution provides the console script that is running.

    Reverse-mapped from ``argv0``'s basename through installed metadata, so a
    scaffolded application's own script resolves to *that application* rather
    than to functualize.
    """
    # Split on both separators rather than via `Path`: `argv0` carries the
    # *invoking* platform's convention, and `PurePosixPath` would treat a
    # Windows `argv0` as one long filename.
    name = argv0.replace("\\", "/").rsplit("/", 1)[-1]
    if not name:
        return None
    # Strip a Windows extension so `weather-app.exe` matches its script entry.
    if name.lower().endswith(".exe"):
        name = name[: -len(".exe")]

    from importlib.metadata import distributions

    for dist in distributions():
        try:
            entries = dist.entry_points
        except Exception:  # pragma: no cover - unreadable metadata on disk
            continue
        for entry in entries:
            if entry.group == "console_scripts" and entry.name == name:
                dist_name = dist.metadata["Name"]
                return str(dist_name) if dist_name else None
    return None


def detect(
    prefix: str,
    base_prefix: str,
    environ: Mapping[str, str],
    argv0: str,
    cwd: Path,
) -> Detection:
    """Resolve both axes from supplied inputs.

    Every input is a parameter rather than a module-level read, and that is a
    testability requirement rather than a style preference: ``sys.prefix``
    cannot be set by an environment variable, so a version reading it directly
    could only ever be exercised in the single mode the test suite happens to
    run under.

    ``cwd`` is a parameter for the same reason — rung 5 needs a starting
    directory, and taking it as an argument keeps the walk addressable from a
    test without a process-wide ``chdir``.

    Args:
        prefix: ``sys.prefix`` of the running interpreter.
        base_prefix: ``sys.base_prefix``.
        environ: the process environment.
        argv0: ``sys.argv[0]`` — the console script that was invoked.
        cwd: where to start rung 5's bounded upward walk.

    Raises:
        RuntimeOverrideError: ``FUNCTUALIZE_RUNTIME`` names no known mode.
    """
    return Detection(
        mode=_detect_mode(prefix, base_prefix, environ, cwd),
        owning_distribution=_owning_distribution(argv0),
        standalone_binary=_standalone_binary(environ, argv0),
    )


def _standalone_binary(environ: Mapping[str, str], argv0: str) -> str | None:
    """The running executable's path, for a standalone installation.

    ``PYAPP`` holds the absolute path only when the binary was built with
    ``PYAPP_PASS_LOCATION=1``; older builds set the literal ``"1"`` and a build
    whose ``current_exe()`` failed sets the empty string. Both are "unknown",
    not a path — returning ``"1"`` here would have every mutating command
    operate on a file named ``1`` in the working directory.

    ``argv0`` is the second rung, and it is not a fallback guess. Inside a real
    PyApp binary it is the literal string ``-c`` and this rung cannot fire. It
    fires only when the mode was pinned with ``FUNCTUALIZE_RUNTIME=standalone``
    — where ``argv0`` genuinely *is* the command that ran — which is what keeps
    that override useful rather than a way to manufacture a degraded install.
    """
    value = environ.get("PYAPP", "")
    if value and value != "1":
        return value
    if argv0 and argv0 != "-c":
        return argv0
    return None


def _detect_mode(
    prefix: str,
    base_prefix: str,
    environ: Mapping[str, str],
    cwd: Path,
) -> InstallMode:
    """The ladder. First match wins; cheapest signals first."""
    # 1. An explicit override, for CI and tests.
    override = environ.get(_OVERRIDE_VAR, "")
    if override:
        try:
            return InstallMode(override)
        except ValueError:
            raise RuntimeOverrideError(
                f"{_OVERRIDE_VAR}={override!r} is not a known install mode. "
                f"Expected one of: {', '.join(m.value for m in InstallMode)}"
            ) from None

    # 2. The binary announces itself: PyApp injects PYAPP into its runtime --
    #    the executable's own path under `PYAPP_PASS_LOCATION=1`, otherwise
    #    "1". Membership, not truthiness: PyApp sets it to the *empty string*
    #    when `current_exe()` fails (`distribution.rs:56`), and a binary that
    #    cannot name itself is still a standalone binary. Reading that as
    #    "not standalone" would send it down the project or unknown rungs and
    #    describe it as something it is not.
    if "PYAPP" in environ or environ.get("PYAPP_COMMAND_NAME"):
        return InstallMode.STANDALONE

    prefix_path = Path(prefix)

    # 3. uv tools. `sys.prefix`, never VIRTUAL_ENV — the latter is set by shell
    #    *activation*, and a uv-tool binary runs through a shebang without it.
    uv_tools = _uv_tools_dir(environ)
    if uv_tools is not None and _is_under(prefix_path, uv_tools):
        return InstallMode.TOOL_UV

    # 4. pipx. PIPX_HOME is deliberately not consulted: it is unset for a
    #    default install, so its absence would prove nothing.
    parts = prefix_path.parts
    if "pipx" in parts and "venvs" in parts:
        return InstallMode.TOOL_PIPX

    # 5. The one filesystem rung — see `_walk_to_project`.
    if _walk_to_project(cwd):
        return InstallMode.PROJECT

    # 6. No virtual environment at all: bare pip into a system interpreter.
    if prefix == base_prefix:
        return InstallMode.TOOL_PIP

    # 7. An unrecognised virtual environment. Never `standalone`: a dev
    #    checkout falling through to that would be handed bundled-uv commands
    #    which do not exist.
    return InstallMode.UNKNOWN


def detect_from_process(cwd: Path | None = None) -> Detection:
    """:func:`detect` against the running process. The production entry point."""
    import sys

    return detect(
        prefix=sys.prefix,
        base_prefix=sys.base_prefix,
        environ=os.environ,
        argv0=sys.argv[0] if sys.argv else "",
        cwd=cwd if cwd is not None else Path.cwd(),
    )
