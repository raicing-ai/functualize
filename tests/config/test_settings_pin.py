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
from functualize._cli.pep723 import parse_script_metadata
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
# The root surface, in order: the five flags with no declaration entry,
# then the eleven generated from `Setting.cli_flag`.
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
        "--require-file-prefix",
        "require_file_prefix",
        None,
        False,
        False,
        "StringParamType",
        "Only scan files named <prefix>*",
    ),
    (
        "--require-file-postfix",
        "require_file_postfix",
        None,
        False,
        False,
        "StringParamType",
        "Only scan files named *<postfix>",
    ),
    (
        "--require-file-import",
        "require_file_import",
        None,
        False,
        False,
        "StringParamType",
        "Only scan files importing this module",
    ),
    (
        "--require-file-marker",
        "require_file_marker",
        None,
        False,
        False,
        "StringParamType",
        "Only scan files defining this marker",
    ),
    (
        "--require-job-decorators",
        "require_job_decorators",
        None,
        True,
        False,
        "StringParamType",
        "Only register decorated functions",
    ),
    (
        "--require-job-prefix",
        "require_job_prefix",
        None,
        False,
        False,
        "StringParamType",
        "Only register jobs named <prefix>*",
    ),
    (
        "--require-job-postfix",
        "require_job_postfix",
        None,
        False,
        False,
        "StringParamType",
        "Only register jobs named *<postfix>",
    ),
    (
        "--exclude",
        "exclude",
        None,
        True,
        False,
        "StringParamType",
        "Glob patterns to skip",
    ),
    (
        "--discovery-depth",
        "discovery_depth",
        None,
        False,
        False,
        "IntParamType",
        "Directory scan depth (0 = unlimited)",
    ),
    (
        "--dotenv-file",
        "dotenv_file",
        None,
        False,
        False,
        "StringParamType",
        "Explicit .env file path",
    ),
    (
        "--import-libs",
        "import_libs",
        None,
        True,
        False,
        "StringParamType",
        "Paths importable by job modules",
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

    def test_legacy_recognized_tables_are_gone(self) -> None:
        for name in (
            "_RECOGNIZED_SECTIONS",
            "_RECOGNIZED_TOP_LEVEL_KEYS",
            "_RECOGNIZED_KEYS",
        ):
            assert not hasattr(cli_config, name)

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

    def test_f3b_shell_file_converges_in_3_1(
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
        from functualize.app import (
            ConfigSources,
            FunctualizeApp,
            JobSources,
            PluginSources,
        )

        monkeypatch.chdir(project)
        app = FunctualizeApp(
            "functualize",
            job_sources=JobSources(functions=[]),
            config_sources=ConfigSources(),
            plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
        )
        assert app._execution_engine._resolve_shell_program() == (
            "/bin/from-dotfunctualize"
        )
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
        from functualize._config.settings_resolution import resolve_settings
        from functualize._types.functualize_settings import FUNCTUALIZE_SETTINGS

        resolved = resolve_settings(FUNCTUALIZE_SETTINGS, Path.cwd())
        assert resolved.get("discovery.extra_directories") == ("canonical",)

    def test_pep723_skill_is_unknown_after_6_4(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        script = tmp_path / "script.py"
        script.write_text(
            '# /// script\n# [tool.functualize]\n# job = "run"\n'
            '# skill = "demo"\n# ///\ndef run(): pass\n'
        )
        from functualize._types.functualize_settings import SCRIPT_METADATA

        metadata = parse_script_metadata(script)
        assert frozenset({"job"}) == SCRIPT_METADATA
        assert metadata is not None and metadata.job == "run"
        err = capsys.readouterr().err
        assert "unknown key(s)" in err and "skill" in err
