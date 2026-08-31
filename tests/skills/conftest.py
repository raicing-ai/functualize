"""Shared discovery for the skills conformance suite.

These tests exist because the framework validates every job against a schema
and applied nothing at all to the documents that *teach* that schema. Prose
drifts silently: a capability gets added, a table does not, and an agent
confidently writes code against a surface that no longer exists.

Everything here reads the shipped skills as data and checks them against the
running code, so drift becomes a build failure rather than a support ticket.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = REPO_ROOT / "skills"


def skill_dirs() -> list[Path]:
    """Every shipped skill directory, sorted."""
    return sorted(p for p in SKILLS_ROOT.iterdir() if p.is_dir())


def markdown_files() -> list[Path]:
    """Every markdown file across every shipped skill."""
    return sorted(SKILLS_ROOT.rglob("*.md"))


def backticked(text: str) -> set[str]:
    """Every single-backtick span in ``text``."""
    return set(re.findall(r"`([^`\n]+)`", text))


@pytest.fixture(scope="session")
def skills_root() -> Path:
    if not SKILLS_ROOT.is_dir():
        pytest.fail(f"skills/ is missing at {SKILLS_ROOT}")
    return SKILLS_ROOT


@pytest.fixture(scope="session")
def all_skill_text() -> str:
    """Every shipped skill markdown file concatenated."""
    return "\n".join(p.read_text(encoding="utf-8") for p in markdown_files())
