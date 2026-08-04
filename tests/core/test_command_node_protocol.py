"""C1.1 — `CommandNode` / `CommandProvider` protocol contract.

No consumers exist yet (`JobCommandProvider` is C1.2, `ClickCommandProvider` is
C1.3). What is pinned here is the *contract* those two must satisfy: the
protocols are runtime-checkable, a hand-rolled stub satisfies them structurally,
and the public import path is `functualize.plugin` — the same door
`Surface`/`PromptCollector` come through.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from functualize.plugin import CommandNode, CommandProvider


class _Leaf:
    """A runnable leaf — the minimum that should satisfy CommandNode."""

    def __init__(self, name: str, *, needs_terminal: bool = False) -> None:
        self.name = name
        self.help_text = f"help for {name}"
        self.needs_terminal = needs_terminal

    def children(self) -> list[CommandNode]:
        return []

    def params(self) -> list[object]:
        return []

    def execute(self, args: Sequence[str]) -> int:
        return 0


class _Group:
    """A navigable node with children — the duality/group case."""

    def __init__(self, name: str, children: list[CommandNode]) -> None:
        self.name = name
        self.help_text = f"group {name}"
        self.needs_terminal = False
        self._children = children

    def children(self) -> list[CommandNode]:
        return self._children

    def params(self) -> list[object]:
        return []

    def execute(self, args: Sequence[str]) -> int:
        return 0


class _Provider:
    def nodes(self) -> list[CommandNode]:
        return [_Leaf("cache"), _Group("infra", [_Leaf("provision")])]


class TestCommandNodeProtocol:
    def test_leaf_stub_satisfies_isinstance(self) -> None:
        assert isinstance(_Leaf("cache"), CommandNode)

    def test_group_stub_satisfies_isinstance(self) -> None:
        assert isinstance(_Group("infra", []), CommandNode)

    def test_missing_member_fails_isinstance(self) -> None:
        class _NoExecute:
            name = "x"
            help_text = "x"
            needs_terminal = False

            def children(self) -> list[CommandNode]:
                return []

            def params(self) -> list[object]:
                return []

        assert not isinstance(_NoExecute(), CommandNode)

    def test_missing_data_attribute_fails_isinstance(self) -> None:
        """`needs_terminal` is a bool attribute, so its absence must be caught."""

        class _NoNeedsTerminal:
            name = "x"
            help_text = "x"

            def children(self) -> list[CommandNode]:
                return []

            def params(self) -> list[object]:
                return []

            def execute(self, args: Sequence[str]) -> int:
                return 0

        assert not isinstance(_NoNeedsTerminal(), CommandNode)

    def test_needs_terminal_is_a_bool_not_a_predicate(self) -> None:
        """The recorded shape decision: a plain bool, resolved at construction.

        `BuiltinCommand.needs_terminal(args)` is a *method* because it models a
        command family; a CommandNode is one node, so the answer is static.
        """
        node = _Leaf("edit", needs_terminal=True)
        assert node.needs_terminal is True
        assert not callable(node.needs_terminal)


class TestCommandProviderProtocol:
    def test_provider_stub_satisfies_isinstance(self) -> None:
        assert isinstance(_Provider(), CommandProvider)

    def test_non_provider_fails_isinstance(self) -> None:
        class _NotAProvider:
            pass

        assert not isinstance(_NotAProvider(), CommandProvider)

    def test_provider_nodes_are_command_nodes(self) -> None:
        for node in _Provider().nodes():
            assert isinstance(node, CommandNode)


class TestPublicHome:
    def test_importable_from_functualize_plugin(self) -> None:
        """Recorded decision: same public door as Surface/PromptCollector.

        There is no `functualize.shell` package; the interactivity protocols are
        re-exported from `functualize.plugin`, so these sit beside them.
        """
        import functualize.plugin as plugin

        assert "CommandNode" in plugin.__all__
        assert "CommandProvider" in plugin.__all__

    def test_types_layer_stays_import_free(self) -> None:
        """The module must not drag internal packages into `_types` at runtime.

        `lint-imports` enforces this repo-wide; this is the local canary so a
        stray import shows up in this task's own test run.
        """
        import functualize._types.commands as mod

        source = __import__("inspect").getsource(mod)
        for forbidden in (
            "from functualize._app",
            "from functualize._cli",
            "from functualize._engine",
            "from functualize._discovery",
        ):
            assert forbidden not in source


@pytest.mark.parametrize("proto", [CommandNode, CommandProvider])
def test_protocols_are_runtime_checkable(proto: type) -> None:
    assert getattr(proto, "_is_runtime_protocol", False)
