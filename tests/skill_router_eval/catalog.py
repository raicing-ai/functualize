"""The bounded catalog the skill router chooses from.

The catalog is derived from the checked-in ``skills/`` tree: exactly the
directories that hold a ``SKILL.md``, and nothing else. A tree that disagrees
with the declared tuple is an error rather than a silently wider choice set,
because the corpus and every measured number are stated against this set.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from tests.hermetic_eval.comparators import identity_sha256

SKILLS: tuple[str, ...] = (
    "functualize",
    "functualize-app",
    "functualize-cli",
    "functualize-skill",
)
NONE = "none"
OPTIONS: tuple[str, ...] = (*SKILLS, NONE)
NONE_MEANING = "No functualize skill applies; answer without loading one."

DEFAULT_SKILLS_ROOT = Path(__file__).resolve().parents[2] / "skills"


class CatalogError(ValueError):
    """The skills tree does not hold exactly the declared catalog."""


@dataclass(frozen=True)
class Entry:
    """One skill, as the catalog sees it."""

    name: str
    description: str
    sha256: str
    skill_md_bytes: int
    total_bytes: int


def _skill_files(skill_dir: Path) -> list[Path]:
    return sorted(
        (path for path in skill_dir.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(skill_dir).as_posix(),
    )


def _digest(skill_dir: Path, files: Sequence[Path]) -> str:
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(skill_dir).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _frontmatter(skill_md: Path) -> dict[str, Any]:
    text = skill_md.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            block = "\n".join(lines[1:index])
            loaded = yaml.safe_load(block)
            return loaded if isinstance(loaded, dict) else {}
    return {}


def derive_catalog(skills_root: Path = DEFAULT_SKILLS_ROOT) -> tuple[Entry, ...]:
    """Return the catalog, in ``SKILLS`` order, or raise on a shape mismatch."""
    root = Path(skills_root)
    present = sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    )
    declared = sorted(SKILLS)
    if present != declared:
        extra = [name for name in present if name not in declared]
        missing = [name for name in declared if name not in present]
        details = []
        if extra:
            details.append(f"extra: {', '.join(extra)}")
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        raise CatalogError(
            f"{root} does not hold exactly the declared catalog ({'; '.join(details)})"
        )

    entries = []
    for name in SKILLS:
        skill_dir = root / name
        files = _skill_files(skill_dir)
        skill_md = skill_dir / "SKILL.md"
        description = " ".join(
            str(_frontmatter(skill_md).get("description", "")).split()
        )
        entries.append(
            Entry(
                name=name,
                description=description,
                sha256=_digest(skill_dir, files),
                skill_md_bytes=len(skill_md.read_bytes()),
                total_bytes=sum(len(path.read_bytes()) for path in files),
            )
        )
    return tuple(entries)


def catalog_json(entries: Sequence[Entry]) -> dict[str, object]:
    """The canonical JSON shape a lock or a run directory stores."""
    return {
        "version": 1,
        "skills": [
            {
                "name": entry.name,
                "description": entry.description,
                "sha256": entry.sha256,
                "skill_md_bytes": entry.skill_md_bytes,
                "total_bytes": entry.total_bytes,
            }
            for entry in entries
        ],
        "none": NONE_MEANING,
    }


def catalog_sha256(entries: Sequence[Entry]) -> str:
    """The digest that names this exact catalog."""
    return identity_sha256(catalog_json(entries))


def option_meanings(entries: Sequence[Entry]) -> dict[str, str]:
    """The meaning of every option, in ``OPTIONS`` order."""
    by_name = {entry.name: entry.description for entry in entries}
    meanings: dict[str, str] = {}
    for option in OPTIONS:
        if option == NONE:
            meanings[option] = NONE_MEANING
            continue
        if option not in by_name:
            raise CatalogError(f"catalog has no entry for {option!r}")
        meanings[option] = by_name[option]
    return meanings
