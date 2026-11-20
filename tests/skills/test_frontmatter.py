"""Frontmatter conformance for the shipped agent skills.

The Agent Skills spec defines six fields. Claude Code accepts many more, and a
skill using them is rejected by claude.ai upload and the Skills API with
``Unexpected key(s) in SKILL.md frontmatter`` — so anything we publish stays on
the portable six (ADR-006 §5). These tests hold that line, and hold the two
things that silently break discovery: a ``name`` that disagrees with its
directory, and a description over the limit.
"""

from __future__ import annotations

import pytest

from functualize import __version__
from functualize._cli.skills import parse_frontmatter, read_skill

from .conftest import skill_dirs

#: The complete set the spec defines. Nothing else may appear in a shipped
#: skill: the extra fields are Claude Code extensions and are rejected
#: elsewhere.
PORTABLE_FIELDS = frozenset(
    {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
)

#: The spec's own limits.
MAX_NAME = 64
MAX_DESCRIPTION = 1024
MAX_COMPATIBILITY = 500


@pytest.mark.parametrize("skill_dir", skill_dirs(), ids=lambda p: p.name)
def test_skill_has_readable_frontmatter(skill_dir):
    """Every skill directory holds a SKILL.md our own parser can read.

    The parser is a deliberate subset (``_cli/skills.py``). Binding it to the
    files here means we cannot author frontmatter that ``func builtin skills
    list`` would silently fail to display.
    """
    info = read_skill(skill_dir)
    assert info is not None, f"{skill_dir}/SKILL.md is missing or has no `name`"


@pytest.mark.parametrize("skill_dir", skill_dirs(), ids=lambda p: p.name)
def test_name_matches_directory(skill_dir):
    """``name`` must equal the directory name — the spec requires it.

    A mismatch does not error anywhere; the skill simply never activates.
    """
    info = read_skill(skill_dir)
    assert info is not None
    assert info.name == skill_dir.name


@pytest.mark.parametrize("skill_dir", skill_dirs(), ids=lambda p: p.name)
def test_name_is_well_formed(skill_dir):
    """Lowercase, digits and hyphens; no leading, trailing or doubled hyphen."""
    info = read_skill(skill_dir)
    assert info is not None
    name = info.name
    assert len(name) <= MAX_NAME
    assert name == name.lower()
    assert all(c.isalnum() or c == "-" for c in name), name
    assert not name.startswith("-") and not name.endswith("-"), name
    assert "--" not in name, name


@pytest.mark.parametrize("skill_dir", skill_dirs(), ids=lambda p: p.name)
def test_description_is_present_and_within_limit(skill_dir):
    """The description is the entire activation surface — and it is capped.

    It is the only part always in context, so an over-long one is truncated
    exactly where the trigger tokens usually are.
    """
    info = read_skill(skill_dir)
    assert info is not None
    description = info.description
    assert description, f"{skill_dir.name} has no description"
    assert len(description) <= MAX_DESCRIPTION, (
        f"{skill_dir.name}: description is {len(description)} chars, "
        f"limit is {MAX_DESCRIPTION}"
    )


@pytest.mark.parametrize("skill_dir", skill_dirs(), ids=lambda p: p.name)
def test_only_portable_fields(skill_dir):
    """No Claude Code extensions in anything we ship."""
    front = parse_frontmatter((skill_dir / "SKILL.md").read_text(encoding="utf-8"))
    extra = set(front) - PORTABLE_FIELDS
    assert not extra, (
        f"{skill_dir.name}: non-portable frontmatter {sorted(extra)}. "
        "Rejected by claude.ai upload and the Skills API (ADR-006 §5)."
    )


@pytest.mark.parametrize("skill_dir", skill_dirs(), ids=lambda p: p.name)
def test_metadata_version_tracks_the_package(skill_dir):
    """``metadata.version`` is the one hand-maintained number here.

    There is no ``version`` field in the spec, so this is inert to every
    client — but it is what an installed skill self-identifies with, and a
    stale value is worse than none. Pin it to the package rather than letting
    it drift into meaning nothing.
    """
    front = parse_frontmatter((skill_dir / "SKILL.md").read_text(encoding="utf-8"))
    metadata = front.get("metadata")
    assert isinstance(metadata, dict), f"{skill_dir.name}: no metadata block"
    assert metadata.get("version") == __version__, (
        f"{skill_dir.name}: metadata.version is {metadata.get('version')!r}, "
        f"package is {__version__!r}"
    )


@pytest.mark.parametrize("skill_dir", skill_dirs(), ids=lambda p: p.name)
def test_compatibility_within_limit(skill_dir):
    """Optional, prose, and capped at 500 characters when present."""
    front = parse_frontmatter((skill_dir / "SKILL.md").read_text(encoding="utf-8"))
    compatibility = front.get("compatibility")
    if compatibility is None:
        pytest.skip("no compatibility field")
    assert isinstance(compatibility, str)
    assert len(compatibility) <= MAX_COMPATIBILITY


def test_at_least_the_four_task_skills_ship():
    """Guards against a skill silently disappearing from the distribution."""
    names = {d.name for d in skill_dirs()}
    assert {
        "functualize",
        "functualize-app",
        "functualize-cli",
        "functualize-skill",
    } <= names
