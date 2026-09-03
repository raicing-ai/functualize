"""AC32 / AC33 — every new command, from all three surfaces.

No earlier task owns this. Each one tested its own commands on whichever
surface was convenient, which leaves the cross-product unchecked: a command can
be correct from the direct CLI and unreachable from a consumer application, or
present in both and dead in the inline shell. The three surfaces resolve
commands by genuinely different routes --

- **direct CLI** — `_cli/main.py` builds the `builtin` group itself;
- **consumer app** — `CliAdapter` mounts the same subtree into somebody else's
  script (`register_builtins=True`);
- **inline shell** — the TUI resolves through `app/commands.py`'s node tree and
  either runs on a worker or hands the terminal over.

-- so agreement between them is a property, not a given.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from functualize._cli.builtins import BUILTIN_ROOT, get_builtin

#: Every command this feature added, and whether it changes anything.
_READ_ONLY = [
    ["builtin", "self", "doctor"],
    ["builtin", "info"],
    ["builtin", "plugin", "list"],
]
_MUTATING = [
    ["builtin", "self", "update"],
    ["builtin", "self", "install", "requests"],
    ["builtin", "plugin", "install", "functualize-http"],
    ["builtin", "plugin", "uninstall", "functualize-http"],
]


class TestReadOnlyCommandsWorkOnBothCliSurfaces:
    """`cli_run` is parametrized over `func` and `app`, so each of these runs
    twice: once through `_cli/main.py` and once through `CliAdapter`."""

    @pytest.mark.parametrize("argv", _READ_ONLY, ids=lambda a: " ".join(a[1:]))
    def test_it_succeeds(self, cli_run, tmp_path: Path, argv: list[str]) -> None:
        assert cli_run(argv, cwd=tmp_path).exit_code == 0

    @pytest.mark.parametrize("argv", _READ_ONLY, ids=lambda a: " ".join(a[1:]))
    def test_it_produces_output(self, cli_run, tmp_path: Path, argv: list[str]) -> None:
        """A command that exits 0 and says nothing has not been exercised."""
        assert cli_run(argv, cwd=tmp_path).stdout.strip()


class TestMutatingCommandsRefuseIdenticallyOnBothCliSurfaces:
    """The refusal contract must not depend on which script you typed.

    A consumer application resolves a *different* owning distribution, so this
    is the place the two surfaces could most plausibly disagree.
    """

    @pytest.mark.parametrize("argv", _MUTATING, ids=lambda a: " ".join(a[1:]))
    def test_a_degraded_mode_refuses_with_three(
        self, cli_run, tmp_path: Path, argv: list[str], monkeypatch
    ) -> None:
        from functualize._cli import package_ops

        monkeypatch.setattr(package_ops, "_call", lambda argv: 0)
        result = cli_run(
            [*argv, "--yes"], cwd=tmp_path, env={"FUNCTUALIZE_RUNTIME": "unknown"}
        )
        assert result.exit_code == 3
        assert result.stdout == ""


class TestTheInlineShellSeesTheSameTree:
    """The third surface, without a Pilot run.

    The TUI resolves commands through `app/commands.py`, which builds its node
    tree from the same registry -- so a name present in one and absent from the
    other is invisible in exactly one surface. That is asserted here directly;
    the terminal-handoff behaviour is covered in `test_builtin_handoff.py`.
    """

    @pytest.mark.parametrize(
        ("family", "subcommand"),
        [
            ("self", "doctor"),
            ("self", "update"),
            ("self", "install"),
            ("self", "python"),
            ("self", "uv"),
            ("plugin", "list"),
            ("plugin", "install"),
            ("plugin", "uninstall"),
        ],
    )
    def test_the_registry_knows_it(self, family: str, subcommand: str) -> None:
        entry = get_builtin(family)
        assert entry is not None
        assert subcommand in {name for name, _ in entry.subcommands}

    @pytest.mark.parametrize("family", ["self", "plugin"])
    def test_the_node_tree_carries_the_family(self, family: str) -> None:
        from functualize.app.commands import build_command_tree, resolve_command_path
        from functualize.app.core import FunctualizeApp

        app = FunctualizeApp(name="surfacecheck")
        node, remaining = resolve_command_path(
            build_command_tree(app), [BUILTIN_ROOT, family]
        )
        assert node is not None, f"`builtin {family}` does not resolve in the shell"
        assert remaining == []

    @pytest.mark.parametrize(
        ("family", "subcommand", "terminal"),
        [
            ("self", "doctor", False),
            ("self", "update", True),
            ("self", "install", True),
            ("self", "python", True),
            ("self", "uv", True),
            ("plugin", "list", False),
            ("plugin", "install", True),
            ("plugin", "uninstall", True),
        ],
    )
    def test_terminal_ownership_is_answered_per_subcommand(
        self, family: str, subcommand: str, terminal: bool
    ) -> None:
        entry = get_builtin(family)
        assert entry is not None
        assert entry.needs_terminal([subcommand]) is terminal


@pytest.mark.surfaces("app")
class TestAConsumerApplication:
    def test_it_reports_its_own_installation(self, cli_run, tmp_path: Path) -> None:
        result = cli_run(["builtin", "info", "all", "--json"], cwd=tmp_path)
        assert "install" in json.loads(result.stdout)

    def test_it_can_list_its_own_extensions(self, cli_run, tmp_path: Path) -> None:
        assert (
            "functualize-inline"
            in cli_run(["builtin", "plugin", "list"], cwd=tmp_path).stdout
        )


class TestAnApplicationThatDeclinesTheBuiltinTree:
    """AC33 — `register_builtins=False` must still produce a working app.

    The feature mounts two more families into that subtree, and a mount that
    ran unconditionally would break every application that opted out.
    """

    def _adapter(self, tmp_path: Path, *, register: bool):
        from functualize.app.adapters.cli import CliAdapter
        from functualize.app.core import FunctualizeApp, JobSources

        jobs = tmp_path / "jobs"
        jobs.mkdir(exist_ok=True)
        (jobs / "hello.py").write_text("def hello() -> str:\n    return 'hi'\n")
        app = FunctualizeApp(
            name="declining", job_sources=JobSources(directories=[str(jobs)])
        )
        app.refresh()
        adapter = CliAdapter()
        # `register_builtins` is a setup-phase argument, not a constructor one:
        # the adapter is instantiated before it has an app to wire.
        adapter(app, register_builtins=register)
        return adapter

    def test_it_constructs(self, tmp_path: Path) -> None:
        assert self._adapter(tmp_path, register=False) is not None

    def test_it_has_no_builtin_group(self, tmp_path: Path) -> None:
        adapter = self._adapter(tmp_path, register=False)
        assert BUILTIN_ROOT not in adapter.cli_command.commands

    def test_the_jobs_are_still_there(self, tmp_path: Path) -> None:
        """The negative half alone would pass on an app that mounted nothing at
        all, which is not the property."""
        adapter = self._adapter(tmp_path, register=False)
        assert "hello" in adapter.cli_command.commands

    def test_opting_in_does_mount_the_new_families(self, tmp_path: Path) -> None:
        """The contrast that makes the assertion above mean something."""
        adapter = self._adapter(tmp_path, register=True)
        builtin = adapter.cli_command.commands[BUILTIN_ROOT]
        assert {"self", "plugin"} <= set(builtin.commands)
