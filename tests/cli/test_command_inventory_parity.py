"""Every surface that lists commands lists the *same* commands.

`tests/cli/test_schema_surface_parity.py` already guards one half of this: two
renderings of a command's *fields* must agree, because they once did not and
`Stdout`/`Shell` shipped as required MCP arguments. This guards the other half
— the **inventory**. Which commands exist at all?

That half was unguarded, and four surfaces disagreed simultaneously. Plugin
commands were reachable through `func <ns> <cmd>` and mounted on
`app.cli_command`, yet absent from the command tree (so the TUI browser, the
input bar, the pre-flight renderer and the node executor all missed them),
absent from `builtin info schema` (the surface every `--help` epilog advertises
to agents as "all commands"), and absent from shell completion. Every one of
those surfaces had a passing test suite.

The lesson encoded here: a surface that grows its own inventory fails in this
file rather than in a user's shell.
"""

from __future__ import annotations

import pytest

from functualize._cli.completions.data import extract_completion_data
from functualize._cli.info import command_schemas
from functualize.app import FunctualizeApp
from functualize.app.commands import build_command_tree
from functualize.app.config import JobSources, PluginSources

#: The namespace and command this fixture registers. Deliberately not "mcp":
#: the parity claim must hold for any plugin, and naming the one plugin that
#: happens to be installed in this checkout would hide an environment
#: dependence rather than remove it.
NAMESPACE = "demo"
PLUGIN_COMMANDS = ("serve", "stop")


@pytest.fixture
def app() -> FunctualizeApp:
    """A job, a namespaced plugin command, and the reserved subtree.

    Plugin discovery points at a group nobody publishes under, so the inventory
    is exactly what this fixture declares regardless of what is installed.
    """

    def alpha(count: int = 1) -> None:
        """A job."""

    instance = FunctualizeApp(
        name="parity",
        job_sources=JobSources(functions=[alpha]),
        plugin_sources=PluginSources(entry_point_group="functualize.plugins.__none__"),
    )
    for name in PLUGIN_COMMANDS:
        instance.extensions.register_plugin_command(
            name, lambda: None, help_text=f"Does {name}", namespace=NAMESPACE
        )
    return instance


# ── The five inventories ─────────────────────────────────────────────────────


def _tree_top_level(app: FunctualizeApp) -> set[str]:
    return {node.name for node in build_command_tree(app)}


def _schema_top_level(app: FunctualizeApp) -> set[str]:
    return {entry["path"][0] for entry in command_schemas(app)}


def _completion_top_level(app: FunctualizeApp) -> set[str]:
    return set(extract_completion_data(app).command_tree[""])


def _click_top_level(app: FunctualizeApp) -> set[str]:
    return set(app.cli_command.commands)


def _dispatch_listing(app: FunctualizeApp, capsys) -> set[str]:
    """What `func demo` prints, parsed back out of its listing."""
    from functualize._cli.main import _dispatch_group

    _dispatch_group(app, [NAMESPACE], set(), output_format="none")
    out = capsys.readouterr().out
    lines = out.splitlines()
    start = lines.index("Commands:")
    return {
        line.split()[0]
        for line in lines[start + 1 :]
        if line.strip() and line.startswith("  ")
    }


# ── Parity ───────────────────────────────────────────────────────────────────


class TestTopLevelInventoryAgrees:
    def test_every_surface_reports_the_namespace(self, app: FunctualizeApp) -> None:
        """The original defect, stated once for every surface that had it."""
        inventories = {
            "command tree": _tree_top_level(app),
            "info schema": _schema_top_level(app),
            "completion": _completion_top_level(app),
            "app.cli_command": _click_top_level(app),
        }
        missing = [name for name, inv in inventories.items() if NAMESPACE not in inv]
        assert not missing, f"{NAMESPACE!r} missing from: {', '.join(missing)}"

    def test_every_surface_reports_the_job(self, app: FunctualizeApp) -> None:
        inventories = {
            "command tree": _tree_top_level(app),
            "info schema": _schema_top_level(app),
            "completion": _completion_top_level(app),
            "app.cli_command": _click_top_level(app),
        }
        missing = [name for name, inv in inventories.items() if "alpha" not in inv]
        assert not missing, f"'alpha' missing from: {', '.join(missing)}"

    def test_every_surface_reports_the_reserved_subtree(
        self, app: FunctualizeApp
    ) -> None:
        inventories = {
            "command tree": _tree_top_level(app),
            "info schema": _schema_top_level(app),
            "completion": _completion_top_level(app),
            "app.cli_command": _click_top_level(app),
        }
        missing = [name for name, inv in inventories.items() if "builtin" not in inv]
        assert not missing, f"'builtin' missing from: {', '.join(missing)}"

    def test_the_three_kinds_are_the_same_three_everywhere(
        self, app: FunctualizeApp
    ) -> None:
        """Set equality on the declared inventory, so an *extra* row fails too."""
        expected = {"alpha", NAMESPACE, "builtin"}
        assert _tree_top_level(app) == expected
        assert _schema_top_level(app) == expected
        assert _click_top_level(app) == expected
        # Completion additionally offers the job's own flags after its name.
        assert expected <= _completion_top_level(app)


class TestNamespaceContentsAgree:
    def test_subcommands_match_across_surfaces(self, app: FunctualizeApp) -> None:
        expected = set(PLUGIN_COMMANDS)

        tree_node = next(n for n in build_command_tree(app) if n.name == NAMESPACE)
        assert {c.name for c in tree_node.children()} == expected

        schema = {
            entry["path"][1]
            for entry in command_schemas(app)
            if entry["path"][0] == NAMESPACE and len(entry["path"]) > 1
        }
        assert schema == expected

        completion = set(extract_completion_data(app).command_tree[NAMESPACE])
        assert completion == expected

        click_group = app.cli_command.commands[NAMESPACE]
        assert set(click_group.commands) == expected

    def test_dispatch_lists_the_same_subcommands(
        self, app: FunctualizeApp, capsys
    ) -> None:
        assert _dispatch_listing(app, capsys) == set(PLUGIN_COMMANDS)


class TestKindIsConsistent:
    def test_plugin_commands_are_published_as_plugin(self, app: FunctualizeApp) -> None:
        kinds = {
            entry["name"]: entry["kind"]
            for entry in command_schemas(app)
            if entry["path"][0] == NAMESPACE
        }
        assert kinds and set(kinds.values()) == {"plugin"}


class TestBuiltinDeclarationsMatchTheClickGroups:
    """`BUILTIN_COMMANDS` is a second list of what `func builtin ...` contains.

    The click groups are what actually runs; `BUILTIN_COMMANDS` is a
    declarative mirror that feeds shell completion, the TUI's command palette,
    and `builtin info`. Two lists of the same thing drift, and this one did
    immediately: adding `plugin available` left the declaration behind, so the
    command ran while completion and the palette denied it existed.

    Nothing guarded that, in a file whose entire subject is surfaces
    disagreeing about which commands exist. So: guard it.
    """

    def _mounted_builtin_group(self):
        import click

        from functualize._cli.builtins import register_builtin_commands

        root = click.Group(name="func")
        register_builtin_commands(root)
        return root.commands["builtin"]

    def test_every_declared_family_is_mounted(self) -> None:
        from functualize._cli.builtins import BUILTIN_COMMANDS

        mounted = set(self._mounted_builtin_group().commands)
        declared = {c.name for c in BUILTIN_COMMANDS}
        assert declared - mounted == set(), (
            f"declared but not mounted: {sorted(declared - mounted)}"
        )

    def test_every_mounted_family_is_declared(self) -> None:
        from functualize._cli.builtins import BUILTIN_COMMANDS

        mounted = set(self._mounted_builtin_group().commands)
        declared = {c.name for c in BUILTIN_COMMANDS}
        assert mounted - declared == set(), (
            f"mounted but not declared: {sorted(mounted - declared)}"
        )

    def test_declared_subcommands_match_each_group(self) -> None:
        """The drift that actually happened, for every family at once."""
        from functualize._cli.builtins import BUILTIN_COMMANDS

        builtin = self._mounted_builtin_group()
        problems: list[str] = []
        for command in BUILTIN_COMMANDS:
            if not command.subcommands:
                continue
            mounted = builtin.commands.get(command.name)
            group_commands = getattr(mounted, "commands", None)
            if group_commands is None:
                continue
            declared = {name for name, _ in command.subcommands}
            actual = set(group_commands)
            if declared != actual:
                problems.append(
                    f"{command.name}: declared={sorted(declared)} "
                    f"mounted={sorted(actual)}"
                )
        assert not problems, (
            "BUILTIN_COMMANDS drifted from the click groups:\n" + "\n".join(problems)
        )
