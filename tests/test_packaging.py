"""Tests for package build and installation verification.

Verifies that the functualize package:
- Builds successfully producing sdist and wheel artifacts
- Declares the 'functualize' console entry point
- Declares the 'functualize.plugins' entry point group
- Has all required metadata fields (name, version, description, requires-python, dependencies)

Requirements: 14.1, 14.4, 14.6, 14.7, 14.8
"""

import importlib.metadata
import subprocess
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def _declared_version() -> str:
    """The version `pyproject.toml` declares — the release's source of truth.

    Asserted against rather than hardcoded. A literal here is a fourteenth place
    the version is declared, on top of the thirteen `CONTRIBUTING.md` lists, and
    it is one no release checklist mentions: bumping the documented thirteen and
    running the suite lands red, which is exactly what happened cutting 0.1.1.
    Comparing the sources to each other keeps the invariant that matters — every
    declaration agrees — without adding a site to bump.
    """
    data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text("utf-8"))
    version: str = data["project"]["version"]
    return version


class TestPackageMetadata:
    """Verify installed package metadata meets requirements."""

    def test_package_is_importable(self):
        """The functualize package can be imported."""
        import functualize

        assert hasattr(functualize, "__version__")
        assert functualize.__version__ == _declared_version()

    def test_package_has_required_metadata_fields(self):
        """Package metadata includes name, version, description, requires-python."""
        meta = importlib.metadata.metadata("functualize")

        assert meta["Name"] == "functualize"
        assert meta["Version"] == _declared_version()
        assert meta["Summary"] is not None and len(meta["Summary"]) > 0
        assert meta["Requires-Python"] is not None

    def test_package_declares_dependencies(self):
        """Package declares all required dependencies with minimum versions."""
        meta = importlib.metadata.metadata("functualize")
        requires = meta.get_all("Requires-Dist") or []

        required_deps = [
            "click",
            "textual",
            "pydantic",
            "python-dotenv",
            "rich",
        ]
        declared_dep_names = [
            r.split(">")[0].split("<")[0].split("=")[0].split("[")[0].strip()
            for r in requires
        ]

        for dep in required_deps:
            assert dep in declared_dep_names, f"Missing dependency: {dep}"

    def test_package_does_not_declare_typer(self):
        """functualize must not declare typer — the CLI layer is click-native.

        typer may still be present transitively (via unrelated packages); this
        guards only against functualize itself depending on it again.
        """
        meta = importlib.metadata.metadata("functualize")
        requires = meta.get_all("Requires-Dist") or []
        declared_dep_names = [
            r.split(">")[0]
            .split("<")[0]
            .split("=")[0]
            .split("[")[0]
            .split(";")[0]
            .strip()
            for r in requires
        ]
        assert "typer" not in declared_dep_names, (
            "functualize should not declare typer as a dependency"
        )

    def test_console_entry_point_declared(self):
        """The 'functualize' console script entry point is declared."""
        # `entry_points(group=...)` rather than iterating `entry_points()`:
        # the bare call returns the deprecated SelectableGroups mapping, and
        # iterating *that* yields group names (`str`), not EntryPoint objects
        # — so the old filter raised AttributeError on `ep.group` instead of
        # checking anything.
        console_scripts = [
            ep
            for ep in importlib.metadata.entry_points(group="console_scripts")
            if ep.name == "functualize"
        ]

        assert len(console_scripts) == 1
        assert console_scripts[0].value == "functualize._cli.main:main"

    def test_plugin_entry_point_group_declared_in_pyproject(self):
        """The functualize.plugins entry point group is declared in pyproject.toml."""
        pyproject_path = PROJECT_ROOT / "pyproject.toml"
        content = pyproject_path.read_text()

        assert '[project.entry-points."functualize.plugins"]' in content

    def test_hatchling_build_backend_declared(self):
        """The build system uses hatchling as declared in pyproject.toml."""
        pyproject_path = PROJECT_ROOT / "pyproject.toml"
        content = pyproject_path.read_text()

        assert 'build-backend = "hatchling.build"' in content
        assert '"hatchling"' in content


class TestConsoleEntryPoint:
    """Verify the functualize console entry point works."""

    def test_functualize_cli_shows_help(self, tmp_path):
        """The functualize CLI entry point displays help text without errors."""
        # Run from tmp_path to avoid discovering repo source files as jobs
        result = subprocess.run(
            ["uv", "run", "func", "--help"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            timeout=30,
        )
        assert result.returncode == 0
        assert "Usage" in result.stdout or "usage" in result.stdout.lower()

    def test_functualize_entry_point_callable(self):
        """The main() function referenced by the entry point is callable."""
        from functualize._cli.main import main

        assert callable(main)

    def test_functualize_new_command_available(self, tmp_path):
        """The 'builtin scaffold init' sub-command is available in the CLI."""
        # Run from tmp_path to avoid CWD job discovery issues
        result = subprocess.run(
            ["uv", "run", "func", "builtin", "scaffold", "init", "--help"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            timeout=30,
        )
        assert result.returncode == 0
        assert "project" in result.stdout.lower() or "name" in result.stdout.lower()

    def test_functualize_add_command_available(self, tmp_path):
        """The 'builtin scaffold add' sub-command group is available in the CLI."""
        # Run from tmp_path to avoid CWD job discovery issues
        result = subprocess.run(
            ["uv", "run", "func", "builtin", "scaffold", "add", "--help"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            timeout=30,
        )
        assert result.returncode == 0
        assert "job" in result.stdout.lower()
        assert "plugin" in result.stdout.lower()

    def test_functualize_console_script_executable(self, tmp_path):
        """The 'functualize' console script is executable via subprocess."""
        # Run from tmp_path to avoid CWD job discovery issues
        result = subprocess.run(
            ["uv", "run", "functualize", "--help"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            timeout=30,
        )
        assert result.returncode == 0
        assert "Usage" in result.stdout or "usage" in result.stdout.lower()


class TestBuildArtifacts:
    """Verify that the package builds correctly."""

    def test_build_produces_sdist_and_wheel(self, tmp_path):
        """Running uv build produces both .tar.gz and .whl files."""
        result = subprocess.run(
            ["uv", "build", "--out-dir", str(tmp_path)],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=120,
        )
        assert result.returncode == 0, f"Build failed: {result.stderr}"

        # Check for sdist
        tar_files = list(tmp_path.glob("*.tar.gz"))
        assert len(tar_files) == 1, f"Expected 1 sdist, found: {tar_files}"
        assert "functualize" in tar_files[0].name

        # Check for wheel
        whl_files = list(tmp_path.glob("*.whl"))
        assert len(whl_files) == 1, f"Expected 1 wheel, found: {whl_files}"
        assert "functualize" in whl_files[0].name

    def test_wheel_contains_entry_points(self, tmp_path):
        """The built wheel contains correct entry_points.txt."""
        import zipfile

        # Build first
        result = subprocess.run(
            ["uv", "build", "--out-dir", str(tmp_path)],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=120,
        )
        assert result.returncode == 0, f"Build failed: {result.stderr}"

        whl_files = list(tmp_path.glob("*.whl"))
        assert len(whl_files) == 1

        with zipfile.ZipFile(whl_files[0]) as zf:
            entry_points_files = [f for f in zf.namelist() if "entry_points.txt" in f]
            assert len(entry_points_files) == 1

            content = zf.read(entry_points_files[0]).decode()
            assert "[console_scripts]" in content
            assert "functualize = functualize._cli.main:main" in content
