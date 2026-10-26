"""The declared settings vocabulary for the built-in functualize application.

The old CLI catalog and readers still own runtime resolution during wave 0.
The settings store will consume this declaration after the resolver and public
seam are in place.
"""

from __future__ import annotations

from functualize._types.enums import SURFACE_PREFERENCES, RenderSurface
from functualize._types.settings import AppSettingsSchema, Setting

__all__ = [
    "DISCOVERY_FINGERPRINT_FIELDS",
    "FUNCTUALIZE_SETTINGS",
    "LIST_KEYS",
    "PROJECT_CONFIG_CANDIDATES",
    "ROOT_KEY",
    "ROOT_FLAGS",
    "SCRIPT_METADATA",
]


THEME = Setting(
    "tui.theme",
    "str",
    "Active theme ID (must match registered theme_id)",
    default="transparent",
    surface="tui",
)
DISPLAY_AUTO_SWITCH = Setting(
    "tui.display_auto_switch",
    "enum",
    "Display panel auto-switch behavior",
    default="indicator",
    choices=("auto", "indicator", "off"),
    surface="tui",
)
DEFAULT_SURFACE = Setting(
    "tui.default_surface",
    "enum",
    "Where a job renders when run from the TUI",
    default=RenderSurface.PANEL.value,
    choices=SURFACE_PREFERENCES,
    surface="tui",
)
SHOW_SESSION_STAMP = Setting(
    "tui.show_session_stamp",
    "bool",
    "Show session stamp on TUI exit",
    default="true",
    surface="tui",
)
HISTORY_RETENTION = Setting(
    "tui.history_retention",
    "int",
    "Number of history entries to retain",
    default="100",
    min_value=1,
    max_value=1000,
    surface="tui",
)
SIGNATURE_ENABLED = Setting(
    "tui.signature_enabled",
    "bool",
    "Show signature slot",
    default="true",
    surface="tui",
)
DEFAULT_OVERRIDE_TARGET = Setting(
    "tui.default_override_target",
    "enum",
    "Default persistence target for overrides",
    default="file",
    choices=("file", "env"),
    surface="tui",
)
OUTPUT = Setting(
    "cli.output",
    "enum",
    "CLI output format",
    default="rich",
    choices=("rich", "plain", "json"),
)
SHOW_TIMING = Setting(
    "cli.show_timing",
    "bool",
    "Show timing after runs",
    default="false",
)
REQUIRE_FILE_PREFIX = Setting(
    "discovery.require_file_prefix",
    "str",
    "Only scan files named <prefix>*",
    cli_flag="--require-file-prefix",
    phase="early",
)
REQUIRE_FILE_POSTFIX = Setting(
    "discovery.require_file_postfix",
    "str",
    "Only scan files named *<postfix>",
    cli_flag="--require-file-postfix",
    phase="early",
)
REQUIRE_FILE_IMPORT = Setting(
    "discovery.require_file_import",
    "str",
    "Only scan files importing this module",
    cli_flag="--require-file-import",
    phase="early",
)
REQUIRE_FILE_MARKER = Setting(
    "discovery.require_file_marker",
    "str",
    "Only scan files defining this marker",
    cli_flag="--require-file-marker",
    phase="early",
)
REQUIRE_JOB_DECORATORS = Setting(
    "discovery.require_job_decorators",
    "list",
    "Only register decorated functions",
    cli_flag="--require-job-decorators",
    phase="early",
)
REQUIRE_JOB_PREFIX = Setting(
    "discovery.require_job_prefix",
    "str",
    "Only register jobs named <prefix>*",
    cli_flag="--require-job-prefix",
    phase="early",
)
REQUIRE_JOB_POSTFIX = Setting(
    "discovery.require_job_postfix",
    "str",
    "Only register jobs named *<postfix>",
    cli_flag="--require-job-postfix",
    phase="early",
)
EXTRA_DIRECTORIES = Setting(
    "discovery.extra_directories",
    "list",
    "Additional job directories",
    places=("", "discovery"),
    env="FUNCTUALIZE_DISCOVERY_EXTRA_DIRECTORIES",
)
EXCLUDE_PATTERNS = Setting(
    "discovery.exclude_patterns",
    "list",
    "Glob patterns to skip",
    places=("", "discovery"),
    cli_flag="--exclude",
    phase="early",
)
SCAN_DEPTH = Setting(
    "discovery.scan_depth",
    "int",
    "Directory scan depth (0 = unlimited)",
    default="0",
    min_value=0,
    max_value=32,
    cli_flag="--discovery-depth",
    phase="early",
)
PLUGINS_STRICT = Setting(
    "plugins.strict",
    "bool",
    "Error (not warn) on job metadata whose plugin is not loaded",
    default="false",
)
SHELL_PROGRAM = Setting(
    "shell.program",
    "str",
    "Shell binary for raw shell=True commands (default: platform shell)",
)
SHELL_SUDO_PASSWORD = Setting(
    "shell.sudo_password",
    "str",
    "Password for sh.sudo() (secret — masked in all output)",
)
INLINE_TUI = Setting(
    "cli.inline_tui",
    "bool",
    "Launch the interactive shell on a bare invocation at a TTY",
    default="true",
)
KEYRING_TIMEOUT = Setting(
    "vault.keyring_timeout",
    "str",
    "How long a run waits on the OS keyring for the vault key (e.g. 30s, 2m)",
    default="30s",
)
DOTENV = Setting(
    "dotenv",
    "bool",
    "Load .env at startup",
    default="false",
)
DOTENV_PATH = Setting(
    "dotenv_path",
    "str",
    "Explicit .env file path",
    cli_flag="--dotenv-file",
    phase="early",
)
IMPORT_LIBS = Setting(
    "import_libs",
    "list",
    "Paths importable by job modules",
    cli_flag="--import-libs",
    phase="early",
)

# These two file keys participate in directory resolution, but are absent
# from the legacy settings panel.
JOBS_DIRECTORIES = Setting(
    "jobs_directories",
    "list",
    "Job directories",
    listed=False,
)
PLUGINS_DIRECTORIES = Setting(
    "plugins_directories",
    "list",
    "Plugin directories",
    listed=False,
)

# TRANSITIONAL(config-unknown-keys/4.3): the legacy catalog still owns runtime
# values; the settings store will consume this declaration in task 4.3.
FUNCTUALIZE_SETTINGS = AppSettingsSchema(
    settings=(
        THEME,
        DISPLAY_AUTO_SWITCH,
        DEFAULT_SURFACE,
        SHOW_SESSION_STAMP,
        HISTORY_RETENTION,
        SIGNATURE_ENABLED,
        DEFAULT_OVERRIDE_TARGET,
        OUTPUT,
        SHOW_TIMING,
        REQUIRE_FILE_PREFIX,
        REQUIRE_FILE_POSTFIX,
        REQUIRE_FILE_IMPORT,
        REQUIRE_FILE_MARKER,
        REQUIRE_JOB_DECORATORS,
        REQUIRE_JOB_PREFIX,
        REQUIRE_JOB_POSTFIX,
        EXTRA_DIRECTORIES,
        EXCLUDE_PATTERNS,
        SCAN_DEPTH,
        PLUGINS_STRICT,
        SHELL_PROGRAM,
        SHELL_SUDO_PASSWORD,
        INLINE_TUI,
        KEYRING_TIMEOUT,
        DOTENV,
        DOTENV_PATH,
        IMPORT_LIBS,
        JOBS_DIRECTORIES,
        PLUGINS_DIRECTORIES,
    ),
    freeform_sections=frozenset({"aliases"}),
)

LIST_KEYS = (
    JOBS_DIRECTORIES.key,
    IMPORT_LIBS.key,
    PLUGINS_DIRECTORIES.key,
    EXTRA_DIRECTORIES.key,
    EXCLUDE_PATTERNS.key,
)
PROJECT_CONFIG_CANDIDATES = FUNCTUALIZE_SETTINGS.sources.project_file_names
ROOT_KEY = "root"
DISCOVERY_FINGERPRINT_FIELDS = (
    (EXCLUDE_PATTERNS.key, ()),
    (EXTRA_DIRECTORIES.key, ()),
    (REQUIRE_FILE_PREFIX.key, None),
    (REQUIRE_FILE_POSTFIX.key, None),
    (REQUIRE_FILE_IMPORT.key, None),
    (REQUIRE_FILE_MARKER.key, None),
    (REQUIRE_JOB_DECORATORS.key, None),
    (REQUIRE_JOB_PREFIX.key, None),
    (REQUIRE_JOB_POSTFIX.key, None),
    ("pre_filter", None),
)

# The CLI-specific controls with no file setting are kept alongside the
# setting-backed options. Click still owns parsing until task 5.1.
# TRANSITIONAL(config-unknown-keys/5.1): Click decorators still own parsing.
ROOT_FLAGS = (
    "--log-level",
    DOTENV_PATH.cli_flag,
    "--no-dotenv",
    "--config-directory",
    SCAN_DEPTH.cli_flag,
    REQUIRE_FILE_IMPORT.cli_flag,
    REQUIRE_FILE_PREFIX.cli_flag,
    REQUIRE_FILE_POSTFIX.cli_flag,
    REQUIRE_FILE_MARKER.cli_flag,
    REQUIRE_JOB_PREFIX.cli_flag,
    REQUIRE_JOB_POSTFIX.cli_flag,
    REQUIRE_JOB_DECORATORS.cli_flag,
    EXCLUDE_PATTERNS.cli_flag,
    "--perf-report",
    "--perf-filter",
    IMPORT_LIBS.cli_flag,
)

# PEP 723 is intentionally narrower than today's parser: task 6.4 removes
# the accepted-but-unused 'skill' field from its runtime reader.
# TRANSITIONAL(config-unknown-keys/6.4): the old parser still accepts skill.
SCRIPT_METADATA = frozenset({"job"})
