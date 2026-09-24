"""`substrate_for_project` asks the filesystem nothing until a document is read.

FUN-17/T12, decided in TD-1 (D4). Boot step 6.5 builds the project's substrate
on both boot paths, and `boot_static` promises zero filesystem IO. The upward
walk for `.functualize/` cannot be avoided — the mode *is* whether that
directory exists — so `JsonFileSubstrate.for_project` defers it to the first
document access instead of doing it at construction.

A lazy root is an untested path that looks identical to an eager one from the
outside: both answer `root` correctly. What tells them apart is *when* the walk
happens, so that is what is asserted.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from functualize._primitives.fresh_format import resolve_fresh_location
from functualize._primitives.substrate import JsonFileSubstrate, substrate_for_project


def _tracking_stat(calls: list[str]) -> object:
    original = os.stat

    def tracking(path: object, *args: object, **kwargs: object) -> os.stat_result:
        calls.append(str(path))
        return original(path, *args, **kwargs)  # type: ignore[arg-type]

    return tracking


def test_building_the_projects_substrate_stats_nothing(tmp_path: Path) -> None:
    calls: list[str] = []
    with patch.object(os, "stat", _tracking_stat(calls)):
        substrate_for_project(tmp_path)

    assert calls == [], f"building the substrate asked the filesystem: {calls}"


def test_the_first_document_access_is_what_walks(tmp_path: Path) -> None:
    """The other half: the walk is deferred, not deleted."""
    substrate = substrate_for_project(tmp_path)

    calls: list[str] = []
    with patch.object(os, "stat", _tracking_stat(calls)):
        substrate.read("probe")

    assert calls, "a document read resolved no directory; the walk is gone"


def test_the_late_answer_is_the_one_an_eager_walk_gives(tmp_path: Path) -> None:
    """Deferring *when* must not change *where*."""
    (tmp_path / ".functualize").mkdir()
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)

    substrate = substrate_for_project(nested)

    assert substrate.root == resolve_fresh_location(nested)[0].parent


def test_a_relative_start_is_anchored_when_built(tmp_path: Path) -> None:
    """A later `chdir` cannot move a substrate that was built from `.`."""
    here = tmp_path / "here"
    (here / ".functualize").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    previous = Path.cwd()
    os.chdir(here)
    try:
        substrate = JsonFileSubstrate.for_project(".")
        os.chdir(elsewhere)
        root = substrate.root
    finally:
        os.chdir(previous)

    assert root == (here / ".functualize").resolve()
