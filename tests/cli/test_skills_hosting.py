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

import importlib.metadata
import importlib.resources
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

    real_entry_points = importlib.metadata.entry_points
    real_version = importlib.metadata.version
    real_files = importlib.resources.files

    # Answer only for the skills group and only for `otherpkg`; defer
    # everything else to the real implementation. A narrower fake breaks as
    # soon as a test drives the whole CLI, which also scans the *plugin* entry
    # point group on its way to a command.
    def fake_entry_points(*, group: str | None = None, **kwargs: object):
        if group == SKILLS_ENTRY_POINT_GROUP:
            return [
                _FakeEntryPoint("otherpkg", "otherpkg._skills", _FakeDist("otherpkg"))
            ]
        if group is None:
            return real_entry_points(**kwargs)  # type: ignore[arg-type]
        return real_entry_points(group=group, **kwargs)  # type: ignore[arg-type]

    def fake_files(package: str):
        if package == "otherpkg._skills":
            return directory
        return real_files(package)

    def fake_version(name: str) -> str:
        if name == "otherpkg":
            return "9.9.9"
        return real_version(name)

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


class TestTheCommandsIterateEveryLocation:
    """4.2 — the four `builtin skills` subcommands, migrated to the plural.

    Until now each resolved core's single directory, so a hosted skill existed
    and no command would ever mention it.
    """

    def test_path_emits_one_line_per_location(self, hosted: Path, cli_run) -> None:
        """**A deliberate breaking change.** `skills path` printed exactly one
        path so it could be substituted: `npx skills add "$(func builtin skills
        path)"`. With more than one location a single path could only ever be
        core's, and answering with core's alone silently hides the rest.

        The substitution idiom is therefore wrong now, which is why `README.md`
        changed in the same task.
        """
        result = cli_run(["builtin", "skills", "path"])
        assert result.exit_code == 0
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        assert len(lines) == 2, lines
        assert lines[1] == str(hosted)
        assert lines[0] != str(hosted)

    def test_list_names_the_hosted_skill(self, hosted: Path, cli_run) -> None:
        result = cli_run(["builtin", "skills", "list"])
        assert result.exit_code == 0
        assert "other-skill" in result.stdout

    def test_list_stamps_each_source_with_its_own_version(
        self, hosted: Path, cli_run
    ) -> None:
        """`otherpkg 9.9.9`, never functualize's version against otherpkg's
        name — the guarantee `_cli/skills.py`'s docstring exists for."""
        from functualize import __version__

        result = cli_run(["builtin", "skills", "list"])
        assert "otherpkg 9.9.9" in result.stdout
        assert f"otherpkg {__version__}" not in result.stdout

    def test_install_dry_run_targets_every_location(
        self, hosted: Path, cli_run
    ) -> None:
        result = cli_run(["builtin", "skills", "install", "--dry-run"])
        assert result.exit_code == 0
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        assert len(lines) == 2, lines
        assert all(line.startswith("npx skills add ") for line in lines)
        assert lines[1].endswith(str(hosted))

    def test_info_reports_every_location(self, hosted: Path, cli_run, project_tree):
        root = project_tree(jobs={"jobs.py": "def hello() -> None:\n    ...\n"})
        result = cli_run(["builtin", "info"], cwd=root)
        assert result.exit_code == 0
        assert "otherpkg 9.9.9" in result.stdout
        assert str(hosted) in result.stdout


class TestMaterializationIsStampedPerSource:
    """The second acceptance: a hosted skill lands under **its own** version.

    A shared stamp would put `otherpkg`'s skill under `func-<functualize
    version>`, which is the exact claim `_cli/skills.py` promises can never
    happen -- and would have two distributions overwrite one directory.
    """

    def test_the_materialize_command_stamps_each_source_separately(
        self, hosted: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cli_run
    ) -> None:
        """Through the CLI, not the function underneath it.

        Written after a sabotage passed: hard-coding `distribution="functualize"`
        inside the `materialize` command changed nothing, because every test
        here called `materialize_skills()` directly and none drove the command
        that has to pass the location's own stamp to it. The wiring *is* the
        task; testing only the callee tested the half that never moved.
        """
        from functualize import __version__

        data_dir = tmp_path / "xdg"
        monkeypatch.setattr(
            "functualize.app.utils.resolve_user_data_dir", lambda: data_dir
        )

        result = cli_run(["builtin", "skills", "materialize"])
        assert result.exit_code == 0

        roots = {p.name for p in (data_dir / "skills").iterdir() if p.is_dir()}
        assert f"func-{__version__}" in roots, roots
        assert "otherpkg-9.9.9" in roots, roots
        assert f"otherpkg-{__version__}" not in roots
        assert (
            data_dir / "skills" / "otherpkg-9.9.9" / "other-skill" / "SKILL.md"
        ).is_file()

    def test_a_hosted_skill_uses_its_own_distribution_and_version(
        self, hosted: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from functualize._cli import skills as skills_mod

        data_dir = tmp_path / "xdg"
        monkeypatch.setattr(
            "functualize.app.utils.resolve_user_data_dir", lambda: data_dir
        )

        destination, names = skills_mod.materialize_skills(
            hosted, "9.9.9", distribution="otherpkg"
        )
        assert names == ["other-skill"]
        assert destination == data_dir / "skills" / "otherpkg-9.9.9"
        assert (destination / "other-skill" / "SKILL.md").is_file()

    def test_core_keeps_the_func_stem(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not `functualize-<version>`: agent configs already point at
        `func-<version>`, and renaming it would break every one of them."""
        from functualize._cli import skills as skills_mod

        data_dir = tmp_path / "xdg"
        monkeypatch.setattr(
            "functualize.app.utils.resolve_user_data_dir", lambda: data_dir
        )
        assert skills_mod.materialized_root("1.2.3") == (
            data_dir / "skills" / "func-1.2.3"
        )
        assert skills_mod.materialized_root("1.2.3", "functualize") == (
            data_dir / "skills" / "func-1.2.3"
        )

    def test_prune_does_not_cross_distributions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`--prune` deletes *this* distribution's other versions. Pruning by a
        bare `func-` prefix would have one host delete another's tree."""
        from functualize._cli import skills as skills_mod

        data_dir = tmp_path / "xdg"
        monkeypatch.setattr(
            "functualize.app.utils.resolve_user_data_dir", lambda: data_dir
        )
        skills_root = data_dir / "skills"
        core_old = skills_root / "func-0.0.1"
        _skill_tree(core_old, "core-skill", dist="functualize")

        source = _skill_tree(tmp_path / "src", "other-skill")
        skills_mod.materialize_skills(
            source, "9.9.9", prune=True, distribution="otherpkg"
        )

        assert core_old.is_dir(), "pruning otherpkg deleted core's tree"


class TestTheReportIsAList:
    """`full_report()["skills"]` was an object or `null`; it is now a list.

    Also a breaking change, and the same one: an object could only ever
    describe core. Always present and `[]` when empty, so a consumer never
    needs to guard for the key.
    """

    def test_every_location_is_reported_with_its_own_stamp(
        self, hosted: Path, cli_run, project_tree
    ) -> None:
        import json

        root = project_tree(jobs={"jobs.py": "def hello() -> None:\n    ...\n"})
        result = cli_run(["builtin", "info", "--json"], cwd=root)
        assert result.exit_code == 0
        entries = json.loads(result.stdout)["skills"]
        assert isinstance(entries, list)
        assert len(entries) == 2
        hosted_entry = next(e for e in entries if e["origin"] == "entry-point")
        assert hosted_entry["distribution"] == "otherpkg"
        assert hosted_entry["version"] == "9.9.9"
        assert hosted_entry["names"] == ["other-skill"]
