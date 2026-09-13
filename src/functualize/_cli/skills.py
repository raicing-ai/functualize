"""Agent skills that ship with functualize: locate, read, and materialize them.

Functualize ships Agent Skills — ``SKILL.md`` directories teaching a coding
agent the contracts that are invisible from the file it is editing. They are
*framework-owned*: regenerated on upgrade, never hand-edited in place, which is
why they are not a scaffold template (ADR-006 §3).

Two locations matter and the distinction is the whole design:

``skills/`` (repo) / ``functualize/_skills`` (wheel)
    The single source of truth, carried inside the installed distribution. Its
    content is exactly the version of functualize the caller is running, so a
    skill read from here can never describe a different release.

``$XDG_DATA_HOME/functualize/skills/func-<version>/`` (materialized)
    A copy, written on demand. Worth having because the wheel's own directory
    lives inside an environment that may be ephemeral (``uvx``, a PEP 723
    script env, a rebuilt venv) and cannot be pointed at from a project that
    does not depend on functualize. Version-stamped so several installs
    coexist, and disposable by construction.

The version goes in the *parent* directory, never in the skill directory name:
the Agent Skills spec requires a skill's ``name`` to equal its directory name,
so ``…/func-0.1.0/functualize/SKILL.md`` is conformant and
``…/functualize-0.1.0/SKILL.md`` is not.

Stdlib-only and dependency-free on purpose — this module is reachable from
``func --help`` and must not pull anything heavy in.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "CORE_DIRECTORY_STEM",
    "SKILLS_ENTRY_POINT_GROUP",
    "SKILLS_PACKAGE_DIRNAME",
    "SkillInfo",
    "SkillsLocation",
    "directory_stem",
    "list_skills",
    "materialize_skills",
    "materialized_root",
    "parse_frontmatter",
    "read_skill",
    "resolve_skills_dir",
    "resolve_skills_locations",
]

#: Directory name the skills are force-included under inside the wheel.
#: Mirrored by ``[tool.hatch.build.targets.wheel.force-include]`` in
#: pyproject.toml; a test asserts the two agree.
SKILLS_PACKAGE_DIRNAME = "_skills"


@dataclass(frozen=True)
class SkillInfo:
    """One skill directory, as described by its own frontmatter."""

    name: str
    description: str
    version: str | None
    path: Path

    @property
    def summary(self) -> str:
        """The description collapsed onto one line, for terminal listing."""
        return " ".join(self.description.split())


@dataclass(frozen=True)
class SkillsLocation:
    """Where the skills came from, and whether that is the packaged copy.

    ``origin`` is reported rather than inferred by the caller because the
    cases have different guarantees: ``package`` is pinned to the running
    version, ``checkout`` is whatever the working tree currently says, and
    ``entry-point`` belongs to somebody else's distribution entirely.

    ``distribution`` and ``version`` exist for the last of those. The module
    docstring's promise -- *a skill read from here can never describe a
    different release* -- has to hold for a third-party skill too, and it only
    does if the stamp comes from **that** package's version rather than from
    functualize's. A shared stamp would quietly break the one guarantee this
    module is for.
    """

    path: Path
    origin: str  # "package" | "checkout" | "entry-point"
    distribution: str = "functualize"
    version: str = ""

    @property
    def is_packaged(self) -> bool:
        return self.origin == "package"


def resolve_skills_dir() -> SkillsLocation | None:
    """Locate the skills directory belonging to the running functualize.

    Tried in order:

    1. ``<package>/_skills`` — an installed wheel or sdist. Authoritative.
    2. ``<repo>/skills`` — an editable install or a source checkout, where the
       build-time force-include has not run. Reported as ``checkout`` so the
       caller can say so rather than implying a version guarantee it does not
       have.

    Returns None when neither exists, which is a real state: a stripped-down
    install, or a checkout with the directory removed.
    """
    package_dir = Path(__file__).resolve().parent.parent
    packaged = package_dir / SKILLS_PACKAGE_DIRNAME
    if packaged.is_dir():
        return SkillsLocation(packaged, "package")

    # src-layout checkout: <repo>/src/functualize/_cli/skills.py → <repo>/skills
    checkout = package_dir.parent.parent / "skills"
    if checkout.is_dir():
        return SkillsLocation(checkout, "checkout")

    return None


#: The entry-point group a third-party distribution declares to host skills:
#:
#:     [project.entry-points."functualize.skills"]
#:     mypackage = "mypackage._skills"
#:
#: The value is an importable package whose directory holds skill directories
#: -- the same shape as functualize's own ``_skills/``.
SKILLS_ENTRY_POINT_GROUP = "functualize.skills"


def _functualize_version() -> str:
    from functualize import __version__

    return __version__


def _entry_point_locations() -> list[SkillsLocation]:
    """Every third-party skills directory declared through the entry point.

    A malformed or missing entry is **warned about and skipped**, never fatal.
    This path is reachable from ``func --help``, so one broken third-party
    package must not be able to take the whole CLI down.

    Resolution uses ``importlib.resources`` rather than a path relative to
    ``__file__``: the target package may be zipped, and a host has no reason to
    replicate functualize's own layout assumptions.
    """
    # Deliberate exception to the `_primitives.entry_points` cache: `_cli`
    # may not import internal packages (import-linter contract, same note as
    # `plugin_cmd.py`), and no public seam re-exports the cached helper. This
    # also needs `version()` per distribution, which the cache does not cover.
    import logging
    from importlib.metadata import entry_points, version

    logger = logging.getLogger(__name__)
    locations: list[SkillsLocation] = []

    try:
        found = entry_points(group=SKILLS_ENTRY_POINT_GROUP)
    except Exception as exc:  # pragma: no cover - importlib is very stable
        logger.warning(
            "Could not read %s entry points: %s", SKILLS_ENTRY_POINT_GROUP, exc
        )
        return locations

    for entry in sorted(found, key=lambda e: e.name):
        try:
            from importlib.resources import files

            directory = Path(str(files(entry.value)))
            if not directory.is_dir():
                raise NotADirectoryError(directory)
            distribution = (
                getattr(getattr(entry, "dist", None), "name", None) or entry.name
            )
            locations.append(
                SkillsLocation(
                    directory,
                    "entry-point",
                    distribution=distribution,
                    version=version(distribution),
                )
            )
        except Exception as exc:
            logger.warning(
                "Skipping skills entry point %r (%s): %s", entry.name, entry.value, exc
            )

    return locations


def resolve_skills_locations() -> list[SkillsLocation]:
    """Core's own location first, then every registered entry point.

    Core first because it is the one location with a guaranteed shape, and
    because ``list``/``path``/``materialize`` all present it as the primary
    answer. An empty list is a real state: a stripped-down install with no
    third-party hosts.
    """
    locations: list[SkillsLocation] = []
    own = resolve_skills_dir()
    if own is not None:
        locations.append(
            SkillsLocation(
                own.path,
                own.origin,
                distribution="functualize",
                version=_functualize_version(),
            )
        )
    locations.extend(_entry_point_locations())
    return locations


def parse_frontmatter(text: str) -> dict[str, object]:
    """Parse the YAML frontmatter subset the Agent Skills spec actually uses.

    Deliberately not a YAML parser. The spec defines six scalar-or-map fields,
    and this reads exactly them: ``key: value``, folded (``>``) and literal
    (``|``) block scalars, and a one-level nested map (``metadata:``). Anything
    it cannot read is anything we should not be authoring, and the conformance
    suite asserts that by round-tripping every shipped skill through here.

    Avoiding a YAML dependency keeps ``func --help`` free of one.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    try:
        end = next(
            i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"
        )
    except StopIteration:
        return {}

    result: dict[str, object] = {}
    body = lines[1:end]
    i = 0
    while i < len(body):
        line = body[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if line[:1].isspace():  # continuation handled by its owner below
            i += 1
            continue
        key, _, raw = line.partition(":")
        key = key.strip()
        raw = raw.strip()
        i += 1

        if raw in (">", "|", ">-", "|-"):
            collected: list[str] = []
            while i < len(body) and (not body[i].strip() or body[i][:1].isspace()):
                collected.append(body[i].strip())
                i += 1
            joiner = "\n" if raw.startswith("|") else " "
            result[key] = joiner.join(c for c in collected if c).strip()
        elif raw == "":
            nested: dict[str, str] = {}
            while i < len(body) and (not body[i].strip() or body[i][:1].isspace()):
                if body[i].strip():
                    nkey, _, nval = body[i].strip().partition(":")
                    nested[nkey.strip()] = nval.strip().strip('"').strip("'")
                i += 1
            result[key] = nested
        else:
            result[key] = raw.strip('"').strip("'")

    return result


def read_skill(directory: Path) -> SkillInfo | None:
    """Read one skill directory, or None when it has no readable SKILL.md."""
    skill_md = directory / "SKILL.md"
    if not skill_md.is_file():
        return None

    try:
        front = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
    except OSError:
        return None

    name = front.get("name")
    if not isinstance(name, str) or not name:
        return None

    description = front.get("description")
    metadata = front.get("metadata")
    version = None
    if isinstance(metadata, dict):
        raw_version = metadata.get("version")
        version = raw_version if isinstance(raw_version, str) else None

    return SkillInfo(
        name=name,
        description=description if isinstance(description, str) else "",
        version=version,
        path=directory,
    )


def list_skills(root: Path) -> list[SkillInfo]:
    """Every readable skill directly under ``root``, ordered by name."""
    found = [
        info
        for child in sorted(root.iterdir())
        if child.is_dir() and (info := read_skill(child)) is not None
    ]
    return sorted(found, key=lambda s: s.name)


#: What core's own materialized tree is stamped with. Not ``functualize-``:
#: agent configs already point at ``func-<version>``, and renaming it would
#: break every one of them for no gain (`tasks.md` 4.2).
CORE_DIRECTORY_STEM = "func"


def directory_stem(distribution: str) -> str:
    """The parent-directory prefix a distribution's skills materialize under.

    Core keeps ``func-``; everyone else is stamped with their own name, so two
    hosts shipping a skill of the same name land in different trees and the
    version in the path is *that host's* version rather than functualize's.
    """
    return CORE_DIRECTORY_STEM if distribution == "functualize" else distribution


def materialized_root(version: str, distribution: str = "functualize") -> Path:
    """Where ``materialize_skills`` writes for a given distribution + version."""
    from functualize.app.utils import resolve_user_data_dir

    stem = directory_stem(distribution)
    return resolve_user_data_dir() / "skills" / f"{stem}-{version}"


def materialize_skills(
    source: Path,
    version: str,
    *,
    prune: bool = False,
    distribution: str = "functualize",
) -> tuple[Path, list[str]]:
    """Copy the packaged skills into the XDG data directory.

    The destination is replaced wholesale rather than merged: these files are
    framework-owned, and a merge would preserve a skill deleted upstream while
    claiming the tree matches the installed version.

    Args:
        source: Directory holding the skill directories (from
            :func:`resolve_skills_dir`).
        version: The version to stamp the parent directory with, so several
            installs coexist. **The owning distribution's version**, not
            functualize's — see :class:`SkillsLocation`.
        prune: Also delete materialized trees for *other* versions. Off by
            default — an older tree may still be referenced by a project whose
            agent config points at it.
        distribution: Who owns these skills. Decides the directory stem, so a
            third-party host never overwrites core's tree or another host's.

    Returns:
        The destination directory and the names of the skills written.
    """
    destination = materialized_root(version, distribution)
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    names: list[str] = []
    for skill in list_skills(source):
        shutil.copytree(skill.path, destination / skill.name)
        names.append(skill.name)

    if prune:
        # Only this distribution's other versions. Pruning by a bare `func-`
        # prefix would have one host delete another's tree, which is the
        # failure per-source stamping exists to prevent.
        prefix = f"{directory_stem(distribution)}-"
        for sibling in destination.parent.iterdir():
            if (
                sibling.is_dir()
                and sibling != destination
                and sibling.name.startswith(prefix)
            ):
                shutil.rmtree(sibling)

    return destination, names
