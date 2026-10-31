"""Offline tests for the catalog declaration (AC-1)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests.skill_router_eval.catalog import (
    NONE,
    NONE_MEANING,
    OPTIONS,
    SKILLS,
    CatalogError,
    catalog_json,
    catalog_sha256,
    derive_catalog,
    option_meanings,
)

SKILLS_ROOT = Path(__file__).resolve().parents[2] / "skills"


def _copy_skills(tmp_path: Path) -> Path:
    root = tmp_path / "skills"
    shutil.copytree(SKILLS_ROOT, root)
    return root


def test_the_catalog_is_the_five_options_in_order() -> None:
    entries = derive_catalog(SKILLS_ROOT)

    assert [entry.name for entry in entries] == list(SKILLS)
    assert list(option_meanings(entries)) == list(OPTIONS)
    assert len(OPTIONS) == len(SKILLS) + 1


def test_every_option_carries_a_meaning() -> None:
    meanings = option_meanings(derive_catalog(SKILLS_ROOT))

    assert meanings[NONE] == NONE_MEANING
    assert all(meaning.strip() for meaning in meanings.values())


def test_two_derivations_of_one_tree_share_a_digest() -> None:
    first = derive_catalog(SKILLS_ROOT)
    second = derive_catalog(SKILLS_ROOT)

    assert first == second
    assert catalog_sha256(first) == catalog_sha256(second)
    assert catalog_json(first)["version"] == 1


def test_an_extra_skill_directory_is_refused(tmp_path: Path) -> None:
    root = _copy_skills(tmp_path)
    extra = root / "functualize-extra"
    extra.mkdir()
    (extra / "SKILL.md").write_text(
        "---\nname: functualize-extra\n---\n", encoding="utf-8"
    )

    with pytest.raises(CatalogError, match="functualize-extra"):
        derive_catalog(root)


def test_a_missing_skill_directory_is_refused(tmp_path: Path) -> None:
    root = _copy_skills(tmp_path)
    shutil.rmtree(root / "functualize-cli")

    with pytest.raises(CatalogError, match="functualize-cli"):
        derive_catalog(root)


def test_one_changed_byte_changes_the_skill_and_the_catalog_digest(
    tmp_path: Path,
) -> None:
    root = _copy_skills(tmp_path)
    reference = root / "functualize" / "references" / "idiomatic.md"
    before = {entry.name: entry for entry in derive_catalog(root)}
    before_catalog = catalog_sha256(derive_catalog(root))

    reference.write_bytes(reference.read_bytes() + b"x")
    after = {entry.name: entry for entry in derive_catalog(root)}

    assert after["functualize"].sha256 != before["functualize"].sha256
    assert after["functualize"].total_bytes == before["functualize"].total_bytes + 1
    assert after["functualize-app"].sha256 == before["functualize-app"].sha256
    assert catalog_sha256(derive_catalog(root)) != before_catalog
