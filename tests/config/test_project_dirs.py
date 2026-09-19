"""The composition rule for plugin directories, rung by rung.

`resolve_plugin_directories` is the piece that decides *which* directories a
file-plugin scan gets. It is unit-tested here rather than only through boot,
because the interesting cases are combinatorial (declared vs convention, each
precedence rung, the ambient switch, the bound) and a boot-level test of each
would be slow and would not say which rung broke.

T5 wires this to `boot_standard`; `tests/plugins/test_declared_plugin_directories.py`
is the end-to-end proof. Gates AC-3b and AC-3c of
`.spec/features/declared-plugin-directories/spec.md`.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from functualize._config.project_dirs import (
    resolve_plugin_directories,
    resolve_project_config,
    resolve_project_directories,
)


def _plugins_at(directory: Path) -> Path:
    """Create `<directory>/.functualize/plugins` and return it."""
    plugins = directory / ".functualize" / "plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    return plugins


def _declare(directory: Path, body: str) -> None:
    """Write a `.functualize.toml` (root-keyed form) into `directory`."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ".functualize.toml").write_text(textwrap.dedent(body))


# --- AC-3c (i): inheritance up the walk ------------------------------------


def test_a_declared_directory_two_levels_up_is_inherited(tmp_path: Path) -> None:
    """Walk A merges ancestors, so a parent's declaration reaches a child."""
    shared = tmp_path / "shared_plugins"
    shared.mkdir()
    _declare(tmp_path, f'plugins_directories = ["{shared}"]\n')

    leaf = tmp_path / "apps" / "web"
    _declare(leaf, 'jobs_directories = ["jobs"]\n')

    anchor, merged = resolve_project_config(leaf)
    declared, _convention = resolve_plugin_directories(
        anchor=anchor, merged=merged, project_root=None
    )

    assert str(shared.resolve()) in declared


# --- AC-3c (ii): root = true stops the climb -------------------------------


def test_root_true_stops_the_inheritance(tmp_path: Path) -> None:
    """`root = true` is EditorConfig semantics: stop climbing here.

    The falsifier for the test above — same tree, one extra key, and the
    grandparent's declaration must no longer arrive.
    """
    shared = tmp_path / "shared_plugins"
    shared.mkdir()
    _declare(tmp_path, f'plugins_directories = ["{shared}"]\n')

    leaf = tmp_path / "apps" / "web"
    _declare(leaf, 'root = true\njobs_directories = ["jobs"]\n')

    anchor, merged = resolve_project_config(leaf)
    declared, _convention = resolve_plugin_directories(
        anchor=anchor, merged=merged, project_root=None
    )

    assert str(shared.resolve()) not in declared


# --- AC-3c (iii): the XDG global rung --------------------------------------


def test_the_xdg_global_layer_supplies_a_directory(tmp_path: Path) -> None:
    """An org-wide directory in ~/.config/functualize/config.toml is honoured.

    Measured before the fix as resolving correctly through the precedence
    chain and then being discarded — nothing handed it to the loader.
    """
    org_wide = tmp_path / "org_plugins"
    org_wide.mkdir()

    declared, _convention = resolve_plugin_directories(
        anchor=tmp_path,
        merged={},
        project_root=None,
        global_config={"plugins_directories": [str(org_wide)]},
    )

    assert str(org_wide.resolve()) in declared


def test_the_xdg_global_file_is_actually_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rung above passes `global_config` in; this one makes the code find it.

    Written deliberately as a pair. A test that hands the value straight to the
    function under test proves the *precedence* but not the *plumbing* — the
    same shape of gate that, elsewhere in this feature, stayed green under a
    sabotaged XDG lookup and so proved nothing. This one writes a real
    `$XDG_CONFIG_HOME/functualize/config.toml` and lets
    `resolve_project_directories` go and find it.
    """
    org_wide = tmp_path / "org_plugins"
    org_wide.mkdir()

    xdg = tmp_path / "xdg_config"
    (xdg / "functualize").mkdir(parents=True)
    (xdg / "functualize" / "config.toml").write_text(
        f'plugins_directories = ["{org_wide}"]\n'
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

    project = tmp_path / "project"
    project.mkdir()
    result = resolve_project_directories(project)

    assert str(org_wide.resolve()) in result.declared_plugin_directories


# --- the convention half ----------------------------------------------------


def test_the_convention_directory_comes_from_the_project_root(tmp_path: Path) -> None:
    """Anchored on walk C, so a config-less level is still found.

    This is the case walk A's own convention collection misses: `tmp_path`
    holds `.functualize/plugins/` but no config file, so it never appears in
    walk A's layer list.
    """
    plugins = _plugins_at(tmp_path)
    leaf = tmp_path / "apps" / "web"
    leaf.mkdir(parents=True)

    result = resolve_project_directories(leaf)

    assert result.project_root == (tmp_path / ".functualize")
    assert str(plugins.resolve()) in result.convention_plugin_directories


def test_an_absent_convention_directory_yields_nothing(tmp_path: Path) -> None:
    """A `.functualize/` with no `plugins/` inside contributes no directory."""
    (tmp_path / ".functualize").mkdir()

    result = resolve_project_directories(tmp_path)

    assert result.convention_plugin_directories == ()


# --- AC-3b: the bound -------------------------------------------------------


def test_a_plugins_dir_above_the_project_root_is_not_reached(tmp_path: Path) -> None:
    """AC-3b — the falsifier for an unbounded walk.

    An outer directory also carries `.functualize/plugins/`. The project's own
    root is nearer, so the walk stops there and the outer one is never scanned.
    Without this bound the search would climb to the filesystem root, executing
    arbitrary Python from any ancestor — the trust-model concern in `spec.md`
    §E.
    """
    outer_plugins = _plugins_at(tmp_path / "outer")
    inner = tmp_path / "outer" / "project"
    inner_plugins = _plugins_at(inner)

    result = resolve_project_directories(inner / "src" / "deep")

    assert str(inner_plugins.resolve()) in result.convention_plugin_directories
    assert str(outer_plugins.resolve()) not in result.plugin_directories


# --- the ambient switch -----------------------------------------------------


def test_ambient_false_drops_convention_but_keeps_declared(tmp_path: Path) -> None:
    """`PluginSources(ambient_directory=False)` refuses only the implicit half.

    The field's own docstring has always promised this — "a declared
    `plugins_directories` is unaffected; only the convention fallback is
    refused" — and until this feature the declared half never loaded at all,
    so the promise was untestable.
    """
    _plugins_at(tmp_path)
    declared_dir = tmp_path / "declared_plugins"
    declared_dir.mkdir()

    declared, convention = resolve_plugin_directories(
        anchor=tmp_path,
        merged={"plugins_directories": [str(declared_dir)]},
        project_root=tmp_path / ".functualize",
        ambient_directory=False,
    )

    assert convention == []
    assert str(declared_dir.resolve()) in declared


# --- composition ------------------------------------------------------------


def test_declared_and_convention_compose_declared_first(tmp_path: Path) -> None:
    """Both are scanned, declared first (`spec.md` §C.2).

    Before this feature a declared value returned early and *suppressed* the
    project's own convention directory — a second, latent bug in the same
    function.
    """
    convention_dir = _plugins_at(tmp_path)
    declared_dir = tmp_path / "declared_plugins"
    declared_dir.mkdir()

    result = resolve_project_directories(tmp_path)
    assert str(convention_dir.resolve()) in result.plugin_directories

    declared, convention = resolve_plugin_directories(
        anchor=tmp_path,
        merged={"plugins_directories": [str(declared_dir)]},
        project_root=tmp_path / ".functualize",
    )
    combined = declared + convention
    assert combined.index(str(declared_dir.resolve())) < combined.index(
        str(convention_dir.resolve())
    )


def test_a_directory_reachable_both_ways_is_listed_once(tmp_path: Path) -> None:
    """Declaring the convention directory explicitly must not scan it twice.

    It counts as *declared*, because that is the stronger statement and it is
    what the caller warns about when nothing loads from it.
    """
    convention_dir = _plugins_at(tmp_path)

    declared, convention = resolve_plugin_directories(
        anchor=tmp_path,
        merged={"plugins_directories": [str(convention_dir)]},
        project_root=tmp_path / ".functualize",
    )

    assert str(convention_dir.resolve()) in declared
    assert convention == []


# --- standalone -------------------------------------------------------------


@pytest.mark.real_state_root
def test_standalone_mode_has_no_project_root(tmp_path: Path) -> None:
    """No `.functualize/` anywhere above means no convention directory.

    Not "some arbitrary ancestor's" — none. Marked `real_state_root` because
    the autouse sandbox fixture would otherwise create the very directory this
    test needs absent.
    """
    leaf = tmp_path / "loose" / "files"
    leaf.mkdir(parents=True)

    result = resolve_project_directories(leaf)

    assert result.convention_plugin_directories == ()
