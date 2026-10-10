"""The shipped skills must actually ship, and be findable at runtime.

Three failure modes this guards, all of which are silent:

1. The build config stops carrying ``skills/`` into the distribution. Every
   test above still passes — they read the repo — while every *installed*
   functualize answers "no skills found".
2. The runtime resolver stops agreeing with where the build puts them, so
   ``func builtin skills path`` points at nothing on a real install.
3. The shipped reference teaches a ``sh(...)`` form the capability rejects —
   the reader hits the error the document caused.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

import pytest

from functualize._cli.skills import (
    SKILLS_PACKAGE_DIRNAME,
    list_skills,
    materialize_skills,
    materialized_root,
    resolve_skills_dir,
)
from functualize._engine.capabilities.shell import WiredShell

from .conftest import REPO_ROOT, SKILLS_ROOT, backticked, markdown_files, skill_dirs


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


# ── Documented `sh(...)` command forms ──────────────────────────────────────
#
# The reference teaches `sh(...)` forms and the capability accepts exactly
# three: a list of argv tokens (the common case), a raw string with
# ``shell=True``, and a template string with params. A bare raw string raises.
# Every literal call the skills show is resolved through the capability's own
# contract here, so an example that would fail in front of a reader fails in
# the suite first.

_PYTHON_FENCE = re.compile(r"```python\n(.*?)```", re.DOTALL)

_MISSING = object()


def _literal(node: ast.expr) -> object:
    """``node``'s value, or ``_MISSING`` when it is a placeholder."""
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return _MISSING


def _sh_calls(source: str) -> list[tuple[str, object, dict[str, object]]]:
    """``(call text, command, kwargs)`` for each literal ``sh(...)`` in source.

    Parsed, not pattern-matched: `sh(...)` signature prose and attribute calls
    (`sh.cd(...)`, `sh.prefix(...)`) are not command invocations, and a
    placeholder like `sh(cmd)` carries nothing the resolver can check — both
    are skipped rather than guessed at.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    found: list[tuple[str, object, dict[str, object]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "sh"):
            continue
        if any(kw.arg is None for kw in node.keywords):
            continue  # `**spread` — the command form cannot be known.
        args = [_literal(a) for a in node.args]
        kwargs = {kw.arg: _literal(kw.value) for kw in node.keywords}
        if not args or args[0] is _MISSING:
            continue
        if any(value is _MISSING for value in kwargs.values()):
            continue
        if not isinstance(args[0], (str, list)):
            continue  # `sh(...)` placeholder, not an example.
        text = ast.get_source_segment(source, node) or "sh(...)"
        found.append((text, args[0], kwargs))
    return found


def _documented_sh_examples() -> list[tuple[str, object, dict[str, object]]]:
    """Every literal ``sh(...)`` example the shipped skills show a reader.

    Python fences and inline backticked spans alike — both are copied.
    """
    examples: list[tuple[str, object, dict[str, object]]] = []
    for path in markdown_files():
        relative = str(path.relative_to(SKILLS_ROOT))
        text = path.read_text(encoding="utf-8")
        sources = [(relative, block) for block in _PYTHON_FENCE.findall(text)]
        sources += [
            (f"{relative} (inline)", span)
            for span in backticked(text)
            if re.search(r"\bsh\(", span)
        ]
        for where, source in sources:
            for call, command, kwargs in _sh_calls(source):
                examples.append((f"{where}: {call}", command, kwargs))
    return examples


SHELL_EXAMPLES = _documented_sh_examples()


@pytest.mark.parametrize(
    ("command", "kwargs"),
    [(command, kwargs) for _, command, kwargs in SHELL_EXAMPLES],
    ids=[where for where, _, _ in SHELL_EXAMPLES],
)
def test_every_documented_shell_example_is_an_accepted_form(command, kwargs):
    """A `sh(...)` example the capability rejects teaches by error.

    The bare raw string is the documented trap: the reference showed one, the
    capability raises for exactly it, and the reader hit the error the
    reference caused. Resolution runs through the real contract, so the
    document cannot drift from the guard.
    """
    shell = bool(kwargs.get("shell", False))
    template = {k: v for k, v in kwargs.items() if k != "shell"}
    WiredShell()._resolve_command(command, shell=shell, template_params=template)


def test_the_shell_example_scan_actually_finds_examples():
    """The falsifier. An empty scan passes the test above vacuously."""
    assert len(SHELL_EXAMPLES) >= 3, SHELL_EXAMPLES
    forms = [(command, kwargs) for _, command, kwargs in SHELL_EXAMPLES]
    assert any(isinstance(command, list) for command, _ in forms), (
        "no list-form example — the common case is untaught"
    )
    assert any(isinstance(command, str) and kwargs for command, kwargs in forms), (
        "no raw-string example with shell=True or template params"
    )
