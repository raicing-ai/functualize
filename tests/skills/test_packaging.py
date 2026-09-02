"""The shipped skills must actually ship, and be findable at runtime.

Two failure modes this guards, both of which are silent:

1. The build config stops carrying ``skills/`` into the distribution. Every
   test above still passes — they read the repo — while every *installed*
   functualize answers "no skills found".
2. The runtime resolver stops agreeing with where the build puts them, so
   ``func builtin skills path`` points at nothing on a real install.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from functualize._cli.skills import (
    SKILLS_PACKAGE_DIRNAME,
    list_skills,
    materialize_skills,
    materialized_root,
    resolve_skills_dir,
)

from .conftest import REPO_ROOT, SKILLS_ROOT, skill_dirs


def _pyproject() -> dict:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_wheel_force_includes_the_skills():
    """The wheel carries ``skills/`` as ``functualize/_skills``.

    Without this mapping the package installs with no skills at all, and the
    only symptom is a command that says none exist.
    """
    force_include = _pyproject()["tool"]["hatch"]["build"]["targets"]["wheel"][
        "force-include"
    ]
    assert force_include.get("skills") == f"functualize/{SKILLS_PACKAGE_DIRNAME}", (
        "the wheel no longer force-includes skills/ at the path _cli/skills.py "
        f"resolves ({SKILLS_PACKAGE_DIRNAME})"
    )


def test_sdist_includes_the_skills():
    """The sdist carries them too, or a source build produces a stripped wheel."""
    only_include = _pyproject()["tool"]["hatch"]["build"]["targets"]["sdist"][
        "only-include"
    ]
    assert "skills" in only_include


def test_resolver_finds_the_checkout_directory():
    """In a source checkout the resolver falls back to ``<repo>/skills``.

    Reported as ``checkout`` rather than ``package`` on purpose: it is whatever
    the working tree currently says, not a version guarantee.
    """
    location = resolve_skills_dir()
    assert location is not None
    assert location.path.resolve() == SKILLS_ROOT.resolve()
    assert location.origin == "checkout"
    assert not location.is_packaged


def test_resolver_prefers_the_packaged_copy(tmp_path, monkeypatch):
    """A real install must win over the checkout fallback.

    Simulated by pointing the module's own file at a fake package tree — the
    ordering is the contract, and getting it backwards means an installed
    functualize would serve whatever repo happened to be nearby.
    """
    import functualize._cli.skills as skills_module

    package = tmp_path / "site-packages" / "functualize"
    (package / "_cli").mkdir(parents=True)
    packaged_skills = package / SKILLS_PACKAGE_DIRNAME / "demo"
    packaged_skills.mkdir(parents=True)
    (packaged_skills / "SKILL.md").write_text(
        "---\nname: demo\ndescription: A demo.\n---\n", encoding="utf-8"
    )
    monkeypatch.setattr(skills_module, "__file__", str(package / "_cli" / "skills.py"))

    location = resolve_skills_dir()
    assert location is not None
    assert location.origin == "package"
    assert location.is_packaged
    assert [s.name for s in list_skills(location.path)] == ["demo"]


def test_every_skill_directory_is_readable():
    """`list_skills` sees exactly the directories on disk — no silent drops."""
    listed = {s.name for s in list_skills(SKILLS_ROOT)}
    assert listed == {d.name for d in skill_dirs()}


def test_materialize_writes_a_version_stamped_tree(xdg_dirs):
    """The version stamps the *parent*, never the skill directory.

    The spec requires a skill's ``name`` to equal its directory name, so
    ``func-0.1.0/functualize/SKILL.md`` is conformant and
    ``functualize-0.1.0/SKILL.md`` is not — the latter would upload-reject.
    """
    destination, names = materialize_skills(SKILLS_ROOT, "9.9.9")

    assert destination == materialized_root("9.9.9")
    assert destination.name == "func-9.9.9"
    assert destination.parent.name == "skills"
    assert Path(destination.parent.parent) == xdg_dirs.functualize_data

    for name in names:
        assert (destination / name / "SKILL.md").is_file()
        # The directory name is the skill name, unstamped.
        assert "9.9.9" not in name


def test_materialize_replaces_rather_than_merges(xdg_dirs):
    """A skill deleted upstream must not survive in a materialized tree."""
    destination, _ = materialize_skills(SKILLS_ROOT, "9.9.9")
    stale = destination / "removed-upstream"
    stale.mkdir()
    (stale / "SKILL.md").write_text("---\nname: removed-upstream\n---\n")

    materialize_skills(SKILLS_ROOT, "9.9.9")
    assert not stale.exists()


def test_materialize_prune_removes_other_versions(xdg_dirs):
    """`--prune` is opt-in, and clears only sibling version trees."""
    old, _ = materialize_skills(SKILLS_ROOT, "0.0.1")
    assert old.is_dir()

    new, _ = materialize_skills(SKILLS_ROOT, "9.9.9", prune=True)
    assert new.is_dir()
    assert not old.exists()


def test_materialize_keeps_other_versions_by_default(xdg_dirs):
    """An older tree may still be referenced by a project's agent config."""
    old, _ = materialize_skills(SKILLS_ROOT, "0.0.1")
    materialize_skills(SKILLS_ROOT, "9.9.9")
    assert old.is_dir()
