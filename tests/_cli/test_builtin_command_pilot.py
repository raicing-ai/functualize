"""End-to-end Pilot tests for invoking builtin `func` commands from the TUI.

These press *real keys* against a *real, running* TUI. That matters: the
reported defect ("invoking builtin jobs from the func TUI fails") was
invisible to the existing tests precisely because they asserted builtins
appear in the autocomplete *dropdown* — which passed off a hardcoded dict
while execution was never wired at all.

Two stacked failures are covered here:

1. The bar never became READY for a builtin (``_get_job_names()`` excluded
   them, so ``evaluate`` reported "Unknown: config" and set GREY), and
   ``action_execute`` returns silently on GREY — so Enter did nothing.
2. Even past that guard, execution routed to ``FunctualizeApp.execute()``,
   which raises ``JobNotFoundError`` for a name that was never a job.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize._cli.builtins import BUILTIN_NAMES
from functualize._cli.tui.app import FunctualizeInlineTUI
from functualize._cli.tui.bar import BarReadiness
from functualize.app.core import FunctualizeApp, JobSources

_JOB_MODULE = '''
from pydantic import BaseModel, Field


class ServeConfig(BaseModel):
    """Config for the serve job."""

    port: int = Field(default=3000, description="Port to bind")


def serve(config: ServeConfig) -> None:
    """Serve the app."""
'''


@pytest.fixture()
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tmp project with one discovered `serve` job."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.chdir(tmp_path)

    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "serve_job.py").write_text(_JOB_MODULE)
    return tmp_path


def _make_tui(project: Path) -> FunctualizeInlineTUI:
    func_app = FunctualizeApp(
        name="builtinapp", job_sources=JobSources(directories=[str(project / "jobs")])
    )
    return FunctualizeInlineTUI(func_app)


class TestBuiltinReadiness:
    """The bar must become READY for two-level builtin commands."""

    @pytest.mark.asyncio
    async def test_typing_builtin_group_is_not_unknown(self, project: Path) -> None:
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await pilot.press(*"builtin")
            await pilot.pause()

            assert tui._smart_bar.readiness is not BarReadiness.GREY
            assert "Unknown" not in tui._smart_bar.placeholder

    @pytest.mark.asyncio
    async def test_builtin_leaf_is_ready(self, project: Path) -> None:
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await pilot.press(*"builtin version")
            await pilot.pause()

            assert tui._smart_bar.readiness is BarReadiness.READY

    @pytest.mark.asyncio
    async def test_unknown_command_is_still_grey(self, project: Path) -> None:
        """The fix must not make every string look like a valid command."""
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await pilot.press(*"notacommand")
            await pilot.pause()

            assert tui._smart_bar.readiness is BarReadiness.GREY

    @pytest.mark.asyncio
    async def test_builtin_builds_no_pending_execution(self, project: Path) -> None:
        """A builtin is a recognized name but not a job — nothing to pend."""
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await pilot.press(*"builtin version")
            await pilot.pause()

            assert tui._pending is None


class TestBuiltinExecution:
    """Builtins execute via the subtree — ``builtin <name>``."""

    @pytest.mark.asyncio
    async def test_enter_runs_version(self, project: Path) -> None:
        from functualize import __version__

        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await _execute(pilot, tui, "builtin version")

            output = _output_text(tui)
            assert f"functualize {__version__}" in output
            assert "Done" in output

    @pytest.mark.asyncio
    async def test_enter_runs_config_path(self, project: Path) -> None:
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await _execute(pilot, tui, "builtin config path")

            output = _output_text(tui)
            assert "config.toml" in output
            assert "Error" not in output

    @pytest.mark.asyncio
    async def test_builtin_output_is_escaped_not_interpreted(
        self, project: Path
    ) -> None:
        """The output log has markup on; builtin output is plain text.

        ``builtin config show`` emits TOML section headers like ``[discovery]``,
        which would vanish (or raise) if fed to the log as markup.
        """
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await _execute(pilot, tui, "builtin config show")

            assert "[discovery]" in _output_text(tui)

    @pytest.mark.asyncio
    async def test_builtin_records_no_config_snapshot(self, project: Path) -> None:
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await _execute(pilot, tui, "builtin version")

            assert tui._snapshot_store.get_snapshots("builtin") == []

    @pytest.mark.asyncio
    async def test_job_still_executes(self, project: Path) -> None:
        """Routing builtins must not break ordinary job execution."""
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await _execute(pilot, tui, "serve")

            assert "Done" in _output_text(tui)


class TestBuiltinCompletionDropdown:
    """Completions must not resume the job list inside a builtin subtree.

    Reported against the config-inspector example (now part of
    ``examples/standalone/showcase``): typing
    ``builtin config path`` then space re-opened the dropdown listing every
    job and builtin, as if a fresh command were being typed.
    """

    @pytest.mark.asyncio
    async def test_no_command_list_after_a_subcommand(self, project: Path) -> None:
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await pilot.press(*"builtin config path ")
            await pilot.pause()

            assert _dropdown_items(tui) == []

    @pytest.mark.asyncio
    async def test_no_command_list_after_a_bare_builtin_leaf(
        self, project: Path
    ) -> None:
        """``builtin version`` takes no subcommands — not a reason to show jobs."""
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await pilot.press(*"builtin version ")
            await pilot.pause()

            assert _dropdown_items(tui) == []

    @pytest.mark.asyncio
    async def test_subcommands_are_still_offered(self, project: Path) -> None:
        """The fix must not suppress the completions that do belong here."""
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await pilot.press(*"builtin config ")
            await pilot.pause()

            items = _dropdown_items(tui)
            assert any(item.startswith("show") for item in items)
            assert any(item.startswith("path") for item in items)
            assert not any(item.startswith("serve") for item in items)

    @pytest.mark.asyncio
    async def test_job_flags_are_still_offered(self, project: Path) -> None:
        """Real jobs are unaffected by the builtin subtree."""
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await pilot.press(*"serve --")
            await pilot.pause()

            assert any("port" in item for item in _dropdown_items(tui))


class TestBuiltinPreflight:
    """The pre-flight panel must explain a builtin, not render blank.

    Builtins have no descriptor, so the job path bailed out early and left
    the panel empty — including for a fully-typed ``builtin config path``.
    """

    @pytest.mark.asyncio
    async def test_resolved_leaf_shows_what_will_run(self, project: Path) -> None:
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await pilot.press(*"builtin config path")
            await pilot.pause()

            text = _preflight_text(tui)
            assert "config path" in text
            # Post-C1 the preflight renders the *click* command's own help
            # rather than the registry blurb — one description, not two.
            assert "config file paths" in text

    @pytest.mark.asyncio
    async def test_group_lists_its_subcommands(self, project: Path) -> None:
        """A sub-group isn't a runnable leaf — show what can come next."""
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await pilot.press(*"builtin config")
            await pilot.pause()

            text = _preflight_text(tui)
            assert "Subcommands" in text
            for subcommand in ("show", "path", "edit"):
                assert subcommand in text

    @pytest.mark.asyncio
    async def test_group_requiring_a_subcommand_says_so(self, project: Path) -> None:
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await pilot.press(*"builtin cache")
            await pilot.pause()

            text = _preflight_text(tui)
            assert "rebuild" in text
            assert "Subcommands" in text

    @pytest.mark.asyncio
    async def test_leaf_without_subcommands(self, project: Path) -> None:
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await pilot.press(*"builtin version")
            await pilot.pause()

            text = _preflight_text(tui)
            assert "Show the functualize version" in text
            assert "Subcommands" not in text

    @pytest.mark.asyncio
    async def test_unknown_subcommand_is_called_out(self, project: Path) -> None:
        """Otherwise a typo looks exactly like a valid command."""
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await pilot.press(*"builtin config bogus")
            await pilot.pause()

            text = _preflight_text(tui)
            assert "unknown subcommand" in text
            # Sorted, not registry order — a listing a user scans should be
            # predictable rather than mirror declaration order.
            assert "edit, path, show" in text

    @pytest.mark.asyncio
    async def test_job_preflight_is_unaffected(self, project: Path) -> None:
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await pilot.press(*"serve")
            await pilot.pause()

            assert "port" in _preflight_text(tui)


class TestSingleSourceOfTruth:
    """Drift already happened once; these fail if any list re-lists builtins."""

    def test_every_derived_list_matches_the_registry(self) -> None:
        from functualize._cli.builtins import (
            BUILTIN_COMMANDS,
            builtin_descriptions,
        )
        from functualize._cli.completions.provenance import (
            CompletionProvenanceClassifier,
        )
        from functualize._cli.dispatch import _BUILTIN_NAMES
        from functualize._cli.introspect import _BUILTIN_DESCRIPTIONS
        from functualize._cli.tui.smart_bar_autocomplete import _BUILTIN_COMMANDS

        descriptions = builtin_descriptions()
        assert _BUILTIN_NAMES == BUILTIN_NAMES
        assert descriptions == _BUILTIN_DESCRIPTIONS
        assert descriptions == _BUILTIN_COMMANDS
        # The TUI no longer fabricates synthetic builtin descriptors; the
        # Job Browser lists the reserved subtree from the one command tree
        # (C1.4/C1.5), so the registry's children are asserted against the
        # tree instead.
        from functualize.app.commands import ClickCommandProvider

        child_names = {c.name for c in BUILTIN_COMMANDS}
        tree_app = FunctualizeApp(name="y", job_sources=JobSources(directories=[]))
        root = ClickCommandProvider(tree_app).nodes()[0]
        assert {c.name for c in root.children()} >= child_names

        app = FunctualizeApp(name="x", job_sources=JobSources(directories=[]))
        classifier = CompletionProvenanceClassifier(app)
        assert classifier._builtin_names == BUILTIN_NAMES

    def test_registry_matches_the_real_click_commands(self) -> None:
        """The registry must describe the commands actually registered.

        This is what makes the registry a *source of truth* rather than a
        sixth hardcoded copy: it is checked against click's own command tree.

        The tree is now nested: top level holds exactly ``builtin``, whose
        eight children are the first-party commands. The registry must mirror
        both levels — the root's identity and the children's subcommand maps.
        """
        import click

        from functualize._cli.builtins import (
            BUILTIN_COMMANDS,
            BUILTIN_NAMES,
            BUILTIN_ROOT,
            register_builtin_commands,
        )

        cli = click.Group(name="func")
        register_builtin_commands(cli)

        ctx = click.Context(cli)
        # Top level: exactly one command — ``builtin``.
        assert set(cli.list_commands(ctx)) == BUILTIN_NAMES

        # Drill into the ``builtin`` group — its children are BUILTIN_COMMANDS.
        builtin_group = cli.get_command(ctx, BUILTIN_ROOT)
        assert builtin_group is not None, "builtin group not registered"
        builtin_ctx = click.Context(builtin_group)
        assert set(builtin_group.list_commands(builtin_ctx)) == {
            c.name for c in BUILTIN_COMMANDS
        }

        for command in BUILTIN_COMMANDS:
            if not command.subcommands:
                continue
            child = builtin_group.get_command(builtin_ctx, command.name)
            registered = set(child.list_commands(click.Context(child)))
            assert set(command.subcommand_map) == registered, (
                f"{command.name}: registry subcommands drifted from click's"
            )


async def _execute(pilot, tui: FunctualizeInlineTUI, text: str) -> None:
    """Type `text` and run it, the way a user actually does.

    The autocomplete dropdown claims Enter first (to accept the highlighted
    completion), so a real user dismisses it before Enter executes — Escape
    here is that dismissal, not a workaround.
    """
    await pilot.press(*text)
    await pilot.pause()
    if tui.is_autocomplete_visible():
        await pilot.press("escape")
        await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()
    await tui.workers.wait_for_complete()
    await pilot.pause()


def _dropdown_items(tui: FunctualizeInlineTUI) -> list[str]:
    """Return the completion dropdown's visible entries.

    Reads the live widget rather than the completer, because the report was
    about what the dropdown *shows*.
    """
    from functualize._cli.tui.functualize_autocomplete import FunctualizeAutoComplete

    ac = tui.query_one(FunctualizeAutoComplete)
    option_list = getattr(ac, "option_list", None)
    if option_list is None or not ac.display:
        return []
    return [
        str(option_list.get_option_at_index(i).prompt)
        for i in range(option_list.option_count)
    ]


def _preflight_text(tui: FunctualizeInlineTUI) -> str:
    from textual.widgets import RichLog

    log = tui.query_one("#preflight-summary", RichLog)
    if not log.display:
        return ""
    return "\n".join(strip.text for strip in log.lines)


def _output_text(tui: FunctualizeInlineTUI) -> str:
    from textual.widgets import RichLog

    log = tui.query_one("#output-log", RichLog)
    return "\n".join(strip.text for strip in log.lines)
