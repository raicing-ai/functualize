"""`self update`, `self install`, `self python`, `self uv` at the CLI boundary.

Tier 2 of `research.md` §2.3 — in-process, and **nothing here mutates the
developer's real installation**. Two things make that safe:

1. `package_ops._call` is the single point where this feature executes
   anything, so replacing it is enough; and
2. the confirmation prompt is a real seam — without `--yes` the command prints
   and stops, so the "prints the exact command" criteria need no subprocess at
   all.

Every test that pins a mode passes `FUNCTUALIZE_RUNTIME` explicitly, because
`_isolate_home` strips all `FUNCTUALIZE_*` variables.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from functualize._cli import manifest, package_ops


@pytest.fixture
def calls(monkeypatch) -> list[list[str]]:
    """Capture what would have run, and run nothing.

    Returns the list commands land in. Defaults to reporting success; tests
    that need a failure replace `_call` themselves.
    """
    seen: list[list[str]] = []

    def _call(argv) -> int:
        seen.append(list(argv))
        return 0

    monkeypatch.setattr(package_ops, "_call", _call)
    return seen


@pytest.fixture
def no_external_tools(monkeypatch) -> None:
    """Pin the manager paths, so a machine without uv still runs these tests."""
    monkeypatch.setattr(package_ops, "resolve_uv", lambda: "/opt/uv")
    monkeypatch.setattr(package_ops, "resolve_pipx", lambda: "/opt/pipx")
    # Standalone adds packages with the *bundled* interpreter's pip, not
    # uv: a binary is the install method for a machine with no Python
    # toolchain, and PyApp's distribution ships no uv.
    monkeypatch.setattr(package_ops, "owned_python", lambda: "/opt/python")


DEGRADED = ("tool_pip", "unknown")


class TestRefusal:
    """AC13 and AC14d — a mode functualize does not manage."""

    @pytest.mark.parametrize("mode", DEGRADED)
    def test_update_refuses_with_the_refusal_code(
        self, cli_run, tmp_path: Path, calls, mode: str
    ) -> None:
        result = cli_run(
            ["builtin", "self", "update", "--yes"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": mode},
        )
        assert result.exit_code == 3
        assert calls == []

    @pytest.mark.parametrize("mode", DEGRADED)
    def test_refusal_explains_rather_than_only_declining(
        self, cli_run, tmp_path: Path, calls, mode: str
    ) -> None:
        result = cli_run(
            ["builtin", "self", "update", "--yes"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": mode},
        )
        assert mode in result.stderr
        assert "doctor" in result.stderr

    @pytest.mark.parametrize("mode", DEGRADED)
    def test_refusal_writes_nothing_to_stdout(
        self, cli_run, tmp_path: Path, calls, mode: str
    ) -> None:
        """A script capturing this gets an empty capture, not prose."""
        result = cli_run(
            ["builtin", "self", "update", "--yes"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": mode},
        )
        assert result.stdout == ""

    @pytest.mark.parametrize(
        "argv",
        [
            ["builtin", "self", "install", "requests", "--yes"],
            ["builtin", "self", "python"],
            ["builtin", "self", "uv"],
            ["builtin", "self", "python", "--", "-c", "print(1)"],
        ],
    )
    def test_every_owned_environment_command_refuses(
        self, cli_run, tmp_path: Path, calls, argv: list[str]
    ) -> None:
        """AC14d — install, python and uv all need an environment to act on."""
        result = cli_run(argv, cwd=tmp_path, env={"FUNCTUALIZE_RUNTIME": "unknown"})
        assert result.exit_code == 3
        assert result.stdout == ""
        assert calls == []


class TestTheConfirmationSeam:
    """AC14 and AC14a — printed before anything happens, and nothing without
    a yes."""

    def test_update_prints_the_exact_command(
        self, cli_run, tmp_path: Path, calls, no_external_tools
    ) -> None:
        result = cli_run(
            ["builtin", "self", "update"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "tool_pipx"},
        )
        assert "/opt/pipx upgrade" in result.stdout

    def test_standalone_update_does_not_shell_out_to_a_manager(
        self, cli_run, tmp_path: Path, calls, no_external_tools
    ) -> None:
        """A standalone binary has no package manager to delegate to.

        It reaches `self_update.perform` instead, which refuses here because
        this checkout is not a baked distribution and carries no
        `standalone-release.json`. What matters is that *no command ran*: the
        old code path ran `<binary> pyapp update`, a command PyApp hides and
        then refuses.
        """
        result = cli_run(
            ["builtin", "self", "update", "--yes"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "standalone"},
        )
        assert calls == []
        assert result.exit_code == 3
        assert "no release source" in result.stdout

    def test_update_declined_runs_nothing(self, cli_run, tmp_path: Path, calls) -> None:
        """pytest's stdin cannot be read, so `click.confirm` aborts — which is
        the declined path, exercised for free."""
        result = cli_run(
            ["builtin", "self", "update"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "tool_pipx"},
        )
        assert calls == []
        assert result.exit_code != 0

    def test_install_prints_the_exact_command(
        self, cli_run, tmp_path: Path, calls, no_external_tools
    ) -> None:
        result = cli_run(
            ["builtin", "self", "install", "requests"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "standalone"},
        )
        assert "/opt/python -m pip install" in result.stdout
        assert "requests" in result.stdout

    def test_install_declined_runs_nothing(
        self, cli_run, tmp_path: Path, calls, no_external_tools
    ) -> None:
        cli_run(
            ["builtin", "self", "install", "requests"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "standalone"},
        )
        assert calls == []

    def test_yes_skips_the_prompt_but_not_the_printing(
        self, cli_run, tmp_path: Path, calls, no_external_tools
    ) -> None:
        """`--yes` is for automation, and a log of what ran is what automation
        needs most."""
        result = cli_run(
            ["builtin", "self", "install", "requests", "--yes"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "standalone"},
        )
        assert "requests" in result.stdout
        assert calls != []

    def test_a_missing_manager_is_a_usage_error_not_a_refusal(
        self, cli_run, tmp_path: Path, calls, monkeypatch
    ) -> None:
        """The installation is manageable; the manager just is not here. That
        is exit 2, which `contracts.md` §2 assigns to an absent external tool."""

        def _absent() -> str:
            raise package_ops.MissingToolError("uv is required")

        monkeypatch.setattr(package_ops, "resolve_uv", _absent)
        result = cli_run(
            ["builtin", "self", "install", "requests", "--yes"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "tool_pipx"},
        )
        assert result.exit_code == 2
        assert calls == []


@pytest.mark.surfaces("func")
class TestBookkeeping:
    """AC14a — recorded under a key distinct from plugins."""

    def _record(self, xdg_dirs) -> manifest.InstallRecord | None:
        registry = manifest.load(
            manifest.manifest_path(Path(xdg_dirs.functualize_config))
        )
        return registry.installations[0] if registry.installations else None

    def test_a_successful_install_is_recorded_under_packages(
        self, cli_run, tmp_path: Path, calls, no_external_tools, xdg_dirs
    ) -> None:
        cli_run(
            ["builtin", "self", "install", "requests", "--yes"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "standalone"},
        )
        record = self._record(xdg_dirs)
        assert record is not None
        assert "requests" in record.packages

    def test_it_stays_out_of_plugins(
        self, cli_run, tmp_path: Path, calls, no_external_tools, xdg_dirs
    ) -> None:
        """`plugin list` must never show a plain dependency.

        Both halves asserted: without the positive one the test passes when
        nothing is recorded at all, which is not the property.
        """
        cli_run(
            ["builtin", "self", "install", "requests", "--yes"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "standalone"},
        )
        record = self._record(xdg_dirs)
        assert record is not None
        assert "requests" in record.packages
        assert "requests" not in record.plugins

    def test_a_failed_install_is_not_recorded(
        self, cli_run, tmp_path: Path, no_external_tools, xdg_dirs, monkeypatch
    ) -> None:
        """A record of a package that is not installed is worse than no record:
        the next update faithfully reinstalls it.

        Paired with a successful install of a different package, so the
        assertion is "recording happened, and skipped this one" rather than
        "nothing was recorded" — which would hold with the bookkeeping deleted.
        """
        outcomes = {"good": 0, "bad": 1}
        monkeypatch.setattr(
            package_ops,
            "_call",
            lambda argv: next((c for p, c in outcomes.items() if p in argv), 0),
        )
        for package in ("good", "bad"):
            cli_run(
                ["builtin", "self", "install", package, "--yes"],
                cwd=tmp_path,
                env={"FUNCTUALIZE_RUNTIME": "standalone"},
            )
        record = self._record(xdg_dirs)
        assert record is not None
        assert "good" in record.packages
        assert "bad" not in record.packages

    def test_recording_the_same_package_twice_stores_it_once(
        self, cli_run, tmp_path: Path, calls, no_external_tools, xdg_dirs
    ) -> None:
        for _ in range(2):
            cli_run(
                ["builtin", "self", "install", "requests", "--yes"],
                cwd=tmp_path,
                env={"FUNCTUALIZE_RUNTIME": "standalone"},
            )
        record = self._record(xdg_dirs)
        assert record is not None
        assert list(record.packages).count("requests") == 1

    def test_the_two_lists_stay_disjoint(self, xdg_dirs) -> None:
        """A name arriving through the other command moves rather than
        duplicating: `self update` restores both lists in one pass, so a name in
        both would be installed twice, and `plugin list` would show a package."""
        config = Path(xdg_dirs.functualize_config)
        manifest.register(
            config,
            binary_path="/bin/func",
            runtime_mode="standalone",
            owning_distribution="functualize",
            python_version="3.13.0",
            functualize_version="0.1.2",
        )
        manifest.record_addition(
            config, binary_path="/bin/func", key="plugins", name="functualize-http"
        )
        manifest.record_addition(
            config, binary_path="/bin/func", key="packages", name="functualize-http"
        )
        record = manifest.load(manifest.manifest_path(config)).find("/bin/func")
        assert record is not None
        assert record.plugins == ()
        assert record.packages == ("functualize-http",)

    def test_an_unregistered_binary_records_nothing(self, xdg_dirs) -> None:
        """No installation, no record to attach an addition to."""
        assert (
            manifest.record_addition(
                Path(xdg_dirs.functualize_config),
                binary_path="/nowhere/func",
                key="packages",
                name="requests",
            )
            is False
        )


@pytest.mark.surfaces("func")
class TestReconciliation:
    def test_the_capture_is_persisted_before_the_update_runs(
        self, cli_run, tmp_path: Path, xdg_dirs, monkeypatch, no_external_tools
    ) -> None:
        """AC14h.

        Asserted from *inside* the update command: an update interrupted between
        rebuilding the environment and restoring it must still be able to
        restore, which is only true if the snapshot reached disk first. Checking
        afterwards would pass even if it were written at the very end.
        """
        pending_at_call_time: list[bool] = []
        config = Path(xdg_dirs.functualize_config)

        def _call(argv) -> int:
            pending_at_call_time.append(package_ops.pending_path(config).exists())
            return 0

        monkeypatch.setattr(package_ops, "_call", _call)
        cli_run(
            ["builtin", "self", "update", "--yes"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "tool_pipx"},
        )
        assert pending_at_call_time == [True]

    def test_the_snapshot_is_cleared_once_reconciliation_finishes(
        self, cli_run, tmp_path: Path, calls, xdg_dirs
    ) -> None:
        cli_run(
            ["builtin", "self", "update", "--yes"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "standalone"},
        )
        assert not package_ops.pending_path(Path(xdg_dirs.functualize_config)).exists()

    def test_a_failed_upgrade_keeps_the_snapshot(
        self, cli_run, tmp_path: Path, xdg_dirs, monkeypatch, no_external_tools
    ) -> None:
        """Re-running must still be able to restore."""
        monkeypatch.setattr(package_ops, "_call", lambda argv: 9)
        result = cli_run(
            ["builtin", "self", "update", "--yes"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "tool_pipx"},
        )
        assert result.exit_code == 9
        assert package_ops.pending_path(Path(xdg_dirs.functualize_config)).exists()

    def test_an_interrupted_update_resumes_from_its_snapshot(
        self, cli_run, tmp_path: Path, calls, no_external_tools, xdg_dirs
    ) -> None:
        """AC14h's payoff.

        A snapshot left on disk describes the pre-update world. The current
        environment is the half-updated one, so the snapshot wins — and the
        packages it names that are gone now get restored.
        """
        config = Path(xdg_dirs.functualize_config)
        package_ops.save_pending(config, {"functualize": "0.1.2", "pandas": "2.2.0"})

        result = cli_run(
            ["builtin", "self", "update", "--yes"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "tool_pipx"},
        )
        assert "Resuming" in result.stdout
        assert "pandas" in result.stdout
        assert any("pandas" in command for command in calls)

    def test_every_restored_item_is_listed(
        self, cli_run, tmp_path: Path, calls, no_external_tools, xdg_dirs
    ) -> None:
        """AC14i."""
        package_ops.save_pending(
            Path(xdg_dirs.functualize_config), {"pandas": "2.2.0", "polars": "1.0.0"}
        )
        result = cli_run(
            ["builtin", "self", "update", "--yes"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "tool_pipx"},
        )
        assert "restored  pandas" in result.stdout
        assert "restored  polars" in result.stdout

    def test_a_package_that_cannot_be_reinstalled_does_not_fail_the_update(
        self, cli_run, tmp_path: Path, no_external_tools, xdg_dirs, monkeypatch
    ) -> None:
        """AC14i — the upgrade succeeded; one unreachable package must not
        misdescribe the installation as broken."""
        package_ops.save_pending(Path(xdg_dirs.functualize_config), {"pandas": "2.2.0"})

        def _call(argv) -> int:
            return 1 if "pandas" in argv else 0

        monkeypatch.setattr(package_ops, "_call", _call)
        result = cli_run(
            ["builtin", "self", "update", "--yes"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "tool_pipx"},
        )
        assert result.exit_code == 0
        assert "FAILED" in result.stderr
        assert "pandas" in result.stderr

    def test_a_package_still_installed_after_the_upgrade_is_not_reinstalled(
        self, cli_run, tmp_path: Path, calls, no_external_tools, xdg_dirs
    ) -> None:
        """AC14g at the CLI boundary.

        `functualize` is in the snapshot at an old version and is still present
        now at a different one. Restoring it would pin the version the upgrade
        just moved away from.
        """
        package_ops.save_pending(
            Path(xdg_dirs.functualize_config), {"functualize": "0.0.1"}
        )
        cli_run(
            ["builtin", "self", "update", "--yes"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "standalone"},
        )
        install_calls = [c for c in calls if "pip" in c]
        assert install_calls == []

    def test_recorded_additions_are_restored_too(
        self, cli_run, tmp_path: Path, calls, no_external_tools, xdg_dirs
    ) -> None:
        """AC14b — the belt to the capture's braces.

        The recorded name is deliberately one that is *not* installed here:
        `functualize-state-sqlite` is a real first-party plugin present in this
        checkout, so recording it would be filtered out as already-present and
        the test would pass without restoring anything.
        """
        config = Path(xdg_dirs.functualize_config)
        binary = manifest.resolve_binary_path("func", __import__("sys").executable)
        manifest.register(
            config,
            binary_path=binary,
            runtime_mode="tool_pipx",
            owning_distribution="functualize",
            python_version="3.13.0",
            functualize_version="0.1.2",
        )
        manifest.record_addition(
            config, binary_path=binary, key="plugins", name="functualize-absent-plugin"
        )
        result = cli_run(
            ["builtin", "self", "update", "--yes"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "tool_pipx"},
        )
        assert "restored  functualize-absent-plugin" in result.stdout


class TestTheEscapeHatch:
    """AC14c and AC14e — `self python` / `self uv`, both forms."""

    def test_bare_python_prints_one_absolute_path_and_nothing_else(
        self, cli_run, tmp_path: Path
    ) -> None:
        result = cli_run(
            ["builtin", "self", "python"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "standalone"},
        )
        assert result.exit_code == 0
        lines = result.stdout.splitlines()
        assert len(lines) == 1
        assert Path(lines[0]).is_absolute()

    def test_bare_uv_prints_one_absolute_path_and_nothing_else(
        self, cli_run, tmp_path: Path, no_external_tools
    ) -> None:
        result = cli_run(
            ["builtin", "self", "uv"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "standalone"},
        )
        assert result.stdout.splitlines() == ["/opt/uv"]

    def test_the_printed_python_is_the_environment_not_the_base_interpreter(
        self, cli_run, tmp_path: Path
    ) -> None:
        """A venv's `bin/python` is a symlink to the base interpreter.
        Resolving it hands back a Python that sees none of the environment's
        packages — so the path printed here must be `sys.executable` as it
        stands, not where it points."""
        import sys

        result = cli_run(
            ["builtin", "self", "python"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "standalone"},
        )
        assert result.stdout.strip() == __import__("os").path.abspath(sys.executable)

    def test_arguments_are_passed_through_untouched(
        self, cli_run, tmp_path: Path, calls
    ) -> None:
        cli_run(
            ["builtin", "self", "python", "--", "-m", "pip", "--version"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "standalone"},
        )
        assert len(calls) == 1
        assert calls[0][1:] == ["-m", "pip", "--version"]

    def test_an_option_like_argument_is_not_eaten_by_click(
        self, cli_run, tmp_path: Path, calls
    ) -> None:
        """`--version` after `--` belongs to the child, not to `self python`."""
        cli_run(
            ["builtin", "self", "uv", "--", "--version"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "standalone"},
        )
        assert calls[0][1:] == ["--version"]

    def test_the_exit_code_is_proxied(
        self, cli_run, tmp_path: Path, monkeypatch
    ) -> None:
        """AC14c. A wrapper that swallows the child's status makes
        `self python -- -m pytest` useless in CI."""
        monkeypatch.setattr(package_ops, "_call", lambda argv: 42)
        result = cli_run(
            ["builtin", "self", "python", "--", "-c", "raise SystemExit(42)"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "standalone"},
        )
        assert result.exit_code == 42

    def test_a_real_child_actually_runs(self, cli_run, tmp_path: Path) -> None:
        """Unpatched, end to end — the one place the passthrough is proven to
        execute rather than merely to be planned."""
        result = cli_run(
            ["builtin", "self", "python", "--", "-c", "raise SystemExit(7)"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "standalone"},
        )
        assert result.exit_code == 7


class TestTerminalOwnership:
    """The mutating and passthrough subcommands hand over the terminal.

    Each runs a child inheriting fd 0/1/2. On the TUI's worker path only
    Python-level `sys.stdout` is redirected, so the child would draw straight
    onto the terminal underneath the interface — the `skills install` defect P2
    fixed.
    """

    @pytest.mark.parametrize("name", ["update", "install", "python", "uv"])
    def test_it_is_declared(self, name: str) -> None:
        from functualize._cli.builtins import BUILTIN_ROOT_COMMAND

        assert BUILTIN_ROOT_COMMAND.needs_terminal(["self", name])

    def test_doctor_does_not_own_the_terminal(self) -> None:
        """It only prints a report; taking the terminal for that would tear the
        inline shell down for nothing."""
        from functualize._cli.builtins import BUILTIN_ROOT_COMMAND

        assert not BUILTIN_ROOT_COMMAND.needs_terminal(["self", "doctor"])

    def test_the_names_do_not_leak_into_other_families(self) -> None:
        """P1's property, re-asserted where this task could break it: `self`
        now declares `install`, `python` and `update`, and `scaffold` has no
        business inheriting them."""
        from functualize._cli.builtins import BUILTIN_ROOT_COMMAND

        assert not BUILTIN_ROOT_COMMAND.needs_terminal(["scaffold", "update"])
        assert not BUILTIN_ROOT_COMMAND.needs_terminal(["workflow", "python"])


class TestTheCommandsAreDiscoverable:
    def test_the_help_lists_all_five(self, cli_run, tmp_path: Path) -> None:
        result = cli_run(["builtin", "self", "--help"], cwd=tmp_path)
        for name in ("doctor", "update", "install", "python", "uv"):
            assert name in result.stdout

    def test_the_registry_and_click_agree(self) -> None:
        """The shell's completion tree is built from the registry, not from
        click, so a subcommand present in one and absent from the other is
        invisible in exactly one surface."""
        from functualize._cli.builtins import BUILTIN_COMMANDS
        from functualize._cli.self_cmd import self_app

        entry = next(c for c in BUILTIN_COMMANDS if c.name == "self")
        assert {name for name, _ in entry.subcommands} == set(self_app.commands)


@pytest.mark.surfaces("func")
def test_the_registry_is_not_loaded_on_a_warm_path(cli_run, tmp_path: Path) -> None:
    """AC9, re-asserted because this task added lazy imports that could have
    been module-level ones. `builtins._mount` imports `self_cmd` while building
    the group, so a module-level `import manifest` there would put the registry
    on every invocation."""
    import subprocess
    import sys

    probe = (
        "import sys; sys.argv=['func','builtin','version'];"
        "from functualize._cli.main import _run_cli\n"
        "try:\n    _run_cli()\n"
        "except SystemExit:\n    pass\n"
        "import json; print(json.dumps("
        "'functualize._cli.package_ops' in sys.modules))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )
    assert json.loads(completed.stdout.splitlines()[-1]) is False
