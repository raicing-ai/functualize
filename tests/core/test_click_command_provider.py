"""C1.3 — `ClickCommandProvider` over the reserved `builtin` subtree.

Acceptance: `builtin` -> `cache` -> `clear` reachable as three levels of
`children()`; `execute()` runs through click; and `needs_terminal` honours
`BuiltinCommand.needs_terminal(args)` — with `config edit` as the true case.

That last one is where C1.1's shape decision gets paid off: the family-level
predicate collapses to a per-node bool while the provider builds the tree.
"""

from __future__ import annotations

import pytest

from functualize.app.commands import ClickCommandProvider
from functualize.app.core import FunctualizeApp
from functualize.plugin import CommandNode, CommandProvider


@pytest.fixture
def app() -> FunctualizeApp:
    return FunctualizeApp(name="testapp")


def _child(node: CommandNode, name: str) -> CommandNode:
    for child in node.children():
        if child.name == name:
            return child
    raise AssertionError(f"no {name!r} in {[c.name for c in node.children()]}")


def _root(app: FunctualizeApp) -> CommandNode:
    nodes = ClickCommandProvider(app).nodes()
    assert len(nodes) == 1
    return nodes[0]


class TestProtocolConformance:
    def test_provider(self, app) -> None:
        assert isinstance(ClickCommandProvider(app), CommandProvider)

    def test_nodes(self, app) -> None:
        for node in ClickCommandProvider(app).nodes():
            assert isinstance(node, CommandNode)


class TestThreeLevelDrillDown:
    def test_root_is_builtin(self, app) -> None:
        assert _root(app).name == "builtin"

    def test_builtin_cache_clear(self, app) -> None:
        cache = _child(_root(app), "cache")
        clear = _child(cache, "clear")
        assert clear.name == "clear"
        assert clear.children() == []

    def test_families_are_present(self, app) -> None:
        names = {c.name for c in _root(app).children()}
        # The subtree B2b mounts.
        assert {"cache", "config", "state", "info"} <= names

    def test_nodes_are_command_nodes_at_every_level(self, app) -> None:
        root = _root(app)
        for family in root.children():
            assert isinstance(family, CommandNode)
            for leaf in family.children():
                assert isinstance(leaf, CommandNode)


class TestNeedsTerminal:
    """The C1.1 decision, implemented: family predicate -> per-node bool."""

    def test_config_edit_needs_the_terminal(self, app) -> None:
        config = _child(_root(app), "config")
        assert _child(config, "edit").needs_terminal is True

    def test_config_show_does_not(self, app) -> None:
        config = _child(_root(app), "config")
        assert _child(config, "show").needs_terminal is False

    def test_it_is_a_bool_not_a_callable(self, app) -> None:
        edit = _child(_child(_root(app), "config"), "edit")
        assert isinstance(edit.needs_terminal, bool)
        assert not callable(edit.needs_terminal)

    def test_matches_the_builtin_command_predicate(self, app) -> None:
        """Equivalence with the source of truth it collapses."""
        from functualize._cli.builtins import get_builtin

        config = _child(_root(app), "config")
        source = get_builtin("config")
        assert source is not None
        for leaf in config.children():
            assert leaf.needs_terminal == source.needs_terminal([leaf.name])

    def test_group_nodes_do_not_need_the_terminal(self, app) -> None:
        assert _root(app).needs_terminal is False


class TestExecute:
    def test_runs_through_click(self, app, tmp_path, monkeypatch, capsys) -> None:
        monkeypatch.chdir(tmp_path)
        cache = _child(_root(app), "cache")
        assert _child(cache, "check").execute([]) == 0
        assert "No cache file found" in capsys.readouterr().out


class TestParamsBridge:
    def test_params_are_field_descriptors(self, app) -> None:
        from functualize._types.descriptors import FieldDescriptor

        info = _child(_root(app), "info")
        for param in info.params():
            assert isinstance(param, FieldDescriptor)

    def test_help_is_excluded(self, app) -> None:
        info = _child(_root(app), "info")
        assert "help" not in {p.name for p in info.params()}

    def test_known_option_is_exposed(self, app) -> None:
        info = _child(_root(app), "info")
        assert "job" in {p.name for p in info.params()}


class TestHelpText:
    def test_families_have_help(self, app) -> None:
        for family in _root(app).children():
            assert family.help_text, f"{family.name} has no help text"
