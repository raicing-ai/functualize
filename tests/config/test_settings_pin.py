"""Executable snapshot of the settings vocabulary before its owners move.

The second class records known divergences. Each row names the task that will
replace its *current* result, so this file stays green during wave 0.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize._cli import config as cli_config
from functualize._cli.data import func_settings
from functualize._cli.main import cli_app
from functualize._cli.pep723 import _KNOWN_TOOL_KEYS, parse_script_metadata
from functualize._config.project_dirs import (
    LIST_KEYS,
    PROJECT_CONFIG_CANDIDATES,
)
from functualize._config.sources import EnvSource
from functualize._discovery.filter_factory import _DISCOVERY_FINGERPRINT_FIELDS

# name, type, description, default, choices, min, max, max_items, cli_flag, phase
EXPECTED_CATALOG = (
    (
        "tui.theme",
        "str",
        "Active theme ID (must match registered theme_id)",
        "transparent",
        (),
        None,
        None,
        None,
        None,
        None,
    ),
    (
        "tui.display_auto_switch",
        "enum",
        "Display panel auto-switch behavior",
        "indicator",
        ("auto", "indicator", "off"),
        None,
        None,
        None,
        None,
        None,
    ),
    (
        "tui.default_surface",
        "enum",
        "Where a job renders when run from the TUI",
        "panel",
        ("panel", "stdout"),
        None,
        None,
        None,
        None,
        None,
    ),
    (
        "tui.show_session_stamp",
        "bool",
        "Show session stamp on TUI exit",
        "true",
        (),
        None,
        None,
        None,
        None,
        None,
    ),
    (
        "tui.history_retention",
        "int",
        "Number of history entries to retain",
        "100",
        (),
        1,
        1000,
        None,
        None,
        None,
    ),
    (
        "tui.signature_enabled",
        "bool",
        "Show signature slot",
        "true",
        (),
        None,
        None,
        None,
        None,
        None,
    ),
    (
        "tui.default_override_target",
        "enum",
        "Default persistence target for overrides",
        "file",
        ("file", "env"),
        None,
        None,
        None,
        None,
        None,
    ),
    (
        "cli.output",
        "enum",
        "CLI output format",
        "rich",
        ("rich", "plain", "json"),
        None,
        None,
        None,
        None,
        None,
    ),
    (
        "cli.show_timing",
        "bool",
        "Show timing after runs",
        "false",
        (),
        None,
        None,
        None,
        None,
        None,
    ),
    (
        "discovery.require_file_prefix",
        "str",
        "Only scan files named <prefix>*",
        None,
        (),
        None,
        None,
        None,
        None,
        None,
    ),
    (
        "discovery.require_file_postfix",
        "str",
        "Only scan files named *<postfix>",
        None,
        (),
        None,
        None,
        None,
        None,
        None,
    ),
    (
        "discovery.require_file_import",
        "str",
        "Only scan files importing this module",
        None,
        (),
        None,
        None,
        None,
        None,
        None,
    ),
    (
        "discovery.require_file_marker",
        "str",
        "Only scan files defining this marker",
        None,
        (),
        None,
        None,
        None,
        None,
        None,
    ),
    (
        "discovery.require_job_decorators",
        "list",
        "Only register decorated functions",
        None,
        (),
        None,
        None,
        None,
        None,
        None,
    ),
    (
        "discovery.require_job_prefix",
        "str",
        "Only register jobs named <prefix>*",
        None,
        (),
        None,
        None,
        None,
        None,
        None,
    ),
    (
        "discovery.require_job_postfix",
        "str",
        "Only register jobs named *<postfix>",
        None,
        (),
        None,
        None,
        None,
        None,
        None,
    ),
    (
        "discovery.extra_directories",
        "list",
        "Additional job directories",
        None,
        (),
        None,
        None,
        None,
        None,
        None,
    ),
    (
        "discovery.exclude_patterns",
        "list",
        "Glob patterns to skip",
        None,
        (),
        None,
        None,
        None,
        None,
        None,
    ),
    (
        "discovery.scan_depth",
        "int",
        "Directory scan depth (0 = unlimited)",
        "0",
        (),
        0,
        32,
        None,
        None,
        None,
    ),
    (
        "plugins.strict",
        "bool",
        "Error (not warn) on job metadata whose plugin is not loaded",
        "false",
        (),
        None,
        None,
        None,
        None,
        None,
    ),
    (
        "shell.program",
        "str",
        "Shell binary for raw shell=True commands (default: platform shell)",
        None,
        (),
        None,
        None,
        None,
        None,
        None,
    ),
    (
        "shell.sudo_password",
        "str",
        "Password for sh.sudo() (secret — masked in all output)",
        None,
        (),
        None,
        None,
        None,
        None,
        None,
    ),
    (
        "cli.inline_tui",
        "bool",
        "Launch the interactive shell on a bare invocation at a TTY",
        "true",
        (),
        None,
        None,
        None,
        None,
        None,
    ),
    (
        "vault.keyring_timeout",
        "str",
        "How long a run waits on the OS keyring for the vault key (e.g. 30s, 2m)",
        "30s",
        (),
        None,
        None,
        None,
        None,
        None,
    ),
    (
        "dotenv",
        "bool",
        "Load .env at startup",
        "false",
        (),
        None,
        None,
        None,
        None,
        None,
    ),
    (
        "dotenv_path",
        "str",
        "Explicit .env file path",
        None,
        (),
        None,
        None,
        None,
        None,
        None,
    ),
    (
        "import_libs",
        "list",
        "Paths importable by job modules",
        None,
        (),
        None,
        None,
        None,
        None,
        None,
    ),
)

# option, callback name, default, multiple, flag, type, help
EXPECTED_FLAGS = (
    (
        "--log-level",
        "log_level",
        "INFO",
        False,
        False,
        "StringParamType",
        "Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL.",
    ),
    (
        "--dotenv-file",
        "dotenv_file",
        None,
        False,
        False,
        "Path",
        "Path to the .env file to load environment variables from.",
    ),
    (
        "--no-dotenv",
        "no_dotenv",
        False,
        False,
        True,
        "BoolParamType",
        "Suppress .env file loading entirely.",
    ),
    (
        "--config-directory",
        "config_directory",
        None,
        False,
        False,
        "Path",
        "Path to the config directory. When not specified, searches upward from CWD for config files, then falls back to the OS-specific user config directory.",
    ),
    (
        "--discovery-depth",
        "discovery_depth",
        None,
        False,
        False,
        "IntParamType",
        "Max directory levels below CWD to scan for jobs (0-5).",
    ),
    (
        "--require-file-import",
        "require_file_import",
        None,
        False,
        False,
        "StringParamType",
        "Only discover files that import this module.",
    ),
    (
        "--require-file-prefix",
        "require_file_prefix",
        None,
        False,
        False,
        "StringParamType",
        "Only discover files whose name starts with this prefix.",
    ),
    (
        "--require-file-postfix",
        "require_file_postfix",
        None,
        False,
        False,
        "StringParamType",
        "Only discover files whose name ends with this postfix.",
    ),
    (
        "--require-file-marker",
        "require_file_marker",
        None,
        False,
        False,
        "StringParamType",
        "Only discover files declaring this module-level marker variable.",
    ),
    (
        "--require-job-prefix",
        "require_job_prefix",
        None,
        False,
        False,
        "StringParamType",
        "Only discover jobs whose function name starts with this prefix.",
    ),
    (
        "--require-job-postfix",
        "require_job_postfix",
        None,
        False,
        False,
        "StringParamType",
        "Only discover jobs whose function name ends with this postfix.",
    ),
    (
        "--require-job-decorators",
        "require_job_decorators",
        "UNSET",
        True,
        False,
        "StringParamType",
        "Only discover jobs decorated with these decorator names.",
    ),
    (
        "--exclude",
        "exclude",
        "UNSET",
        True,
        False,
        "StringParamType",
        "Glob patterns to exclude from discovery (max 20).",
    ),
    (
        "--perf-report",
        "perf_report",
        None,
        False,
        False,
        "StringParamType",
        "Print performance report after command. Format: text or json.",
    ),
    (
        "--perf-filter",
        "perf_filter",
        None,
        False,
        False,
        "StringParamType",
        "Filter pattern for --perf-report.",
    ),
    (
        "--import-libs",
        "import_libs",
        "UNSET",
        True,
        False,
        "StringParamType",
        "Directories to add to sys.path before importing jobs.",
    ),
)


def _catalog_row(setting: func_settings.FuncSetting) -> tuple[object, ...]:
    schema = setting.schema
    return (
        setting.name,
        schema.type,
        schema.description,
        setting.default,
        tuple(schema.choices or ()),
        schema.min_value,
        schema.max_value,
        schema.max_items,
        setting.cli_flag,
        setting.phase,
    )


@pytest.fixture
def isolated_catalog() -> None:
    original = func_settings.registered_settings()
    func_settings.clear_registered_settings()
    yield
    func_settings.clear_registered_settings()
    func_settings.register_settings(*original)


@pytest.fixture
def config_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    xdg = tmp_path / "xdg"
    xdg.mkdir()
    monkeypatch.setattr(cli_config, "resolve_user_config_dir", lambda: xdg)
    project = tmp_path / "project"
    project.mkdir()
    return xdg, project


class TestCurrentVocabulary:
    def test_catalog_order_and_schema(self, isolated_catalog: None) -> None:
        base = tuple(func_settings.FUNC_SETTINGS)
        tui = func_settings.tui_settings()
        assert tuple(_catalog_row(s) for s in (*tui, *base)) == EXPECTED_CATALOG
        assert tuple(func_settings.SETTINGS_ORDER) == tuple(
            row[0] for row in EXPECTED_CATALOG[7:]
        )
        assert dict(func_settings.DEFAULT_VALUES) == {
            row[0]: row[3] for row in EXPECTED_CATALOG[7:] if row[3] is not None
        }

    def test_environment_names(self, isolated_catalog: None) -> None:
        assert tuple(
            func_settings.env_var_for(s)
            for s in (*func_settings.tui_settings(), *func_settings.FUNC_SETTINGS)
        ) == tuple(
            "FUNCTUALIZE_" + str(row[0]).upper().replace(".", "_")
            for row in EXPECTED_CATALOG
        )

    def test_recognized_file_keys(self) -> None:
        assert {
            "discovery",
            "cli",
            "aliases",
            "tui",
            "vault",
        } == cli_config._RECOGNIZED_SECTIONS
        assert {
            "import_libs",
            "jobs_directories",
            "extra_directories",
            "dotenv",
            "dotenv_path",
        } == cli_config._RECOGNIZED_TOP_LEVEL_KEYS
        assert {
            "discovery": frozenset(
                {
                    "require_file_prefix",
                    "require_file_postfix",
                    "require_file_import",
                    "require_file_marker",
                    "require_job_decorators",
                    "require_job_prefix",
                    "require_job_postfix",
                    "extra_directories",
                    "exclude_patterns",
                    "scan_depth",
                }
            ),
            "cli": frozenset({"output", "show_timing", "inline_tui"}),
            "tui": frozenset(
                {
                    "default_surface",
                    "show_session_stamp",
                    "history_retention",
                    "signature_enabled",
                    "display_auto_switch",
                    "default_override_target",
                    "theme",
                }
            ),
            "vault": frozenset({"keyring_timeout"}),
        } == cli_config._RECOGNIZED_KEYS

    def test_directory_candidates_and_fingerprint(self) -> None:
        assert LIST_KEYS == (
            "jobs_directories",
            "import_libs",
            "plugins_directories",
            "extra_directories",
            "exclude_patterns",
        )
        assert tuple(
            item if isinstance(item, str) else item[0]
            for item in PROJECT_CONFIG_CANDIDATES
        ) == ("pyproject.toml", ".functualize.toml", ".functualize/.functualize.toml")
        assert _DISCOVERY_FINGERPRINT_FIELDS == (
            ("exclude_patterns", ()),
            ("extra_directories", ()),
            ("require_file_prefix", None),
            ("require_file_postfix", None),
            ("require_file_import", None),
            ("require_file_marker", None),
            ("require_job_decorators", None),
            ("require_job_prefix", None),
            ("require_job_postfix", None),
            ("pre_filter", None),
        )

    def test_sixteen_root_options(self) -> None:
        assert len(cli_app.params) == 16
        actual = tuple(
            (
                p.opts[0],
                p.name,
                "UNSET" if repr(p.default) == "Sentinel.UNSET" else p.default,
                p.multiple,
                p.is_flag,
                type(p.type).__name__,
                p.help,
            )
            for p in cli_app.params
        )
        assert actual == EXPECTED_FLAGS

    def test_resolved_matrix(
        self, config_tree: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        xdg, project = config_tree
        (xdg / "config.toml").write_text('[cli]\noutput = "plain"\n')
        # Global-only.
        assert cli_config.resolve_cli_config(cwd=project).output == "plain"
        # Single project directory.
        (project / ".functualize.toml").write_text('[cli]\noutput = "json"\n')
        assert cli_config.resolve_cli_config(cwd=project).output == "json"
        # Nested project wins, then a root marker prevents the parent value.
        nested = project / "nested"
        nested.mkdir()
        (nested / ".functualize.toml").write_text("[cli]\nshow_timing = true\n")
        assert (
            cli_config.resolve_cli_config(cwd=nested).output,
            cli_config.resolve_cli_config(cwd=nested).show_timing,
        ) == ("json", True)
        (nested / ".functualize.toml").write_text(
            "root = true\n[cli]\nshow_timing = true\n"
        )
        assert (
            cli_config.resolve_cli_config(cwd=nested).output,
            cli_config.resolve_cli_config(cwd=nested).show_timing,
        ) == ("plain", True)
        # Environment and typed flags each take the next rung.
        monkeypatch.setenv("FUNCTUALIZE_CLI_OUTPUT", "json")
        assert cli_config.resolve_cli_config(cwd=nested).output == "json"
        assert (
            cli_config.resolve_cli_config(
                cwd=nested, cli_flags={"output": "rich"}
            ).output
            == "rich"
        )


class TestCurrentDivergences:
    def test_f3a_output_split_flips_in_1_2(
        self, config_tree: tuple[Path, Path]
    ) -> None:
        xdg, project = config_tree
        (xdg / "config.toml").write_text('[cli]\noutput = "json"\n')
        (project / ".functualize.toml").write_text('[cli]\noutput = "rich"\n')
        nested = project / "nested"
        nested.mkdir()
        (nested / ".functualize.toml").write_text("root = true\n")
        assert cli_config.resolve_cli_config(cwd=nested).output == "json"
        assert (
            func_settings.FuncSettingsStore.discover(nested, env={})
            .effective_values()
            .get("cli.output")
            == "rich"
        )

    def test_f3b_shell_file_split_flips_in_3_1(
        self,
        config_tree: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _, project = config_tree
        (project / ".functualize.toml").write_text(
            '[shell]\nprogram = "/bin/from-dotfunctualize"\n'
        )
        store_value = (
            func_settings.FuncSettingsStore.discover(project, env={})
            .effective_values()
            .get("shell.program")
        )
        from functualize._app.boot import build_resolution_chain

        class _Registry:
            def list_format_providers(self) -> list[object]:
                return []

            def list_remote_providers(self) -> list[object]:
                return []

        chain = build_resolution_chain(str(project), "functualize", _Registry())
        from functualize._engine.executor import JobExecutionEngine

        monkeypatch.setattr(
            JobExecutionEngine, "_live_resolution_chain", lambda self: chain
        )
        engine = object.__new__(JobExecutionEngine)
        assert engine._resolve_shell_program() is None
        assert store_value == "/bin/from-dotfunctualize"

    def test_shell_and_plugin_env_names_flip_in_1_2(self) -> None:
        source = EnvSource(
            {
                "SHELL_PROGRAM": "/bin/legacy",
                "PLUGINS_STRICT": "true",
                "FUNCTUALIZE_SHELL_PROGRAM": "/bin/catalog",
                "FUNCTUALIZE_PLUGINS_STRICT": "false",
            }
        )
        assert source.get("program", "shell") == "/bin/legacy"
        assert source.get("strict", "plugins") == "true"

    def test_extra_directories_env_name_flips_in_1_2(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FUNCTUALIZE_EXTRA_DIRECTORIES", "legacy")
        monkeypatch.setenv("FUNCTUALIZE_DISCOVERY_EXTRA_DIRECTORIES", "canonical")
        assert cli_config.resolve_env_overrides()["extra_directories"] == "legacy"

    def test_pep723_skill_flips_in_6_4(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        script = tmp_path / "script.py"
        script.write_text(
            '# /// script\n# [tool.functualize]\n# job = "run"\n'
            '# skill = "demo"\n# ///\ndef run(): pass\n'
        )
        metadata = parse_script_metadata(script)
        assert {"job", "skill"} == _KNOWN_TOOL_KEYS
        assert metadata is not None and (metadata.job, metadata.skill) == (
            "run",
            "demo",
        )
        assert capsys.readouterr().err == ""
