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


def _calls(path: Path) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Call)
    ]


def test_declared_settings_have_no_process_registry_or_second_file_reader() -> None:
    catalog = (SOURCE / "_cli" / "data" / "func_settings.py").read_text()
    for name in (
        "register_settings",
        "_REGISTERED",
        "_PREBOOT_OVERRIDES",
        "set_preboot_override",
        "preboot_overrides",
    ):
        assert name not in catalog

    # Settings documents are parsed by settings_layers. The TUI's job-config
    # panels and project_dirs' discovery reader answer different questions.
    for relative in ("_cli/main.py", "_cli/config.py", "_cli/data/func_settings.py"):
        for call in _calls(SOURCE / relative):
            assert not (
                isinstance(call.func, ast.Attribute)
                and call.func.attr in {"loads", "load", "read_bytes"}
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "tomllib"
            ), relative
        assert "tomllib" not in (SOURCE / relative).read_text()


def test_declared_boot_reads_do_not_use_the_job_config_chain() -> None:
    boot = SOURCE / "_app" / "boot.py"
    tree = ast.parse(boot.read_text())
    declared = {setting.name for setting in FUNCTUALIZE_SETTINGS.settings}
    chain_reads: set[tuple[str, str]] = set()
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
            continue
        if call.func.attr != "resolve" or len(call.args) < 2:
            continue
        if not (
            isinstance(call.func.value, ast.Attribute)
            and call.func.value.attr == "_resolution_chain"
        ):
            continue
        if all(
            isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            for arg in call.args[:2]
        ):
            chain_reads.add((call.args[0].value, call.args[1].value))
        else:
            raise AssertionError("dynamic setting read through ResolutionChain")
    assert {f"{section}.{key}" for key, section in chain_reads}.isdisjoint(declared)
    assert chain_reads <= {
        ("strict_hierarchy_validation", "general"),
        ("max_invoke_depth", "general"),
    }


def test_generated_flags_have_one_schema_source_on_both_cli_doors() -> None:
    main = (SOURCE / "_cli" / "main.py").read_text()
    adapter = (SOURCE / "app" / "adapters" / "cli.py").read_text()
    assert main.count("generated_setting_options(FUNCTUALIZE_SETTINGS)") == 1
    assert adapter.count("generated_setting_options(app_instance.settings_schema)") == 1
    assert "passed_setting_flags(FUNCTUALIZE_SETTINGS, generated)" in main
    assert "passed_setting_flags(app.settings_schema, values)" in adapter
