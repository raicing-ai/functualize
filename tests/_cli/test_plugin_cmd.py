"""`builtin plugin list / install / uninstall`.

The listing is read-only and runs against the real installed metadata, which is
what makes AC15 meaningful here: `functualize-inline` is genuinely installed in
this checkout and genuinely registers in only one group.

The mutating pair reuses `package_ops`, so the safety story is the one
`test_self_manage.py` documents: `_call` is the single execution seam, and the
confirmation prompt means a command can be asserted on without being run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli import manifest, package_ops
from functualize._cli.plugin_cmd import (
    ExtensionEntry,
    discover_extensions,
    render_extensions,
)


@pytest.fixture
def calls(monkeypatch) -> list[list[str]]:
    seen: list[list[str]] = []
    monkeypatch.setattr(package_ops, "_call", lambda argv: seen.append(list(argv)) or 0)
    return seen


@pytest.fixture
def no_external_tools(monkeypatch) -> None:
    monkeypatch.setattr(package_ops, "resolve_uv", lambda: "/opt/uv")
    monkeypatch.setattr(package_ops, "resolve_pipx", lambda: "/opt/pipx")


class TestDiscovery:
    def test_it_finds_an_extension_registered_in_only_one_group(self) -> None:
        """AC15, and the reason discovery is not built from `loaded_plugins`.

        `functualize-inline` registers under `functualize.interactivity_providers`
        and nothing else. A listing derived from the plugin loader's own view
        would omit the canonical example the documentation uses.
        """
        entries = discover_extensions()
        inline = [
            e for e in entries if e.group == "functualize.interactivity_providers"
        ]
        assert inline, "functualize-inline should be installed in this checkout"
        assert inline[0].registered_name == "inline"
        assert inline[0].distribution == "functualize-inline"

    def test_both_names_are_carried_and_they_differ(self) -> None:
        """The whole reason the entry holds two fields.

        The framework calls it `inline`; a package manager calls it
        `functualize-inline`. `uninstall` needs the second and a reader needs
        the first, so collapsing them into one loses a command.
        """
        entries = discover_extensions()
        differing = [
            e for e in entries if e.distribution and e.distribution != e.registered_name
        ]
        assert differing

    def test_it_spans_more_than_one_group(self) -> None:
        """A scan that only ever found `functualize.plugins` would pass every
        other assertion here while missing most of what is installed."""
        assert len({e.group for e in discover_extensions()}) > 1

    def test_job_sources_are_not_listed_as_extensions(self) -> None:
        """`functualize.jobs` supplies work to run, not new capability. Listing
        it would invite a `plugin uninstall` that removes somebody's jobs."""
        assert all(e.group != "functualize.jobs" for e in discover_extensions())

    def test_every_group_carries_the_prefix(self) -> None:
        assert all(e.group.startswith("functualize.") for e in discover_extensions())

    def test_entries_are_deduplicated(self) -> None:
        """A path appearing twice in `sys.path` yields each distribution twice
        and would double every row."""
        entries = discover_extensions()
        assert len(entries) == len(set(entries))


class TestRendering:
    def test_a_row_shows_both_names(self) -> None:
        lines = render_extensions(
            [
                ExtensionEntry(
                    "inline",
                    "functualize-inline",
                    "functualize.interactivity_providers",
                )
            ]
        )
        body = "\n".join(lines)
        assert "inline" in body
        assert "functualize-inline" in body

    def test_the_group_heads_its_section(self) -> None:
        lines = render_extensions(
            [
                ExtensionEntry("http", "functualize-http", "functualize.plugins"),
                ExtensionEntry("mcp", "functualize-mcp", "functualize.plugins"),
            ]
        )
        assert lines[0] == "plugins:"
        assert len(lines) == 3

    def test_an_unknown_distribution_is_said_rather_than_guessed(self) -> None:
        """Printing the registered name in the distribution column would tell a
        user to `plugin uninstall inline`, which is not a package."""
        lines = render_extensions(
            [ExtensionEntry("thing", None, "functualize.plugins")]
        )
        assert "unknown distribution" in "\n".join(lines)

    def test_an_empty_listing_says_so(self) -> None:
        assert render_extensions([]) == ["  no extensions registered"]


class TestListCommand:
    def test_it_lists_the_inline_provider(self, cli_run, tmp_path: Path) -> None:
        result = cli_run(["builtin", "plugin", "list"], cwd=tmp_path)
        assert result.exit_code == 0
        assert "functualize-inline" in result.stdout
        assert "interactivity_providers" in result.stdout

    def test_the_json_form_carries_all_three_fields(
        self, cli_run, tmp_path: Path
    ) -> None:
        result = cli_run(
            ["builtin", "plugin", "list", "--format", "json"], cwd=tmp_path
        )
        payload = json.loads(result.stdout)
        assert payload
        assert set(payload[0]) == {"name", "distribution", "group"}

    def test_it_spells_structured_output_format_json(
        self, cli_run, tmp_path: Path
    ) -> None:
        """AC30a — new commands use `--format json`, and ship only one spelling
        for the question."""
        assert (
            cli_run(["builtin", "plugin", "list", "--json"], cwd=tmp_path).exit_code
            != 0
        )

    def test_listing_needs_no_owned_environment(self, cli_run, tmp_path: Path) -> None:
        """Reading metadata is not managing an installation. Refusing here
        would make a degraded install unable to see what it has."""
        result = cli_run(
            ["builtin", "plugin", "list"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "unknown"},
        )
        assert result.exit_code == 0


class TestMutatingCommands:
    @pytest.mark.parametrize("verb", ["install", "uninstall"])
    def test_a_degraded_mode_refuses_and_runs_nothing(
        self, cli_run, tmp_path: Path, calls, verb: str
    ) -> None:
        """AC16."""
        result = cli_run(
            ["builtin", "plugin", verb, "functualize-http", "--yes"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "unknown"},
        )
        assert result.exit_code == 3
        assert result.stdout == ""
        assert calls == []

    @pytest.mark.parametrize("verb", ["install", "uninstall"])
    def test_the_command_is_printed_before_any_side_effect(
        self, cli_run, tmp_path: Path, calls, no_external_tools, verb: str
    ) -> None:
        """AC18 — printed, then declined, so nothing ran at all."""
        result = cli_run(
            ["builtin", "plugin", verb, "functualize-http"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "standalone"},
        )
        assert "/opt/uv" in result.stdout
        assert "functualize-http" in result.stdout
        assert calls == []


@pytest.mark.surfaces("func")
class TestBookkeeping:
    def _record(self, xdg_dirs) -> manifest.InstallRecord | None:
        registry = manifest.load(
            manifest.manifest_path(Path(xdg_dirs.functualize_config))
        )
        return registry.installations[0] if registry.installations else None

    def test_an_install_is_recorded_under_plugins(
        self, cli_run, tmp_path: Path, calls, no_external_tools, xdg_dirs
    ) -> None:
        cli_run(
            ["builtin", "plugin", "install", "functualize-http", "--yes"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "standalone"},
        )
        record = self._record(xdg_dirs)
        assert record is not None
        assert "functualize-http" in record.plugins
        assert "functualize-http" not in record.packages

    def test_an_uninstall_forgets_it(
        self, cli_run, tmp_path: Path, calls, no_external_tools, xdg_dirs
    ) -> None:
        """Not optional bookkeeping: a name left recorded is reinstalled by the
        next `self update`, undoing the uninstall silently and at a distance."""
        for verb in ("install", "uninstall"):
            cli_run(
                ["builtin", "plugin", verb, "functualize-http", "--yes"],
                cwd=tmp_path,
                env={"FUNCTUALIZE_RUNTIME": "standalone"},
            )
        record = self._record(xdg_dirs)
        assert record is not None
        assert "functualize-http" not in record.plugins

    def test_a_failed_uninstall_keeps_the_record(
        self, cli_run, tmp_path: Path, no_external_tools, xdg_dirs, monkeypatch
    ) -> None:
        """The package is still installed, so `self update` should still put it
        back after an upgrade."""
        monkeypatch.setattr(package_ops, "_call", lambda argv: 0)
        cli_run(
            ["builtin", "plugin", "install", "functualize-http", "--yes"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "standalone"},
        )
        monkeypatch.setattr(package_ops, "_call", lambda argv: 5)
        result = cli_run(
            ["builtin", "plugin", "uninstall", "functualize-http", "--yes"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "standalone"},
        )
        assert result.exit_code == 5
        record = self._record(xdg_dirs)
        assert record is not None
        assert "functualize-http" in record.plugins

    def test_forgetting_something_never_recorded_changes_nothing(
        self, xdg_dirs
    ) -> None:
        config = Path(xdg_dirs.functualize_config)
        manifest.register(
            config,
            binary_path="/bin/func",
            runtime_mode="standalone",
            owning_distribution="functualize",
            python_version="3.13.0",
            functualize_version="0.1.2",
        )
        assert (
            manifest.forget_addition(config, binary_path="/bin/func", name="never-here")
            is False
        )


class TestSecondInstallKeepsTheFirst:
    """AC17 as far as it can be asserted in-process.

    The real proof is a container (`k-plugin-lifecycle.toml`, task 9.1) — this
    pins the mechanism that makes it true: the command uv is given restates
    every prior requirement, because `uv tool install` is declarative.
    """

    def test_the_second_install_command_still_names_the_first(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        (tmp_path / "uv-receipt.toml").write_text(
            "[tool]\nrequirements = ["
            '{ name = "functualize", extras = ["cli"] }, '
            '{ name = "functualize-http" }]\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(package_ops, "resolve_uv", lambda: "/opt/uv")
        monkeypatch.setattr(package_ops.sys, "prefix", str(tmp_path))

        from functualize._cli.runtime import Detection, InstallMode

        (command,) = package_ops.install_commands(
            Detection(mode=InstallMode.TOOL_UV, owning_distribution="functualize"),
            "functualize-mcp",
        )
        assert "functualize-http" in command
        assert "functualize-mcp" in command


class TestTerminalOwnership:
    @pytest.mark.parametrize("name", ["install", "uninstall"])
    def test_the_mutating_pair_hands_over_the_terminal(self, name: str) -> None:
        """AC19 — uv draws progress and an index can prompt for credentials."""
        from functualize._cli.builtins import get_builtin

        entry = get_builtin("plugin")
        assert entry is not None
        assert entry.needs_terminal([name]) is True

    def test_list_stays_on_the_worker(self) -> None:
        from functualize._cli.builtins import get_builtin

        entry = get_builtin("plugin")
        assert entry is not None
        assert entry.needs_terminal(["list"]) is False


class TestItIsMounted:
    def test_the_family_is_reachable(self, cli_run, tmp_path: Path) -> None:
        assert cli_run(["builtin", "plugin", "--help"], cwd=tmp_path).exit_code == 0

    def test_the_registry_and_click_agree(self) -> None:
        """The shell's completion tree is built from the registry, not from
        click, so a subcommand in one and not the other is invisible in exactly
        one surface."""
        from functualize._cli.builtins import BUILTIN_COMMANDS
        from functualize._cli.plugin_cmd import plugin_app

        entry = next(c for c in BUILTIN_COMMANDS if c.name == "plugin")
        assert {name for name, _ in entry.subcommands} == set(plugin_app.commands)

    def test_no_new_top_level_name(self, cli_run, tmp_path: Path) -> None:
        """AC30 — `plugin` is a child of `builtin`, not a top-level command."""
        assert cli_run(["plugin", "list"], cwd=tmp_path).exit_code != 0


# ---------------------------------------------------------------------------
# Property: the receipt merge round-trips
# ---------------------------------------------------------------------------

_NAMES = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Nd")),
    min_size=1,
    max_size=12,
).map(lambda s: f"pkg-{s}")


@st.composite
def _requirements(draw) -> package_ops.Requirement:
    """A receipt entry in one of the shapes uv actually writes."""
    name = draw(_NAMES)
    fields: dict[str, object] = {"name": name}
    shape = draw(st.sampled_from(["bare", "specifier", "url", "extras", "marker"]))
    if shape == "specifier":
        fields["specifier"] = draw(st.sampled_from(["==1.0", ">=2", "~=3.1"]))
    elif shape == "url":
        fields["url"] = "https://example.invalid/x.zip"
    elif shape == "extras":
        fields["extras"] = draw(
            st.lists(st.sampled_from(["cli", "all", "dev"]), min_size=1, max_size=2)
        )
    elif shape == "marker":
        fields["marker"] = "sys_platform == 'win32'"
    return package_ops.Requirement(name, fields)


@pytest.mark.slow
class TestTheMergeRoundTrips:
    @given(requirements=st.lists(_requirements(), min_size=1, max_size=6))
    def test_every_prior_requirement_survives(self, requirements) -> None:
        """The property AC17 rests on.

        `uv tool install` is declarative and has no `add`. Whatever the receipt
        held has to reappear in the command, or installing one extension
        uninstalls the others.
        """
        receipt = package_ops.Receipt(requirements=tuple(requirements))
        args = package_ops.merge_receipt(receipt, "functualize", "new-package")
        flat = " ".join(args)
        for requirement in requirements:
            assert requirement.name in flat

    @given(requirements=st.lists(_requirements(), min_size=1, max_size=6))
    def test_the_new_package_is_always_added(self, requirements) -> None:
        receipt = package_ops.Receipt(requirements=tuple(requirements))
        args = package_ops.merge_receipt(receipt, "functualize", "brand-new")
        assert "brand-new" in args

    @given(
        requirement=_requirements(),
        unknown=st.sampled_from(["git", "rev", "editable", "index"]),
    )
    def test_an_unknown_key_is_never_silently_dropped(
        self, requirement, unknown: str
    ) -> None:
        """The round-trip guarantee, stated as its contrapositive.

        Rendering cannot carry a key it does not understand, so the only honest
        outcomes are "reproduced exactly" or "refused". Never "reproduced
        without it" — that removes the constraint from the environment.
        """
        fields = {**requirement.fields, unknown: "something"}
        lossy = package_ops.Requirement(requirement.name, fields)
        with pytest.raises(package_ops.LossyReceiptError):
            lossy.to_pep508()

    @given(requirement=_requirements())
    def test_a_rendered_requirement_always_starts_with_its_name(
        self, requirement
    ) -> None:
        assert requirement.to_pep508().startswith(requirement.name)
