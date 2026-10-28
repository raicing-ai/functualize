"""Keep the settings owner and the public delivery boundary from drifting."""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import click
from click.testing import CliRunner

from functualize._cli.builtins._config import register_config
from functualize._types.enums import SURFACE_PREFERENCES, RenderSurface
from functualize.job import surface_hint
from functualize.plugin import FUNCTUALIZE_SETTINGS

SOURCE = Path(__file__).parents[2] / "src" / "functualize"

# These are delivery seams retained for the later architecture pass. The
# original pin had 15 sites; six settings/surface sites moved in this feature.
DELIVERY_IMPORTS = Counter(
    {
        ("app/commands.py", "functualize._cli.builtins", "get_builtin"): 1,
        ("app/adapters/cli.py", "functualize._cli.info", "explain_missing_job"): 1,
        (
            "app/adapters/cli.py",
            "functualize._cli.builtins",
            "register_builtin_commands",
        ): 1,
        ("app/adapters/cli.py", "functualize._cli.inline_tui", "launch_inline_tui"): 1,
        ("app/adapters/cli.py", "functualize._cli.info", "install_facts"): 1,
        ("app/adapters/cli.py", "functualize._cli.info", "discovery_failures"): 1,
        ("app/adapters/tui.py", "functualize._cli.inline_tui", "launch_inline_tui"): 1,
        (
            "app/adapters/click_params.py",
            "functualize._cli.annotation_utils",
            "_parse",
        ): 2,
    }
)


class _RuntimeImports(ast.NodeVisitor):
    def __init__(self) -> None:
        self.imports: list[tuple[str, str]] = []

    def visit_If(self, node: ast.If) -> None:
        # `plugin/protocols.py` has an annotation-only import of PendingExecution.
        # It is not an executable edge and is outside this feature's move.
        if isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
            for statement in node.orelse:
                self.visit(statement)
            return
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module and node.module.startswith("functualize._cli"):
            self.imports.extend(
                (node.module, alias.asname or alias.name) for alias in node.names
            )


def test_public_delivery_imports_are_the_nine_retained_sites() -> None:
    actual: Counter[tuple[str, str, str]] = Counter()
    for folder in ("app", "job", "types", "plugin", "workflow"):
        for path in (SOURCE / folder).rglob("*.py"):
            visitor = _RuntimeImports()
            visitor.visit(ast.parse(path.read_text()))
            actual.update(
                (str(path.relative_to(SOURCE)), module, name)
                for module, name in visitor.imports
            )

    assert actual == DELIVERY_IMPORTS
    assert sum(actual.values()) == 9
    assert not [
        module
        for _, module, _ in actual
        if module == "functualize._cli.config"
        or module == "functualize._cli.orchestrator"
        or module.startswith("functualize._cli.data")
    ]


def test_surface_vocabulary_has_one_owner() -> None:
    declarations = [
        path
        for path in SOURCE.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.ClassDef) and node.name == "RenderSurface"
    ]
    assert declarations == [SOURCE / "_types" / "enums.py"]
    assert SURFACE_PREFERENCES == ("panel", "stdout")
    assert (
        FUNCTUALIZE_SETTINGS.setting("tui.default_surface").choices
        == SURFACE_PREFERENCES
    )
    for value in SURFACE_PREFERENCES:
        assert surface_hint(value)(lambda: None).__functualize_surface_hint__ == value
    assert {surface.value for surface in RenderSurface} == {
        "panel",
        "stdout",
        "exclusive",
    }


def test_transitional_file_readers_are_gone() -> None:
    for name in ("read_global_config", "SettingsFileInfo", "resolve_cli_config_layers"):
        assert name not in (SOURCE / "_cli" / "config.py").read_text()


def test_root_marker_is_found_until_a_setting_contributes(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    config = tmp_path / ".functualize.toml"
    group = click.Group(name="func")
    register_config(group)
    runner = CliRunner()

    config.write_text("root = true\n")
    root_only = runner.invoke(group, ["config", "path"])
    assert root_only.exit_code == 0
    assert f"○ found   {config}" in root_only.output

    config.write_text('root = true\n[cli]\noutput = "json"\n')
    with_setting = runner.invoke(group, ["config", "path"])
    assert with_setting.exit_code == 0
    assert f"✓ used    {config}" in with_setting.output
