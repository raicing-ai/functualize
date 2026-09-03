"""Package operations against the environment this installation owns.

Everything here answers one of two questions:

- **what command would change this installation**, given how it was installed
  and which distribution owns it; and
- **what did the environment look like**, so an update that rebuilds it can put
  the user's own additions back.

Both are shared. ``self install`` and ``plugin install`` are the same mechanism
with different bookkeeping (`contracts.md` §1), so the command planning lives
here rather than in either command module, and neither one owns it.

**Nothing in this module executes anything except through :func:`_call`.** That
is deliberate: it is the single seam a test replaces to exercise a mutating
command without mutating the developer's real installation.

This module is in the ``_cli/`` layer — stdlib + ``_cli`` siblings + public API.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

from functualize._cli.runtime import Detection, InstallMode
from functualize.app.utils import ExitCode

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

__all__ = [
    "LossyReceiptError",
    "MissingToolError",
    "Requirement",
    "announce",
    "capture_environment",
    "install_commands",
    "names_to_restore",
    "normalize",
    "plan_or_exit",
    "refuse",
    "uninstall_commands",
    "update_commands",
]

_PENDING_NAME = "pending-update.json"

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


# ---------------------------------------------------------------------------
# Mode to commands
# ---------------------------------------------------------------------------


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
    distribution = detection.owning_distribution
    if detection.degraded or distribution is None:
        raise ValueError(f"{detection.mode.value} installations are not self-managing")

    match detection.mode:
        case InstallMode.STANDALONE:
            # PyApp's own updater, reachable at the renamed self-command
            # (`PYAPP_SELF_COMMAND=pyapp`). It replaces the binary in place.
            return ((binary_path, "pyapp", "update"),)
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
    distribution = detection.owning_distribution
    if detection.degraded or distribution is None:
        raise ValueError(f"{detection.mode.value} installations are not self-managing")

    match detection.mode:
        case InstallMode.STANDALONE:
            # `--python` targets the bundled interpreter explicitly. Without it
            # uv picks a Python by its own discovery rules, which in a shell
            # with an activated venv is somebody else's environment.
            return (
                (resolve_uv(), "pip", "install", "--python", owned_python(), package),
            )
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
    distribution = detection.owning_distribution
    if detection.degraded or distribution is None:
        raise ValueError(f"{detection.mode.value} installations are not self-managing")

    match detection.mode:
        case InstallMode.STANDALONE:
            return (
                (resolve_uv(), "pip", "uninstall", "--python", owned_python(), package),
            )
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


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def render(argv: Sequence[str]) -> str:
    """One shell-ish line, for printing a command before it is run."""
    parts: list[str] = []
    for token in argv:
        parts.append(f'"{token}"' if " " in token else token)
    return " ".join(parts)


def script_name() -> str:
    """The console script the user actually typed, for use in guidance.

    Never a hard-coded ``func``: in a consumer application this text has to
    name *that* application's script or it tells the user to run a command they
    do not have.
    """
    argv0 = sys.argv[0] if sys.argv else ""
    name = argv0.replace("\\", "/").rsplit("/", 1)[-1]
    return name or "func"


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
