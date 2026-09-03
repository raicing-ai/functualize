"""Terminal-owning builtins go through the orchestrator, not `App.suspend()`.

`func builtin config edit` spawns $EDITOR, which needs the real terminal. The
original implementation wrapped it in `App.suspend()`; Textual raises
`SuspendNotSupported` in inline mode, so the command reported a failure instead
of opening an editor. Surface switching — inline TUI, fullscreen TUI, direct
stdout — is the orchestrator's job, and this is the same EXCLUSIVE handoff a
`tty: TTY` job and a `!` shell command already take.
"""

from __future__ import annotations

from typing import Any

import pytest

from functualize._cli.builtins import BUILTIN_ROOT, get_builtin
from functualize._cli.tui import job_execution


class _FakeLog:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write(self, msg: object) -> None:
        self.lines.append(str(msg))

    def add_class(self, name: str) -> None:  # noqa: ARG002
        pass

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


class _FakeSuspend:
    def __init__(self, recorder: list[str]) -> None:
        self._recorder = recorder

    def __enter__(self) -> None:
        self._recorder.append("suspended")

    def __exit__(self, *exc: object) -> bool:
        self._recorder.append("resumed")
        return False


class _FakeApp:
    """The narrowest thing `run_builtin` actually touches.

    Carries a real ``FunctualizeApp``: the terminal decision now comes from the
    command tree, which is built from it.
    """

    def __init__(self, func_app: Any) -> None:
        self.output = _FakeLog()
        self.events: list[str] = []
        self.workers: list[Any] = []
        self.handoffs: list[list[str]] = []
        self.started_workers: list[Any] = []
        self.log = self
        self.warnings: list[str] = []
        self._func_app = func_app

    def warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def query_one(self, selector: str, widget_type: object = None) -> _FakeLog:  # noqa: ARG002
        return self.output

    def suspend(self) -> _FakeSuspend:
        return _FakeSuspend(self.events)

    def request_handoff(self, tokens: list[str]) -> None:
        self.handoffs.append(list(tokens))

    def run_worker(self, fn: Any, **kwargs: Any) -> None:  # noqa: ARG002
        self.started_workers.append(fn)


class _RunningWorker:
    name = "cmd-exec"
    is_running = True


@pytest.fixture
def app() -> _FakeApp:
    from functualize.app.core import FunctualizeApp

    return _FakeApp(FunctualizeApp(name="testapp"))


class TestTerminalOwningBuiltins:
    """`config edit` is the one true case in the registry."""

    def test_the_registry_still_marks_edit_as_terminal_owning(self) -> None:
        """The premise of the whole branch — asserted, not assumed."""
        root = get_builtin(BUILTIN_ROOT)
        assert root is not None
        assert root.needs_terminal(["config", "edit"]) is True

    def test_a_subcommand_name_is_matched_only_inside_its_own_family(self) -> None:
        """The root resolves the family before matching the subcommand.

        `skills` and the incoming `plugin` family both spell their installer
        `install`. Matched against a flattened set of every family's terminal
        subcommands, declaring `plugin install` terminal-owning would make
        `skills install` answer True too — a command the TUI would then hand
        the terminal to for no reason. Names cannot be picked around this:
        `install`/`uninstall` were chosen in the first place *because* nothing
        else used them, and `skills` shipped an `install` afterwards.

        Simulated rather than waiting for the real `plugin` family, so the
        guarantee is pinned before the family that would violate it exists.
        """
        from dataclasses import replace

        from functualize._cli.builtins import BUILTIN_COMMANDS, BuiltinCommand

        plugin = BuiltinCommand(
            "plugin",
            "Manage plugin packages",
            (("install", "Install"), ("uninstall", "Uninstall")),
            requires_subcommand=True,
            terminal_subcommands=("install", "uninstall"),
        )
        root = get_builtin(BUILTIN_ROOT)
        assert root is not None
        root = replace(root, children=(*BUILTIN_COMMANDS, plugin))

        # The family that declared it.
        assert root.needs_terminal(["plugin", "install"]) is True
        assert root.needs_terminal(["plugin", "uninstall"]) is True
        # The family that merely shares the word.
        assert root.needs_terminal(["skills", "install"]) is False
        # Still correct for the one true case, and for a near-miss.
        assert root.needs_terminal(["config", "edit"]) is True
        assert root.needs_terminal(["scaffold", "add"]) is False

    def test_the_decision_comes_from_the_command_node(self, app: _FakeApp) -> None:
        """One notion of "owns the terminal", shared with jobs.

        `ClickCommandNode` collapses the family-level predicate to a per-node
        bool while building the tree; `run_builtin` reads that rather than
        re-deriving it from `BuiltinCommand`.
        """
        assert job_execution._node_needs_terminal(app, [BUILTIN_ROOT, "config", "edit"])
        assert not job_execution._node_needs_terminal(
            app, [BUILTIN_ROOT, "config", "show"]
        )

    def test_config_edit_requests_a_handoff(self, app: _FakeApp) -> None:
        job_execution.run_builtin(app, [BUILTIN_ROOT, "config", "edit"])
        assert app.handoffs == [[BUILTIN_ROOT, "config", "edit"]]

    def test_config_edit_is_not_suspended(self, app: _FakeApp) -> None:
        """`App.suspend()` is unsupported in inline mode — never call it."""
        job_execution.run_builtin(app, [BUILTIN_ROOT, "config", "edit"])
        assert app.events == []

    def test_config_edit_does_not_start_a_worker(self, app: _FakeApp) -> None:
        """A terminal-owning command must not run captured on a thread."""
        job_execution.run_builtin(app, [BUILTIN_ROOT, "config", "edit"])
        assert app.started_workers == []

    def test_busy_worker_requests_no_handoff(self, app: _FakeApp) -> None:
        """Two terminal owners is what the EXCLUSIVE contract prevents."""
        app.workers = [_RunningWorker()]
        job_execution.run_builtin(app, [BUILTIN_ROOT, "config", "edit"])
        assert app.handoffs == []


class TestOrdinaryBuiltinsAreUnaffected:
    def test_config_show_runs_on_a_worker(self, app: _FakeApp) -> None:
        job_execution.run_builtin(app, [BUILTIN_ROOT, "config", "show"])
        assert app.handoffs == []
        assert len(app.started_workers) == 1

    def test_version_runs_on_a_worker(self, app: _FakeApp) -> None:
        job_execution.run_builtin(app, [BUILTIN_ROOT, "version"])
        assert app.handoffs == []
        assert len(app.started_workers) == 1


class TestTheFarSideHasNoBuiltinSpecialCase:
    """`_run_handoff` dispatches on the command tree, not on a token literal.

    An earlier draft matched `tokens[0] == "builtin"`. That put a special case
    back at exactly the seam `app/commands.py` exists to erase: "Nothing
    downstream needs to know which provider a node came from."
    """

    def test_a_non_job_node_runs_itself(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from functualize._cli import inline_tui

        ran: list[list[str]] = []
        node = _RecordingNode(ran)
        monkeypatch.setattr(
            inline_tui_commands(), "resolve_command_path", lambda _tree, _t: (node, [])
        )
        monkeypatch.setattr(inline_tui_commands(), "build_command_tree", lambda _a: [])

        func_app = _UnexecutableApp()
        inline_tui._run_handoff(func_app, [BUILTIN_ROOT, "config", "edit"])

        assert ran == [[]], "the node executed itself"
        assert func_app.executed == [], "a non-job is never routed to execute()"

    def test_no_builtin_literal_in_the_handoff_router(self) -> None:
        """The token check is gone, not merely bypassed."""
        import inspect

        from functualize._cli import inline_tui

        source = inspect.getsource(inline_tui._run_handoff)
        assert "BUILTIN_ROOT" not in source
        assert '"builtin"' not in source

    def test_an_unresolvable_path_falls_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nothing named — the caller's unknown-command handling must still run."""
        from functualize._cli import inline_tui

        monkeypatch.setattr(
            inline_tui_commands(),
            "resolve_command_path",
            lambda _tree, t: (None, list(t)),
        )
        monkeypatch.setattr(inline_tui_commands(), "build_command_tree", lambda _a: [])

        assert inline_tui._run_tree_node(_UnexecutableApp(), ["nope"]) is False


def inline_tui_commands() -> Any:
    """The module `_run_tree_node` imports its tree helpers from."""
    from functualize.app import commands

    return commands


class _RecordingNode:
    name = "edit"
    help_text = ""
    needs_terminal = True

    def __init__(self, sink: list[list[str]]) -> None:
        self._sink = sink

    def children(self) -> list[Any]:
        return []

    def params(self) -> list[Any]:
        return []

    def execute(self, args: Any) -> int:
        self._sink.append(list(args))
        return 0


class _UnexecutableApp:
    """A FunctualizeApp stand-in that fails loudly if asked to run a job."""

    def __init__(self) -> None:
        self.executed: list[str] = []

    def get_job(self, name: str) -> None:  # noqa: ARG002
        return None

    def execute(self, name: str, **kwargs: Any) -> None:  # noqa: ARG002
        self.executed.append(name)
        raise AssertionError(f"non-job routed to job execution: {name}")


class TestNodesCanRunThemselves:
    """A node that cannot supply its own click context is not self-contained."""

    def test_builtin_info_runs_through_the_node(self) -> None:
        """Regression: this failed with "No app context available."

        `builtin info` reads `ctx.find_root().obj["app"]`, and invoking a leaf
        directly never runs the root group's callback that would populate it.
        """
        from functualize.app.commands import build_command_tree, resolve_command_path
        from functualize.app.core import FunctualizeApp

        app = FunctualizeApp(name="testapp")
        node, remaining = resolve_command_path(
            build_command_tree(app), [BUILTIN_ROOT, "info"]
        )
        assert node is not None
        assert node.execute(remaining) == 0

    def test_the_context_carries_the_app(self) -> None:
        from functualize.app.commands import builtin_context_obj

        sentinel = object()
        assert builtin_context_obj(sentinel)["app"] is sentinel
