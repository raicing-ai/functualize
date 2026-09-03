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
from typing import TYPE_CHECKING, Any

from functualize._cli.runtime import Detection, InstallMode

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

__all__ = [
    "LossyReceiptError",
    "MissingToolError",
    "Requirement",
    "capture_environment",
    "install_commands",
    "names_to_restore",
    "normalize",
    "update_commands",
]

_PENDING_NAME = "pending-update.json"

#: Receipt keys this module knows how to render back into a PEP 508 string.
#: A key outside this set is a *refusal*, never a silent drop — see
#: :class:`LossyReceiptError`.
_KNOWN_REQUIREMENT_KEYS = frozenset({"name", "extras", "specifier", "url", "marker"})


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

    def to_pep508(self) -> str:
        """Reconstruct the requirement string uv was originally given.

        Raises:
            LossyReceiptError: the entry carries a key this cannot render.
        """
        if self.unknown_keys:
            raise LossyReceiptError(
                f"the uv receipt entry for {self.name!r} carries "
                f"{', '.join(self.unknown_keys)}, which this version cannot "
                f"reproduce."
            )
        text = self.name
        extras = self.fields.get("extras")
        if isinstance(extras, list) and extras:
            text += "[" + ",".join(str(e) for e in extras) + "]"
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
    primary = distribution
    extra_requirements: list[str] = []
    python: str | None = None

    if receipt is not None:
        python = receipt.python
        target = normalize(distribution)
        for requirement in receipt.requirements:
            rendered = requirement.to_pep508()
            if normalize(requirement.name) == target:
                primary = rendered
            else:
                extra_requirements.append(rendered)

    if normalize(package) != normalize(primary.split("[")[0].split(" ")[0]) and not any(
        normalize(package) == normalize(r.split("[")[0].split(" ")[0])
        for r in extra_requirements
    ):
        extra_requirements.append(package)

    args: list[str] = ["tool", "install", primary]
    for requirement in extra_requirements:
        args += ["--with", requirement]
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
    primary = distribution
    extra_requirements: list[str] = []
    python: str | None = None
    target = normalize(package)

    if receipt is not None:
        python = receipt.python
        owner = normalize(distribution)
        for requirement in receipt.requirements:
            if normalize(requirement.name) == target:
                continue
            rendered = requirement.to_pep508()
            if normalize(requirement.name) == owner:
                primary = rendered
            else:
                extra_requirements.append(rendered)

    args: list[str] = ["tool", "install", primary]
    for requirement in extra_requirements:
        args += ["--with", requirement]
    if python:
        args += ["--python", python]
    return tuple(args)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def render(argv: Sequence[str]) -> str:
    """One shell-ish line, for printing a command before it is run."""
    parts: list[str] = []
    for token in argv:
        parts.append(f'"{token}"' if " " in token else token)
    return " ".join(parts)


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
