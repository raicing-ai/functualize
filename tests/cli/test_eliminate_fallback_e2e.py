"""Integration tests for the direct dispatch flow (FallbackGroup eliminated).

Exercises the full CLI dispatch pipeline end-to-end via subprocess to verify:
- Job dispatch from subdirectory (config upward walk)
- Fuzzy suggestions for typos
- Bare invocation in non-TTY (job list output)
- Global --import-libs applied
- Alias expansion and execution
- Single-file mode regression
- FallbackGroup NOT in the import chain

These tests use `subprocess.run` with `uv run func` in temporary project
directories to ensure the full main() path is exercised.

Requirements: 3.1, 3.2, 4.1, 5.1, 6.2, 9.8, 10.2, 12.3
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

# Use the project root so `uv run` picks up the workspace
PROJECT_ROOT = Path(__file__).parent.parent.parent


def _write_project(tmp_path: Path, *, aliases: dict[str, str] | None = None) -> Path:
    """Set up a minimal functualize project in tmp_path.

    Creates:
    - .functualize.toml with jobs_directories pointing to jobs/
    - jobs/ directory with a simple job file

    Returns the project root path.
    """
    # Config file — jobs_directories MUST be at top level (before any section)
    toml_lines = [
        'jobs_directories = ["jobs"]',
    ]
    if aliases:
        toml_lines.append("")
        toml_lines.append("[aliases]")
        for alias, target in aliases.items():
            toml_lines.append(f'{alias} = "{target}"')

    (tmp_path / ".functualize.toml").write_text("\n".join(toml_lines) + "\n")

    # Jobs directory with a simple job
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()

    (jobs_dir / "greet.py").write_text(
        '"""Greet someone by name."""\n'
        "\n"
        "\n"
        "def greet(name: str = 'World') -> None:\n"
        '    """Say hello to someone."""\n'
        "    print(f'Hello, {name}!')\n"
    )

    (jobs_dir / "deploy.py").write_text(
        '"""Deploy the application."""\n'
        "\n"
        "\n"
        "def deploy(env: str = 'staging') -> None:\n"
        '    """Deploy to a target environment."""\n'
        "    print(f'Deploying to {env}')\n"
    )

    return tmp_path


def _run_func(
    *args: str,
    cwd: str | Path,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    """Run `uv run func` with the given args in the specified directory."""
    return subprocess.run(
        ["uv", "run", "--project", str(PROJECT_ROOT), "func", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=timeout,
    )


class TestJobDispatchFromSubdirectory:
    """Test: `func <job> --help` from subdirectory → help output shown.

    Validates that config upward walk discovers the .functualize.toml from
    an ancestor directory, resolves jobs_directories, and routes to the job.

    Requirements: 4.1, 9.8 (upward walk B-1)
    """

    def test_job_help_from_subdirectory(self, tmp_path: Path) -> None:
        """Running `func greet --help` from a subdirectory shows help."""
        project = _write_project(tmp_path)
        subdir = project / "sub" / "deep"
        subdir.mkdir(parents=True)

        result = _run_func("greet", "--help", cwd=subdir)

        assert result.returncode == 0, f"stderr: {result.stderr}"
        # Help output should mention the parameter 'name'
        assert "name" in result.stdout.lower()


class TestFuzzySuggestionOnTypo:
    """Test: `func <typo>` → fuzzy suggestion output on stderr, exit code 1.

    Requirements: 3.2, 5.1
    """

    def test_typo_shows_suggestion(self, tmp_path: Path) -> None:
        """Mistyped command shows suggestions and exits with code 1."""
        project = _write_project(tmp_path)

        result = _run_func("gret", cwd=project)

        assert result.returncode == 1
        # Should mention the unknown command
        assert "gret" in result.stderr
        # Should suggest the close match
        assert "greet" in result.stderr
        # Should have guidance
        assert "func" in result.stderr


class TestBareInvocationNonTTY:
    """Test: `func` in non-TTY → job list output.

    When piped (no TTY), `func` should print discovered jobs.

    Requirements: 6.2
    """

    def test_bare_invocation_lists_jobs(self, tmp_path: Path) -> None:
        """Bare `func` in non-TTY outputs discovered job names."""
        project = _write_project(tmp_path)

        # subprocess is inherently non-TTY (stdin/stdout are pipes)
        result = _run_func(cwd=project)

        assert result.returncode == 0, f"stderr: {result.stderr}"
        # Should list the discovered jobs
        assert "greet" in result.stdout
        assert "deploy" in result.stdout


class TestGlobalImportLibsApplied:
    """Test: `func --import-libs ./lib <job>` → import_libs applied.

    Verifies that the --import-libs global flag prepends paths to sys.path
    before job modules are imported.

    Requirements: 10.2
    """

    def test_import_libs_makes_module_available(self, tmp_path: Path) -> None:
        """Global --import-libs allows job to import from specified path."""
        project = _write_project(tmp_path)

        # Create a library directory with a helper module
        lib_dir = project / "mylib"
        lib_dir.mkdir()
        (lib_dir / "helper.py").write_text("GREETING = 'Hello from helper'\n")

        # Create a job that imports from the helper module
        jobs_dir = project / "jobs"
        (jobs_dir / "use_helper.py").write_text(
            '"""Use helper module."""\n'
            "\n"
            "from helper import GREETING\n"
            "\n"
            "\n"
            "def use_helper() -> None:\n"
            '    """Print greeting from helper."""\n'
            "    print(GREETING)\n"
        )

        result = _run_func("--import-libs", "./mylib", "use_helper", cwd=project)

        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Hello from helper" in result.stdout


class TestAliasExpansion:
    """Test: `func <alias>` → alias expansion and execution.

    Requirements: 12.3
    """

    def test_alias_resolves_to_target_job(self, tmp_path: Path) -> None:
        """Alias defined in config expands to target job and executes."""
        project = _write_project(tmp_path, aliases={"g": "greet"})

        result = _run_func("g", cwd=project)

        assert result.returncode == 0, f"stderr: {result.stderr}"
        # Should execute the greet job (default name='World')
        assert "Hello, World!" in result.stdout


class TestSingleFileMode:
    """Test: `func script.py` → single-file mode still works (regression).

    Verifies that the direct dispatch flow didn't break single-file mode.

    Requirements: 3.1, 9.8
    """

    def test_single_file_execution(self, tmp_path: Path) -> None:
        """Running `func script.py function` executes the function."""
        project = _write_project(tmp_path)

        # Create a standalone script in the project directory
        script = project / "myscript.py"
        script.write_text(
            '"""A standalone script."""\n'
            "\n"
            "\n"
            "def hello(greeting: str = 'Hi') -> None:\n"
            '    """Print a greeting."""\n'
            "    print(f'{greeting} there!')\n"
        )

        result = _run_func("myscript.py", "hello", cwd=project)

        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Hi there!" in result.stdout


class TestFallbackGroupNotInImportChain:
    """Verify FallbackGroup is NOT in the import chain of _cli/main.py.

    Requirements: 3.1, 3.2
    """

    def test_fallback_group_not_imported_in_cli_main(self) -> None:
        """_cli/main.py does not import FallbackGroup anywhere."""
        main_path = PROJECT_ROOT / "src" / "functualize" / "_cli" / "main.py"
        source = main_path.read_text()

        # Check that no active import line references FallbackGroup
        for line in source.splitlines():
            stripped = line.strip()
            # Skip comments and blank lines
            if stripped.startswith("#") or not stripped:
                continue
            # Check for import statements that mention FallbackGroup
            if ("import" in stripped) and ("FallbackGroup" in stripped):
                pytest.fail(f"FallbackGroup is imported in _cli/main.py: {stripped}")

    def test_cli_app_not_using_fallback_group_cls(self) -> None:
        """cli_app Typer constructor does not use cls=FallbackGroup."""
        main_path = PROJECT_ROOT / "src" / "functualize" / "_cli" / "main.py"
        source = main_path.read_text()

        # Check that cli_app doesn't use cls=FallbackGroup or cls=TyperGroup
        assert "cls=FallbackGroup" not in source
        assert "cls=TyperGroup" not in source
