"""How this ``func`` was installed, who owns it, and what would change it.

Three facts, answered together because every self-management command needs all
three and resolving one without the others is how a command ends up naming the
wrong tool:

- **environment kind** — a downloaded binary, a uv tool, a pipx tool, a project
  checkout, or one of two degraded shapes;
- **owning distribution** — which distribution provides the console script that
  is running. For ``func`` that is ``functualize``; for an application built on
  functualize it is *that application*, because ``CliAdapter`` mounts the whole
  ``builtin`` subtree into it by default;
- **the command that would change it** — the exact argv that upgrades this
  installation, adds a package to it, or removes one, assembled from the
  resolved manager and the owning distribution.

The point of knowing the first two is refusal. An installation whose owner
cannot be determined gets guidance and a non-zero exit, never a guess: a wrong
guess prints commands that do not exist and runs updaters against binaries they
do not own.

The third is a pure function of the first two, which is why it lives beside
them rather than in a command module — planning against one installation and
running against another is the failure that separation invites. ``self
install`` and ``plugin install`` are the same mechanism with different
bookkeeping (`contracts.md` §1), so neither of them owns it.

**Planning is public; deciding and executing are not.** Nothing here prints,
prompts, or runs a subprocess -- every function returns a command tuple or
raises. The confirmation prompt, the refusal message and the single
``subprocess.call`` seam stay in ``_cli/package_ops.py``, which is what keeps
this module importable by a host that has no terminal and no CLI framework
installed. ``tests/app/test_packaging.py`` asserts that absence rather than
trusting it.

This module is **public**: a package built on functualize asks it whether a
tool is installed, how, and where, rather than shipping a second detector
that disagrees. It is stdlib-only, so nothing CLI travels with it -- which is
what made promoting it a move rather than a rewrite.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import sysconfig
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = [
    "Detection",
    "InstallMode",
    "LossyReceiptError",
    "MissingToolError",
    "Receipt",
    "Requirement",
    "RuntimeOverrideError",
    "StandaloneUpdateError",
    "capture",
    "capture_environment",
    "detect",
    "detect_from_process",
    "drop_from_receipt",
    "install_commands",
    "merge_receipt",
    "names_to_restore",
    "normalize",
    "owned_python",
    "read_receipt",
    "resolve_pipx",
    "resolve_uv",
    "uninstall_commands",
    "update_commands",
]

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


#: Receipt keys this module knows how to render back into a PEP 508 string.
#: A key outside this set is a *refusal*, never a silent drop — see
#: :class:`LossyReceiptError`.
_KNOWN_REQUIREMENT_KEYS = frozenset(
    {
        "name",
        "extras",
        "specifier",
        "url",
        "marker",
        # A path install: `uv tool install "/src[cli]"` writes
        # `{name = "functualize", extras = ["cli"], directory = "/src"}`. Found
        # by running `plugin install` in a real container, where the merge
        # correctly refused rather than silently reinstalling from the index.
        "directory",
        "editable",
    }
)


class MissingToolError(RuntimeError):
    """The external tool this mode's commands are built from is not present.

    Distinct from a refusal: the installation *is* manageable, the manager is
    just not on this machine. Callers map it to the usage exit code, which
    ``contracts.md`` §2 already assigns to "a required external tool is absent".
    """


class LossyReceiptError(RuntimeError):
    """A uv receipt carries a key this module cannot render back.

    Raised rather than dropped. ``uv tool install`` is *declarative*: it
    rewrites the receipt from the arguments it is given, so a requirement this
    module fails to reproduce is not merely missing from one command — it is
    removed from the tool environment. A receipt entry pinning a git URL or a
    future key silently becoming a plain name change what is installed.

    The escape hatch is the honest answer here: ``self uv -- tool install …``
    lets the user drive uv directly with the arguments they choose.
    """


def normalize(name: str) -> str:
    """PEP 503 normalization, so two spellings of one package compare equal.

    Load-bearing for reconciliation: ``dist-info`` directories spell names with
    underscores (``functualize_http``) while manifests and users spell them with
    hyphens. Comparing the two raw makes **every** hyphenated package look like
    a user addition that the update removed.
    """
    return re.sub(r"[-_.]+", "-", name).strip().lower()


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


def _site_dirs() -> tuple[Path, ...]:
    """Where this interpreter's installed distributions live."""
    paths = sysconfig.get_paths()
    seen: set[str] = set()
    dirs: list[Path] = []
    for key in ("purelib", "platlib"):
        raw = paths.get(key)
        if raw and raw not in seen:
            seen.add(raw)
            dirs.append(Path(raw))
    return tuple(dirs)


def capture(site_dirs: Iterable[Path]) -> dict[str, str]:
    """Map normalized name to version by reading ``*.dist-info`` **names**.

    Never by opening package metadata. Measured on a 214-distribution
    environment (`schema.md`): parsing directory names costs 2.4 ms, while
    ``Distribution.metadata["Name"]`` costs 172 ms for the same mapping the
    directory name already encodes. An update pays this twice.

    A directory that does not parse is skipped rather than raising — a stray
    entry must not make an update refuse to reconcile.
    """
    found: dict[str, str] = {}
    for directory in site_dirs:
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.name.endswith(".dist-info"):
                continue
            stem = entry.name[: -len(".dist-info")]
            name, _, version = stem.rpartition("-")
            if not name:
                continue
            found[normalize(name)] = version
    return found


def capture_environment() -> dict[str, str]:
    """:func:`capture` over the running interpreter's own site directories.

    The running interpreter *is* the owned environment in every non-degraded
    mode — ``func`` is a console script installed into it — so no child process
    is needed to look at it.
    """
    return capture(_site_dirs())


def names_to_restore(
    before: dict[str, str],
    after: dict[str, str],
    recorded: Iterable[str],
) -> tuple[str, ...]:
    """What the update removed that the user had added.

    **The difference is over names alone.** A distribution-shipped package
    appears in both captures at different versions after an upgrade; differencing
    over ``(name, version)`` pairs would classify it as a user addition and
    reinstall it at its *old* version, silently undoing the upgrade's own
    dependency updates (`spec.md` AC14g).

    The manifest's records are unioned in rather than trusted alone, and neither
    source is sufficient by itself: the capture catches escape-hatch installs the
    records never saw, and the records survive a capture that failed.

    Known imprecision, accepted: a transitive dependency the new version
    legitimately dropped is in ``before`` and not in ``after``, so it is
    restored. Distinguishing it would require a dependency resolution this has
    no way to perform, and the alternative — trusting the records alone — loses
    exactly the escape-hatch case the capture exists for.
    """
    candidates = {normalize(n) for n in before} | {normalize(n) for n in recorded}
    present = {normalize(n) for n in after}
    return tuple(sorted(candidates - present))


# ---------------------------------------------------------------------------
# uv receipts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Requirement:
    """One entry from a uv tool receipt's ``requirements`` list.

    ``fields`` holds the entry verbatim, including keys this module does not
    know. Named ``fields`` and **not** ``extras`` as the plan sketched it:
    ``extras`` is itself a real receipt key holding PEP 508 extras
    (``{name = "functualize", extras = ["cli"]}``), and one name for two things
    in a type whose whole job is faithful round-tripping is how a lossy parser
    gets written.
    """

    name: str
    fields: dict[str, Any]

    @property
    def unknown_keys(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.fields) - _KNOWN_REQUIREMENT_KEYS))

    @property
    def editable(self) -> bool:
        return bool(self.fields.get("editable"))

    def _check_renderable(self) -> None:
        if self.unknown_keys:
            raise LossyReceiptError(
                f"the uv receipt entry for {self.name!r} carries "
                f"{', '.join(self.unknown_keys)}, which this version cannot "
                f"reproduce."
            )

    def _extras_suffix(self) -> str:
        extras = self.fields.get("extras")
        if isinstance(extras, list) and extras:
            return "[" + ",".join(str(e) for e in extras) + "]"
        return ""

    def to_pep508(self) -> str:
        """Reconstruct the requirement string uv was originally given.

        A ``directory`` entry renders as **the path itself**, with its extras —
        ``/src[cli]`` — rather than as a ``name @ file://`` reference. That is
        literally what the user typed, uv accepts it, and it is the form that
        survives a re-resolve; a synthesised ``file://`` URL is a second
        spelling with its own edge cases and buys nothing.

        Raises:
            LossyReceiptError: the entry carries a key this cannot render, or
                is editable — see :meth:`install_args`.
        """
        self._check_renderable()
        if self.editable:
            raise LossyReceiptError(
                f"the uv receipt entry for {self.name!r} is an editable "
                f"install, which has no requirement-string form."
            )

        directory = self.fields.get("directory")
        if isinstance(directory, str) and directory:
            return f"{directory}{self._extras_suffix()}"

        text = self.name + self._extras_suffix()
        url = self.fields.get("url")
        specifier = self.fields.get("specifier")
        if isinstance(url, str) and url:
            text += f" @ {url}"
        elif isinstance(specifier, str) and specifier:
            text += specifier
        marker = self.fields.get("marker")
        if isinstance(marker, str) and marker:
            text += f" ; {marker}"
        return text

    def install_args(self, *, primary: bool) -> list[str]:
        """How this requirement is restated to ``uv tool install``.

        Editability is a **flag, not part of a requirement string**, so it
        cannot go through :meth:`to_pep508` at all: uv spells it ``--editable``
        for the tool itself and ``--with-editable`` for anything else. Rendering
        an editable entry as a plain path would reinstall it non-editably, which
        silently changes what is installed — the failure this whole
        reconstruction exists to avoid.

        Raises:
            LossyReceiptError: the entry carries a key this cannot render.
        """
        if self.editable:
            self._check_renderable()
            directory = self.fields.get("directory")
            if not isinstance(directory, str) or not directory:
                raise LossyReceiptError(
                    f"the uv receipt entry for {self.name!r} is editable but "
                    f"names no directory, so it cannot be reinstalled."
                )
            spec = f"{directory}{self._extras_suffix()}"
            return ["--editable", spec] if primary else ["--with-editable", spec]

        rendered = self.to_pep508()
        return [rendered] if primary else ["--with", rendered]


@dataclass(frozen=True)
class Receipt:
    """The parts of ``uv-receipt.toml`` a re-install has to carry forward."""

    requirements: tuple[Requirement, ...] = ()
    #: The receipt pins the interpreter the tool was installed against. Dropping
    #: it lets a re-install silently land on a different Python.
    python: str | None = None


def read_receipt(prefix: Path) -> Receipt | None:
    """Parse ``<prefix>/uv-receipt.toml``, or ``None`` when there is none."""
    try:
        data = tomllib.loads((prefix / "uv-receipt.toml").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    tool = data.get("tool")
    if not isinstance(tool, dict):
        return None
    entries = tool.get("requirements")
    requirements: list[Requirement] = []
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                requirements.append(Requirement(entry["name"], dict(entry)))
    python = tool.get("python")
    return Receipt(
        requirements=tuple(requirements),
        python=python if isinstance(python, str) else None,
    )


def merge_receipt(
    receipt: Receipt | None, distribution: str, package: str
) -> tuple[str, ...]:
    """Build a ``uv tool install`` argument list that adds ``package``.

    ``uv tool install`` is **declarative**: it rewrites the environment from the
    arguments given, and ``uv tool`` has no ``add``/``inject`` to delegate to.
    So every requirement already in the receipt has to be restated, or
    installing a second plugin uninstalls the first (`spec.md` AC17).

    Raises:
        LossyReceiptError: some entry cannot be reproduced faithfully.
    """
    return _rebuild(receipt, distribution, add=package, drop=None)


def _requirement_identity(requirement: Requirement) -> str:
    """What "the same package" means when deciding whether to add or drop one.

    The receipt's ``name`` field, never the rendered string: a path install
    renders as ``/src[cli]`` and matching on that would never recognise it as
    ``functualize``.
    """
    return normalize(requirement.name)


def _rebuild(
    receipt: Receipt | None,
    distribution: str,
    *,
    add: str | None,
    drop: str | None,
) -> tuple[str, ...]:
    """Restate a whole tool environment, with one package added or removed.

    One function for both directions because the hard part — reproducing every
    *other* requirement exactly — is identical, and two copies of it would
    drift.
    """
    owner = normalize(distribution)
    dropped = normalize(drop) if drop else None

    primary_args: list[str] = [distribution]
    rest_args: list[str] = []
    python: str | None = None
    present: set[str] = set()

    if receipt is not None:
        python = receipt.python
        for requirement in receipt.requirements:
            identity = _requirement_identity(requirement)
            if dropped is not None and identity == dropped:
                continue
            present.add(identity)
            if identity == owner:
                primary_args = requirement.install_args(primary=True)
            else:
                rest_args += requirement.install_args(primary=False)

    if add is not None and normalize(add) not in present:
        rest_args += ["--with", add]

    args = ["tool", "install", *primary_args, *rest_args]
    if python:
        args += ["--python", python]
    return tuple(args)


# ---------------------------------------------------------------------------
# Locating the tools a mode's commands are built from
# ---------------------------------------------------------------------------


def resolve_uv() -> str:
    """Absolute path to the ``uv`` this installation should drive.

    Nearest first: the ``UV`` variable uv exports to its own children, then a
    ``uv`` sitting beside the running interpreter — where both a project's own
    dependency and the binary's bundled copy land — and only then ``PATH``.

    Raises:
        MissingToolError: no uv anywhere.
    """
    explicit = os.environ.get("UV", "")
    if explicit and Path(explicit).exists():
        return os.path.abspath(explicit)
    parent = Path(sys.executable).parent
    for name in ("uv", "uv.exe"):
        candidate = parent / name
        if candidate.exists():
            return os.path.abspath(candidate)
    found = shutil.which("uv")
    if found:
        # Absolute, because `self uv` bare prints this for capture and a
        # relative path would resolve against the caller's directory.
        return os.path.abspath(found)
    raise MissingToolError(
        "uv is required to manage this installation but was not found. "
        "Install it from https://docs.astral.sh/uv/ and try again."
    )


def resolve_pipx() -> str:
    found = shutil.which("pipx")
    if found:
        return found
    raise MissingToolError(
        "pipx is required to manage this installation but was not found."
    )


def owned_python() -> str:
    """The interpreter of the environment this installation owns.

    Absolute but **not resolved**. A virtual environment's ``bin/python`` is a
    symlink to the base interpreter, and following it hands back a Python that
    cannot see a single one of the environment's packages — so
    ``self python -- -m pip list`` would report the wrong environment and
    ``self python -- -m mymodule`` would fail to import. The symlink *is* the
    environment; resolving it is leaving it.
    """
    return os.path.abspath(sys.executable)


def _bundled_pip() -> tuple[str, ...]:
    """The bundled interpreter's own pip, as a command prefix.

    Not uv. A standalone binary is the install method for a machine with no
    Python toolchain, so requiring ``uv`` on ``PATH`` before a package can be
    added defeats the reason it exists -- and PyApp's baked distribution ships
    no uv, so ``resolve_uv()`` would raise on the very install method that
    cannot fix it. pip is present in the distribution and the bake asserts so.

    ``-m pip`` rather than the ``pip`` script: the script's shebang is written
    at build time and points at the *build machine's* path, which is not where
    the distribution unpacks.
    """
    return (owned_python(), "-m", "pip")


# ---------------------------------------------------------------------------
# Mode to commands
# ---------------------------------------------------------------------------


class StandaloneUpdateError(Exception):
    """``self update`` on a standalone install is not a subprocess.

    Every other mode delegates to a package manager, so its update is a command
    tuple. A standalone binary is a single file, and updating it means
    downloading a release and replacing that file -- work that happens
    in-process, in :mod:`functualize._cli.self_update`. Raised rather than
    returned so a caller that forgets to handle it fails loudly instead of
    running an empty command list and reporting success.

    PyApp's own updater is not an option: it is hidden unless
    ``PYAPP_EXPOSE_UPDATE=1``, refuses outright under ``PYAPP_SKIP_INSTALL=1``
    (`"Cannot update as installation is disabled"`), and would ``pip install
    --upgrade`` from an index if it ran -- replacing the offline-complete
    environment the binary exists to be.
    """


def update_commands(
    detection: Detection, binary_path: str
) -> tuple[tuple[str, ...], ...]:
    """The commands that upgrade this installation, in order.

    A function rather than a table because each mode's command is assembled
    from resolved paths and the **owning distribution** — never a hard-coded
    ``functualize`` (`spec.md` AC31). A consumer application built on
    functualize upgrades *itself*, and naming the framework there would upgrade
    a package the user did not install and leave the application untouched.

    Raises:
        ValueError: the mode is degraded. Callers must check first; this is the
            backstop that keeps a refusal from silently becoming a command.
        MissingToolError: the mode's manager is not installed.
    """
    # Standalone is checked *before* the owner guard. It has no owning
    # distribution by construction -- it is a file, not a package -- so the
    # guard that protects every other mode from acting on a name it could not
    # resolve would refuse every healthy binary.
    if detection.mode is InstallMode.STANDALONE:
        if detection.standalone_binary is None:
            raise ValueError(
                "standalone installations cannot be updated without knowing "
                "their own path"
            )
        raise StandaloneUpdateError(detection.standalone_binary)

    distribution = detection.owning_distribution
    if detection.degraded or distribution is None:
        raise ValueError(f"{detection.mode.value} installations are not self-managing")

    match detection.mode:
        case InstallMode.TOOL_UV:
            return ((resolve_uv(), "tool", "upgrade", distribution),)
        case InstallMode.TOOL_PIPX:
            return ((resolve_pipx(), "upgrade", distribution),)
        case InstallMode.PROJECT:
            uv = resolve_uv()
            # Two commands: the lock has to move before the sync can install
            # anything new. `uv sync` alone would reinstall the pinned version.
            return (
                (uv, "lock", "--upgrade-package", distribution),
                (uv, "sync"),
            )
        case _:  # pragma: no cover - guarded by the degraded check above
            raise ValueError(f"no update command for {detection.mode.value}")


def install_commands(detection: Detection, package: str) -> tuple[tuple[str, ...], ...]:
    """The commands that add ``package`` to the owned environment.

    Shared by ``self install`` and ``plugin install`` — the two differ only in
    what they write to the manifest afterwards (`contracts.md` §1).

    Raises:
        ValueError: the mode is degraded.
        MissingToolError: the mode's manager is not installed.
        LossyReceiptError: a uv receipt could not be reproduced faithfully.
    """
    if detection.mode is InstallMode.STANDALONE:
        return ((*_bundled_pip(), "install", package),)

    distribution = detection.owning_distribution
    if detection.degraded or distribution is None:
        raise ValueError(f"{detection.mode.value} installations are not self-managing")

    match detection.mode:
        case InstallMode.TOOL_UV:
            uv = resolve_uv()
            receipt = read_receipt(Path(sys.prefix))
            return ((uv, *merge_receipt(receipt, distribution, package)),)
        case InstallMode.TOOL_PIPX:
            # pipx has a real injection verb, so no receipt reconstruction.
            return ((resolve_pipx(), "inject", distribution, package),)
        case InstallMode.PROJECT:
            return ((resolve_uv(), "add", package),)
        case _:  # pragma: no cover - guarded by the degraded check above
            raise ValueError(f"no install command for {detection.mode.value}")


def uninstall_commands(
    detection: Detection, package: str
) -> tuple[tuple[str, ...], ...]:
    """The commands that remove ``package`` from the owned environment.

    Raises:
        ValueError: the mode is degraded.
        MissingToolError: the mode's manager is not installed.
        LossyReceiptError: a uv receipt could not be reproduced faithfully.
    """
    if detection.mode is InstallMode.STANDALONE:
        return ((*_bundled_pip(), "uninstall", "-y", package),)

    distribution = detection.owning_distribution
    if detection.degraded or distribution is None:
        raise ValueError(f"{detection.mode.value} installations are not self-managing")

    match detection.mode:
        case InstallMode.TOOL_UV:
            uv = resolve_uv()
            receipt = read_receipt(Path(sys.prefix))
            return ((uv, *drop_from_receipt(receipt, distribution, package)),)
        case InstallMode.TOOL_PIPX:
            return ((resolve_pipx(), "uninject", distribution, package),)
        case InstallMode.PROJECT:
            return ((resolve_uv(), "remove", package),)
        case _:  # pragma: no cover - guarded by the degraded check above
            raise ValueError(f"no uninstall command for {detection.mode.value}")


def drop_from_receipt(
    receipt: Receipt | None, distribution: str, package: str
) -> tuple[str, ...]:
    """:func:`merge_receipt`'s inverse — restate everything *except* ``package``."""
    return _rebuild(receipt, distribution, add=None, drop=package)
