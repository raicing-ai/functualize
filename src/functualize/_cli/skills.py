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
    "SKILLS_PACKAGE_DIRNAME",
    "SkillInfo",
    "SkillsLocation",
    "list_skills",
    "materialize_skills",
    "materialized_root",
    "parse_frontmatter",
    "read_skill",
    "resolve_skills_dir",
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

    ``origin`` is reported rather than inferred by the caller because the two
    cases have different guarantees: ``package`` is pinned to the running
    version, ``checkout`` is whatever the working tree currently says.
    """

    path: Path
    origin: str  # "package" | "checkout"

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


def materialized_root(version: str) -> Path:
    """Where ``materialize_skills`` writes for a given functualize version."""
    from functualize.app.utils import resolve_user_data_dir

    return resolve_user_data_dir() / "skills" / f"func-{version}"


def materialize_skills(
    source: Path, version: str, *, prune: bool = False
) -> tuple[Path, list[str]]:
    """Copy the packaged skills into the XDG data directory.

    The destination is replaced wholesale rather than merged: these files are
    framework-owned, and a merge would preserve a skill deleted upstream while
    claiming the tree matches the installed version.

    Args:
        source: Directory holding the skill directories (from
            :func:`resolve_skills_dir`).
        version: The running functualize version, used to stamp the parent
            directory so several installs coexist.
        prune: Also delete materialized trees for *other* versions. Off by
            default — an older tree may still be referenced by a project whose
            agent config points at it.

    Returns:
        The destination directory and the names of the skills written.
    """
    destination = materialized_root(version)
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    names: list[str] = []
    for skill in list_skills(source):
        shutil.copytree(skill.path, destination / skill.name)
        names.append(skill.name)

    if prune:
        for sibling in destination.parent.iterdir():
            if (
                sibling.is_dir()
                and sibling != destination
                and sibling.name.startswith("func-")
            ):
                shutil.rmtree(sibling)

    return destination, names
