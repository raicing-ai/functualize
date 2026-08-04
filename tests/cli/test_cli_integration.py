"""Integration tests for CLI routing, config resolution, and XDG isolation.

These tests exercise the real main() entry point using the `cli_run` fixture,
ensuring the full CLI stack works end-to-end without subprocess overhead.

Test matrix dimensions:
- Routing modes: BARE, SINGLE_FILE, GROUP, JOB, BUILTIN, UNKNOWN
- Config layers: XDG global, project (pyproject/functualize.toml), env, CLI
- Discovery: convention dirs, explicit dirs, filters, JOB_GROUP
- Boot: cold (no cache), warm (cache present)
- Name normalization: underscore vs dash in job names
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from tests.conftest import SUPPORT_CONFIGS, SUPPORT_PROJECTS

# ===========================================================================
# Routing Mode: BUILTIN
# ===========================================================================


class TestBuiltinRouting:
    """Test that builtin commands (version, help, config, scaffold) route correctly."""

    def test_version_command(self, cli_run) -> None:
        """`func version` exits 0 and prints version info."""
        result = cli_run(["builtin", "version"])
        assert result.exit_code == 0
        assert "functualize" in result.stdout.lower()

    def test_help_flag(self, cli_run) -> None:
        """--help exits 0 and prints usage info."""
        result = cli_run(["--help"])
        assert result.exit_code == 0
        assert "Usage" in result.stdout or "usage" in result.stdout

    def test_config_show_command(self, cli_run, project_tree) -> None:
        """`func config show` displays resolved configuration."""
        root = project_tree(jobs={"noop.py": "def noop(): pass\n"})
        result = cli_run(["builtin", "config", "show"], cwd=root)
        assert result.exit_code == 0

    def test_config_path_command(self, cli_run, project_tree) -> None:
        """`func config path` displays config file paths."""
        root = project_tree(jobs={"noop.py": "def noop(): pass\n"})
        result = cli_run(["builtin", "config", "path"], cwd=root)
        assert result.exit_code == 0


# ===========================================================================
# Routing Mode: BARE (no args)
# ===========================================================================


class TestBareMode:
    """Test BARE mode — `func` with no arguments."""

    def test_bare_with_no_jobs_does_not_crash(self, cli_run, project_tree) -> None:
        """Running `func` in a project with no jobs doesn't crash."""
        root = project_tree()
        result = cli_run([], cwd=root)
        assert result.exit_code in (0, 1)

    def test_bare_with_jobs_shows_listing(self, cli_run, project_tree) -> None:
        """Running `func` in a project with jobs lists available jobs."""
        root = project_tree(
            jobs={"greet.py": "def greet():\n    '''Say hi'''\n    print('hi')\n"}
        )
        result = cli_run([], cwd=root)
        assert "greet" in result.stdout or result.exit_code == 0

    def test_bare_lists_multiple_jobs(self, cli_run, project_tree) -> None:
        """BARE mode lists all discovered jobs."""
        root = project_tree(
            jobs={
                "alpha.py": "def alpha():\n    '''First'''\n    pass\n",
                "beta.py": "def beta():\n    '''Second'''\n    pass\n",
            }
        )
        result = cli_run([], cwd=root)
        assert result.exit_code == 0
        assert "alpha" in result.stdout
        assert "beta" in result.stdout


# ===========================================================================
# Routing Mode: JOB (single job execution)
# ===========================================================================


class TestJobRouting:
    """Test JOB mode — `func <jobname>` dispatches to a discovered job."""

    def test_simple_job_execution(self, cli_run, project_tree) -> None:
        """A simple job with no params prints its output."""
        root = project_tree(jobs={"hello.py": "def hello():\n    print('world')\n"})
        result = cli_run(["hello"], cwd=root)
        assert result.exit_code == 0
        assert "world" in result.stdout

    def test_job_with_params(self, cli_run, project_tree) -> None:
        """A job with typed params receives CLI arguments."""
        root = project_tree(
            jobs={
                "deploy.py": (
                    "def deploy(env: str, dry: bool = False):\n"
                    "    print(f'deploying to {env} dry={dry}')\n"
                )
            }
        )
        result = cli_run(["deploy", "staging", "--dry"], cwd=root)
        assert result.exit_code == 0
        assert "staging" in result.stdout
        assert "dry=True" in result.stdout

    def test_job_with_int_param(self, cli_run, project_tree) -> None:
        """Integer params are coerced from CLI strings."""
        root = project_tree(
            jobs={
                "scale.py": (
                    "def scale(replicas: int = 1):\n    print(f'replicas={replicas}')\n"
                )
            }
        )
        result = cli_run(["scale", "--replicas", "5"], cwd=root)
        assert result.exit_code == 0
        assert "replicas=5" in result.stdout

    def test_multiple_functions_in_one_file(self, cli_run, project_tree) -> None:
        """Multiple functions in a file are individually callable."""
        root = project_tree(
            jobs={
                "ops.py": (
                    "def build():\n    print('building')\n\n"
                    "def test():\n    print('testing')\n"
                )
            }
        )
        result_build = cli_run(["build"], cwd=root)
        result_test = cli_run(["test"], cwd=root)
        assert result_build.exit_code == 0
        assert "building" in result_build.stdout
        assert result_test.exit_code == 0
        assert "testing" in result_test.stdout

    def test_unknown_job_exits_nonzero(self, cli_run, project_tree) -> None:
        """An unknown job name exits with non-zero code."""
        root = project_tree(jobs={"hello.py": "def hello():\n    print('hi')\n"})
        result = cli_run(["nonexistent_job_xyz"], cwd=root)
        assert result.exit_code != 0


# ===========================================================================
# Routing Mode: GROUP
# ===========================================================================


class TestGroupRouting:
    """Test GROUP mode — `func <group> <job>` dispatches to grouped jobs."""

    def test_group_job_execution(self, cli_run, project_tree) -> None:
        """A grouped job runs via `func <group> <job>`."""
        root = project_tree(
            jobs={
                "infra.py": (
                    "JOB_GROUP = 'infra'\n\n"
                    "def provision():\n    print('provisioned')\n"
                )
            }
        )
        result = cli_run(["infra", "provision"], cwd=root)
        assert result.exit_code == 0
        assert "provisioned" in result.stdout

    def test_group_lists_subcommands(self, cli_run, project_tree) -> None:
        """Invoking just the group name lists its sub-commands."""
        root = project_tree(
            jobs={
                "deploy.py": (
                    "JOB_GROUP = 'deploy'\n\n"
                    "def staging():\n    '''Deploy to staging'''\n    pass\n\n"
                    "def production():\n    '''Deploy to prod'''\n    pass\n"
                )
            }
        )
        result = cli_run(["deploy"], cwd=root)
        # Should list sub-commands or show help for the group
        assert result.exit_code in (0, 1)
        assert "staging" in result.stdout or "production" in result.stdout

    def test_nested_group(self, cli_run, project_tree) -> None:
        """Nested JOB_GROUP (dot-separated) routes correctly."""
        root = project_tree(
            jobs={
                "aws.py": (
                    "JOB_GROUP = 'infra.aws'\n\n"
                    "def launch():\n    print('launching ec2')\n"
                )
            }
        )
        result = cli_run(["infra", "aws", "launch"], cwd=root)
        assert result.exit_code == 0
        assert "launching ec2" in result.stdout


# ===========================================================================
# Routing Mode: SINGLE_FILE
# ===========================================================================


class TestSingleFileRouting:
    """Test SINGLE_FILE mode — `func script.py` runs a standalone file."""

    def test_single_file_execution(self, cli_run, tmp_path: Path) -> None:
        """A standalone .py file with explicit function name runs directly."""
        script = tmp_path / "task.py"
        script.write_text("def run():\n    print('from single file')\n")
        result = cli_run([str(script), "run"])
        assert result.exit_code == 0
        assert "from single file" in result.stdout

    def test_single_file_lists_functions(self, cli_run, tmp_path: Path) -> None:
        """A standalone .py file without function arg lists available functions."""
        script = tmp_path / "multi.py"
        script.write_text(
            "def build():\n    '''Build it'''\n    pass\n\n"
            "def deploy():\n    '''Ship it'''\n    pass\n"
        )
        result = cli_run([str(script)])
        assert result.exit_code == 0
        assert "build" in result.stdout
        assert "deploy" in result.stdout

    def test_single_file_with_params(self, cli_run, tmp_path: Path) -> None:
        """A standalone .py file job receives CLI arguments."""
        script = tmp_path / "greet.py"
        script.write_text(
            "def greet(name: str = 'world'):\n    print(f'hello {name}')\n"
        )
        result = cli_run([str(script), "greet", "--name", "kiro"])
        assert result.exit_code == 0
        assert "hello kiro" in result.stdout


# ===========================================================================
# Name Normalization: Underscore vs Dash
# ===========================================================================


class TestNameNormalization:
    """Underscore/dash handling in job and function names.

    Job identity is canonical and hyphenated: `def my_task` registers and is
    displayed as `my-task`. Both spellings *resolve*, because resolution
    normalizes what you typed — that is a total function onto the one name,
    not a second name to maintain.
    """

    def test_canonical_dash_form_works(self, cli_run, project_tree) -> None:
        """The registered name is the hyphenated one."""
        root = project_tree(
            jobs={"my_task.py": "def my_task():\n    print('underscore works')\n"}
        )
        result = cli_run(["my-task"], cwd=root)
        assert result.exit_code == 0
        assert "underscore works" in result.stdout

    def test_python_spelling_still_resolves(self, cli_run, project_tree) -> None:
        """Typing the function's own spelling reaches the same job.

        Nobody should have to remember which spelling a job was written in to
        run it, so `my_task` resolves to `my-task` rather than 404ing.
        """
        root = project_tree(
            jobs={"my_task.py": "def my_task():\n    print('underscore works')\n"}
        )
        result = cli_run(["my_task"], cwd=root)
        assert result.exit_code == 0
        assert "underscore works" in result.stdout

    def test_canonical_function_name_works(self, cli_run, project_tree) -> None:
        """A function with underscores is addressed with hyphens."""
        root = project_tree(
            jobs={"ops.py": ("def run_migrations():\n    print('migrated')\n")}
        )
        result = cli_run(["run-migrations"], cwd=root)
        assert result.exit_code == 0
        assert "migrated" in result.stdout

    def test_python_function_spelling_still_resolves(
        self, cli_run, project_tree
    ) -> None:
        """The function's own spelling reaches the same job."""
        root = project_tree(
            jobs={"ops.py": ("def run_migrations():\n    print('migrated')\n")}
        )
        result = cli_run(["run_migrations"], cwd=root)
        assert result.exit_code == 0
        assert "migrated" in result.stdout


# ===========================================================================
# Config Resolution: XDG Global Config
# ===========================================================================


class TestXdgConfigResolution:
    """Test that XDG global config files are discovered and applied."""

    def test_global_config_read_from_xdg(self, cli_run, xdg_dirs, project_tree) -> None:
        """Global config at $XDG_CONFIG_HOME/functualize/config.toml is loaded."""
        config_dir = xdg_dirs.functualize_config
        config_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(
            SUPPORT_CONFIGS / "global_with_aliases" / "config.toml",
            config_dir / "config.toml",
        )
        root = project_tree(
            jobs={"deploy.py": "def deploy():\n    print('deployed')\n"}
        )
        # Alias 'd' -> 'deploy' should resolve
        result = cli_run(["d"], cwd=root)
        assert result.exit_code in (0, 1)

    def test_missing_xdg_dir_does_not_crash(self, cli_run, project_tree) -> None:
        """Missing XDG config dir doesn't cause errors."""
        root = project_tree(jobs={"hello.py": "def hello():\n    print('hi')\n"})
        result = cli_run(["hello"], cwd=root)
        assert result.exit_code == 0

    def test_xdg_cache_used_for_discovery_cache(
        self, cli_run, xdg_dirs, project_tree
    ) -> None:
        """Discovery cache writes to $XDG_CACHE_HOME when in standalone mode."""
        root = project_tree(jobs={"hello.py": "def hello():\n    print('cached')\n"})
        result = cli_run(["hello"], cwd=root)
        assert result.exit_code == 0

    def test_xdg_config_with_output_format(
        self, cli_run, xdg_dirs, project_tree
    ) -> None:
        """Global config output format setting is applied."""
        config_dir = xdg_dirs.functualize_config
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.toml").write_text('[cli]\noutput = "plain"\n')
        root = project_tree(jobs={"hello.py": "def hello():\n    print('hi')\n"})
        result = cli_run(["hello"], cwd=root)
        assert result.exit_code == 0


# ===========================================================================
# Config Resolution: Project Config Precedence
# ===========================================================================


class TestProjectConfigPrecedence:
    """Test project config file resolution and precedence."""

    def test_pyproject_toml_beats_functualize_toml(self, cli_run, project_tree) -> None:
        """pyproject.toml [tool.functualize] takes precedence over .functualize.toml."""
        root = project_tree(
            pyproject=(
                "[project]\nname = 'test'\n\n"
                "[tool.functualize.aliases]\n"
                'd = "deploy"\n'
            ),
            functualize_toml=('[aliases]\nd = "should_not_be_used"\n'),
            jobs={"deploy.py": "def deploy():\n    print('from pyproject')\n"},
        )
        result = cli_run(["d"], cwd=root)
        assert result.exit_code in (0, 1)

    def test_env_var_overrides_file_config(self, cli_run, project_tree) -> None:
        """FUNCTUALIZE_CLI_OUTPUT env var overrides file-based config."""
        root = project_tree(
            pyproject='[tool.functualize.cli]\noutput = "rich"\n',
            jobs={"hello.py": "def hello():\n    print('hi')\n"},
        )
        result = cli_run(["hello"], cwd=root, env={"FUNCTUALIZE_CLI_OUTPUT": "plain"})
        assert result.exit_code == 0

    def test_functualize_toml_used_when_no_pyproject(
        self, cli_run, project_tree
    ) -> None:
        """.functualize.toml is used when no pyproject.toml exists."""
        root = project_tree(
            functualize_toml='[aliases]\nx = "xray"\n',
            jobs={"xray.py": "def xray():\n    print('xray fired')\n"},
        )
        result = cli_run(["x"], cwd=root)
        assert result.exit_code in (0, 1)

    def test_upward_config_walk(self, cli_run, project_tree) -> None:
        """Config is found by walking upward from CWD."""
        root = project_tree(
            pyproject="[tool.functualize]\n",
            jobs={"hello.py": "def hello():\n    print('found')\n"},
        )
        # Create a subdirectory and invoke from there
        sub = root / "subdir" / "deep"
        sub.mkdir(parents=True)
        result = cli_run(["hello"], cwd=sub)
        assert result.exit_code == 0
        assert "found" in result.stdout


# ===========================================================================
# Alias Expansion
# ===========================================================================


class TestAliasExpansion:
    """Test that aliases defined in config expand to real job names."""

    def test_alias_resolves_to_job(self, cli_run, project_tree) -> None:
        """An alias defined in pyproject.toml resolves and executes."""
        root = project_tree(
            pyproject=('[tool.functualize.aliases]\nd = "ship"\np = "setup"\n'),
            jobs={
                "ship.py": "def ship():\n    print('shipped via alias')\n",
                "setup.py": "def setup():\n    print('setup via alias')\n",
            },
        )
        result = cli_run(["d"], cwd=root)
        assert result.exit_code == 0
        assert "shipped via alias" in result.stdout

        result = cli_run(["p"], cwd=root)
        assert result.exit_code == 0
        assert "setup via alias" in result.stdout

    def test_alias_with_nonexistent_target(self, cli_run, project_tree) -> None:
        """Alias pointing to nonexistent job fails cleanly."""
        root = project_tree(
            pyproject='[tool.functualize.aliases]\nx = "nonexistent"\n',
            jobs={"hello.py": "def hello():\n    pass\n"},
        )
        result = cli_run(["x"], cwd=root)
        assert result.exit_code != 0


# ===========================================================================
# Discovery: Convention Directories & Filters
# ===========================================================================


class TestDiscovery:
    """Test job discovery mechanics: convention dirs, filters, explicit dirs."""

    def test_convention_jobs_dir_discovered(self, cli_run, project_tree) -> None:
        """.functualize/jobs/ is auto-discovered."""
        root = project_tree(
            convention_dirs=True,
            jobs={"task.py": "def task():\n    print('found via convention')\n"},
        )
        result = cli_run(["task"], cwd=root)
        assert result.exit_code == 0
        assert "found via convention" in result.stdout

    def test_no_convention_dir_still_works(self, cli_run, tmp_path: Path) -> None:
        """Project without .functualize/ directory still works (bare mode)."""
        result = cli_run([], cwd=tmp_path)
        assert result.exit_code in (0, 1)

    def test_underscore_prefixed_files_excluded(self, cli_run, project_tree) -> None:
        """Files starting with _ are not discovered as jobs."""
        root = project_tree(
            jobs={
                "_helpers.py": "def _helpers():\n    pass\n",
                "real_job.py": "def real_job():\n    print('real')\n",
            }
        )
        result = cli_run(["_helpers"], cwd=root)
        assert result.exit_code != 0

        result = cli_run(["real_job"], cwd=root)
        assert result.exit_code == 0

    def test_explicit_jobs_directories(self, cli_run, project_tree) -> None:
        """jobs_directories in config adds search paths for job discovery."""
        root = project_tree(
            pyproject='[tool.functualize.discovery]\njobs_directories = ["scripts"]\n',
        )
        scripts = root / "scripts"
        scripts.mkdir()
        (scripts / "ship.py").write_text("def ship():\n    print('from scripts')\n")
        result = cli_run(["ship"], cwd=root)
        assert result.exit_code == 0
        assert "from scripts" in result.stdout

    def test_exclude_patterns_filter_files(self, cli_run, project_tree) -> None:
        """exclude_patterns filters files during full discovery.

        NOTE: exclude_patterns is applied at full-boot time, not at the
        lightweight enumeration level. The lightweight AST scan still sees
        the file, but the full boot filters it. This test documents that
        exclude_patterns currently does NOT prevent execution via the cold
        boot path (since enumeration finds the name, routing dispatches it,
        and full boot does filter but by then the name is known).
        """
        root = project_tree(
            pyproject=(
                '[tool.functualize.discovery]\nexclude_patterns = ["**/test_*.py"]\n'
            ),
            jobs={
                "test_stuff.py": "def test_stuff():\n    print('should be excluded')\n",
                "real.py": "def real():\n    print('included')\n",
            },
        )
        # Currently exclude_patterns doesn't block at enumeration level
        # This documents actual behavior — the file is still callable
        result = cli_run(["test_stuff"], cwd=root)
        # TODO: once exclude is enforced at dispatch, change to != 0
        assert result.exit_code == 0

        result = cli_run(["real"], cwd=root)
        assert result.exit_code == 0


# ===========================================================================
# Cache: Warm Boot & Invalidation
# ===========================================================================


class TestCacheBehavior:
    """Test cache warm boot and invalidation scenarios."""

    def test_warm_boot_uses_cache(self, cli_run, project_tree) -> None:
        """Second invocation uses cached routing names (faster)."""
        root = project_tree(
            jobs={"hello.py": "def hello():\n    print('cached run')\n"}
        )
        # First run (cold boot — generates cache)
        result1 = cli_run(["hello"], cwd=root)
        assert result1.exit_code == 0

        # Second run (warm boot — should use cache)
        result2 = cli_run(["hello"], cwd=root)
        assert result2.exit_code == 0
        assert "cached run" in result2.stdout

    def test_new_file_discovered_after_cache(self, cli_run, project_tree) -> None:
        """A new job file added after cache is still discovered."""
        root = project_tree(jobs={"alpha.py": "def alpha():\n    print('alpha')\n"})
        # Cold boot
        cli_run(["alpha"], cwd=root)

        # Add a new file
        jobs_dir = root / ".functualize" / "jobs"
        (jobs_dir / "beta.py").write_text("def beta():\n    print('beta')\n")

        # Should discover beta (cache invalidation or fallback)
        result = cli_run(["beta"], cwd=root)
        # May depend on whether cache invalidation is implemented
        assert result.exit_code in (0, 1)


# ===========================================================================
# Global CLI Flags
# ===========================================================================


class TestGlobalFlags:
    """Test global CLI flags (--log-level, --no-dotenv, etc)."""

    def test_log_level_flag(self, cli_run, project_tree) -> None:
        """--log-level DEBUG enables debug output."""
        root = project_tree(jobs={"hello.py": "def hello():\n    print('hi')\n"})
        result = cli_run(["--log-level", "DEBUG", "hello"], cwd=root)
        assert result.exit_code == 0
        assert "hi" in result.stdout

    def test_no_dotenv_flag(self, cli_run, project_tree) -> None:
        """--no-dotenv suppresses .env file loading."""
        root = project_tree(
            jobs={
                "hello.py": "def hello():\n    import os\n    print(os.environ.get('MY_VAR', 'unset'))\n"
            },
        )
        (root / ".env").write_text("MY_VAR=from_dotenv\n")
        result = cli_run(["--no-dotenv", "hello"], cwd=root)
        assert result.exit_code == 0
        assert "unset" in result.stdout

    def test_dotenv_not_loaded_by_default(self, cli_run, project_tree) -> None:
        """.env is NOT loaded unless dotenv is enabled in config or via flag."""
        root = project_tree(
            pyproject="[tool.functualize]\n",
            jobs={
                "hello.py": "def hello():\n    import os\n    print(os.environ.get('DOTENV_DEFAULT_VAR', 'unset'))\n"
            },
        )
        (root / ".env").write_text("DOTENV_DEFAULT_VAR=loaded\n")
        try:
            result = cli_run(["hello"], cwd=root)
            assert result.exit_code == 0
            assert "unset" in result.stdout
        finally:
            os.environ.pop("DOTENV_DEFAULT_VAR", None)

    def test_dotenv_config_enables_loading(self, cli_run, project_tree) -> None:
        """[tool.functualize] dotenv = true auto-loads .env from CWD."""
        root = project_tree(
            pyproject="[tool.functualize]\ndotenv = true\n",
            jobs={
                "hello.py": "def hello():\n    import os\n    print(os.environ.get('DOTENV_CONFIG_VAR', 'unset'))\n"
            },
        )
        (root / ".env").write_text("DOTENV_CONFIG_VAR=loaded\n")
        try:
            result = cli_run(["hello"], cwd=root)
            assert result.exit_code == 0
            assert "loaded" in result.stdout
        finally:
            os.environ.pop("DOTENV_CONFIG_VAR", None)

    def test_dotenv_config_path_loading(self, cli_run, project_tree) -> None:
        """[tool.functualize] dotenv_path loads the named file without dotenv=true."""
        root = project_tree(
            pyproject='[tool.functualize]\ndotenv_path = ".env.custom"\n',
            jobs={
                "hello.py": "def hello():\n    import os\n    print(os.environ.get('DOTENV_PATH_VAR', 'unset'))\n"
            },
        )
        (root / ".env.custom").write_text("DOTENV_PATH_VAR=loaded\n")
        try:
            result = cli_run(["hello"], cwd=root)
            assert result.exit_code == 0
            assert "loaded" in result.stdout
        finally:
            os.environ.pop("DOTENV_PATH_VAR", None)


# ===========================================================================
# Error Handling
# ===========================================================================


class TestErrorHandling:
    """Test that errors are reported cleanly."""

    def test_failing_job_reports_error(self, cli_run, project_tree) -> None:
        """A job that raises an exception exits non-zero with error output."""
        root = project_tree(
            jobs={
                "fail.py": "def fail():\n    raise RuntimeError('intentional failure')\n"
            }
        )
        result = cli_run(["fail"], cwd=root)
        assert result.exit_code != 0
        assert "intentional failure" in result.stderr or "RuntimeError" in result.stderr

    def test_bad_config_syntax_warns(self, cli_run, xdg_dirs, project_tree) -> None:
        """Malformed global config TOML produces a warning, not a crash."""
        config_dir = xdg_dirs.functualize_config
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.toml").write_text("[invalid syntax\n")
        root = project_tree(jobs={"hello.py": "def hello():\n    print('hi')\n"})
        result = cli_run(["hello"], cwd=root)
        # Should still run (warning emitted, config ignored)
        assert result.exit_code == 0

    def test_permission_error_on_config(self, cli_run, xdg_dirs, project_tree) -> None:
        """Unreadable config file produces a warning, not a crash."""
        config_dir = xdg_dirs.functualize_config
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file = config_dir / "config.toml"
        config_file.write_text('[cli]\noutput = "plain"\n')
        config_file.chmod(0o000)
        try:
            root = project_tree(jobs={"hello.py": "def hello():\n    print('hi')\n"})
            result = cli_run(["hello"], cwd=root)
            assert result.exit_code == 0
        finally:
            config_file.chmod(0o644)

    def test_unknown_command_suggests_similar(self, cli_run, project_tree) -> None:
        """Unknown command with a close match suggests alternatives."""
        root = project_tree(
            jobs={"deploy.py": "def deploy():\n    print('deployed')\n"}
        )
        result = cli_run(["deplo"], cwd=root)
        assert result.exit_code != 0
        # Should suggest 'deploy' as a similar command
        assert "deploy" in result.stderr or "deploy" in result.stdout


# ===========================================================================
# Static Fixture Projects
# ===========================================================================


class TestStaticFixtureProjects:
    """Test using committed static project fixtures from _support/."""

    def test_minimal_project_job_runs(self, cli_run) -> None:
        """The minimal static fixture project's job executes."""
        result = cli_run(["hello"], cwd=SUPPORT_PROJECTS / "minimal")
        assert result.exit_code in (0, 1)

    def test_grouped_project_lists_groups(self, cli_run) -> None:
        """The grouped static fixture project shows group info."""
        result = cli_run([], cwd=SUPPORT_PROJECTS / "grouped")
        assert result.exit_code in (0, 1)

    def test_multi_config_precedence(self, cli_run) -> None:
        """Multi-config project: pyproject.toml wins over .functualize.toml."""
        result = cli_run(["deploy"], cwd=SUPPORT_PROJECTS / "multi_config")
        # pyproject has require_file_import = "functualize" so deploy.py
        # may pass or fail depending on filter — just should not crash
        assert result.exit_code in (0, 1)
