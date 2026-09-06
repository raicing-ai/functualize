"""A third-party distribution can host agent skills.

`resolve_skills_dir()` looked in exactly two places, both inside the
functualize distribution, so `builtin skills list` would never show anyone
else's. `resolve_skills_locations()` returns core's location first, then every
distribution declaring the `functualize.skills` entry point.

The version stamp is **per source**. `skills.py`'s own module docstring
promises that *a skill read from here can never describe a different release*;
that only holds for a third-party skill if the stamp comes from that package's
version rather than functualize's, so `SkillsLocation` carries `distribution`
and `version` and materialization uses them.

A malformed or missing entry point warns and is skipped. This path is
reachable from `func --help`, so one broken third-party package must not be
able to take the whole CLI down.

The entry points are faked at the `importlib.metadata` seam rather than by
installing a real wheel: a real install would mutate the developer's
environment, and `entry_points(group=...)` is the exact surface the code
reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from functualize._cli.skills import (
    SKILLS_ENTRY_POINT_GROUP,
    SkillsLocation,
    list_skills,
    resolve_skills_dir,
    resolve_skills_locations,
)

SKILL_MD = """\
---
name: {name}
description: A skill from {dist}.
---

Body.
"""


@dataclass
class _FakeDist:
    name: str


@dataclass
class _FakeEntryPoint:
    name: str
    value: str
    dist: _FakeDist | None = None


def _skill_tree(root: Path, *names: str, dist: str = "otherpkg") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name in names:
        directory = root / name
        directory.mkdir()
        (directory / "SKILL.md").write_text(SKILL_MD.format(name=name, dist=dist))
    return root


@pytest.fixture
def hosted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Install a fake `otherpkg` declaring the entry point, and return its dir."""
    directory = _skill_tree(tmp_path / "otherpkg" / "_skills", "other-skill")

    def fake_entry_points(*, group: str):
        assert group == SKILLS_ENTRY_POINT_GROUP
        return [_FakeEntryPoint("otherpkg", "otherpkg._skills", _FakeDist("otherpkg"))]

    def fake_files(package: str):
        assert package == "otherpkg._skills"
        return directory

    def fake_version(name: str) -> str:
        assert name == "otherpkg"
        return "9.9.9"

    monkeypatch.setattr("importlib.metadata.entry_points", fake_entry_points)
    monkeypatch.setattr("importlib.metadata.version", fake_version)
    monkeypatch.setattr("importlib.resources.files", fake_files)
    return directory


class TestPluralResolution:
    def test_core_comes_first(self, hosted: Path) -> None:
        locations = resolve_skills_locations()
        assert locations[0].distribution == "functualize"
        assert locations[0].origin in {"package", "checkout"}

    def test_the_third_party_location_appears(self, hosted: Path) -> None:
        locations = resolve_skills_locations()
        entry = next(loc for loc in locations if loc.origin == "entry-point")
        assert entry.path == hosted
        assert entry.distribution == "otherpkg"
        assert entry.version == "9.9.9"

    def test_its_skills_are_readable(self, hosted: Path) -> None:
        entry = next(
            loc for loc in resolve_skills_locations() if loc.origin == "entry-point"
        )
        assert [s.name for s in list_skills(entry.path)] == ["other-skill"]

    def test_core_is_still_stamped_with_functualizes_version(
        self, hosted: Path
    ) -> None:
        from functualize import __version__

        assert resolve_skills_locations()[0].version == __version__


class TestTheSingularResolverIsUnchanged:
    """`resolve_skills_dir()` is retained and still answers for core only —
    the three call sites migrate to the plural in 4.2, and until they do the
    singular must keep behaving exactly as it did."""

    def test_it_ignores_entry_points(self, hosted: Path) -> None:
        own = resolve_skills_dir()
        assert own is not None
        assert own.path != hosted
        assert own.origin in {"package", "checkout"}


class TestABrokenEntryPointIsSkipped:
    """Never fatal: this runs on the way to `func --help`."""

    def _with_entry_point(
        self, monkeypatch: pytest.MonkeyPatch, value: str, **files_kw: object
    ) -> None:
        monkeypatch.setattr(
            "importlib.metadata.entry_points",
            lambda *, group: [_FakeEntryPoint("broken", value, _FakeDist("broken"))],
        )

    def test_a_missing_module_warns_and_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch, caplog
    ) -> None:
        self._with_entry_point(monkeypatch, "no_such_package_xyz._skills")
        with caplog.at_level("WARNING"):
            locations = resolve_skills_locations()
        assert all(loc.origin != "entry-point" for loc in locations)
        assert "broken" in caplog.text

    def test_a_path_that_is_not_a_directory_is_skipped(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog
    ) -> None:
        """Everything else about this entry point resolves.

        `version` is stubbed deliberately: without it the entry point is
        rejected by `PackageNotFoundError` instead, and the test passes whether
        or not the `is_dir()` guard exists. Sabotage caught exactly that — this
        assertion was vacuous until the stub was added.
        """
        not_a_dir = tmp_path / "file.txt"
        not_a_dir.write_text("")
        self._with_entry_point(monkeypatch, "whatever")
        monkeypatch.setattr("importlib.resources.files", lambda pkg: not_a_dir)
        monkeypatch.setattr("importlib.metadata.version", lambda name: "1.0.0")
        with caplog.at_level("WARNING"):
            locations = resolve_skills_locations()
        assert all(loc.origin != "entry-point" for loc in locations)
        assert "broken" in caplog.text
        assert "NotADirectoryError" in caplog.text or "file.txt" in caplog.text

    def test_core_is_still_returned_when_a_third_party_is_broken(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The point of skipping rather than failing."""
        self._with_entry_point(monkeypatch, "no_such_package_xyz._skills")
        assert resolve_skills_locations()[0].distribution == "functualize"


class TestTheLocationDataclass:
    def test_it_defaults_to_functualize(self) -> None:
        """The two existing construction sites in `resolve_skills_dir` pass
        only path and origin; the defaults keep them valid."""
        loc = SkillsLocation(Path("/tmp"), "package")
        assert loc.distribution == "functualize"
        assert loc.is_packaged

    def test_entry_point_is_not_packaged(self) -> None:
        loc = SkillsLocation(Path("/tmp"), "entry-point", "otherpkg", "1.0")
        assert not loc.is_packaged
