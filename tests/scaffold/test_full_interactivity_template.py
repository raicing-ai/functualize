"""Integration tests for the full-interactivity scaffold template.


Tests that init_project() with template="full-interactivity" creates the expected
project structure, generates valid Python and TOML files, includes plugin
dependencies, and demonstrates all interactivity patterns (prompts, events,
workflow steps).
"""

import ast

import pytest

from functualize._cli.scaffold.generator import ScaffoldGenerator


@pytest.fixture
def generator() -> ScaffoldGenerator:
    """Create a fresh ScaffoldGenerator instance."""
    return ScaffoldGenerator()


@pytest.fixture
def full_project(tmp_path, generator):
    """Scaffold a full-interactivity project and return the project directory."""
    project_dir = tmp_path / "my-app"
    generator.init_project("my-app", project_dir, template="full-interactivity")
    return project_dir


class TestFullInteractivityFileStructure:
    """Verify all expected files exist after init (R4-AC5)."""

    def test_pyproject_toml_exists(self, full_project):
        """pyproject.toml is created at project root."""
        assert (full_project / "pyproject.toml").exists()

    def test_readme_exists(self, full_project):
        """README.md is created at project root (R5-AC2)."""
        assert (full_project / "README.md").exists()

    def test_package_init_exists(self, full_project):
        """src/<package>/__init__.py is created."""
        assert (full_project / "src" / "my_app" / "__init__.py").exists()

    def test_main_py_exists(self, full_project):
        """src/<package>/main.py is created."""
        assert (full_project / "src" / "my_app" / "main.py").exists()

    def test_interactive_job_exists(self, full_project):
        """src/<package>/jobs/interactive_job.py is created."""
        assert (
            full_project / "src" / "my_app" / "jobs" / "interactive_job.py"
        ).exists()

    def test_workflow_job_exists(self, full_project):
        """src/<package>/jobs/workflow_job.py is created."""
        assert (full_project / "src" / "my_app" / "jobs" / "workflow_job.py").exists()

    def test_events_job_exists(self, full_project):
        """src/<package>/jobs/events_job.py is created."""
        assert (full_project / "src" / "my_app" / "jobs" / "events_job.py").exists()

    def test_jobs_init_exists(self, full_project):
        """src/<package>/jobs/__init__.py is created."""
        assert (full_project / "src" / "my_app" / "jobs" / "__init__.py").exists()

    def test_all_expected_files_present(self, full_project):
        """All required files from R4-AC5 are present."""
        expected = [
            "pyproject.toml",
            "README.md",
            "src/my_app/__init__.py",
            "src/my_app/main.py",
            "src/my_app/jobs/interactive_job.py",
            "src/my_app/jobs/workflow_job.py",
            "src/my_app/jobs/events_job.py",
            "src/my_app/jobs/__init__.py",
        ]
        for path in expected:
            assert (full_project / path).exists(), f"Missing: {path}"


class TestFullInteractivityPythonValidity:
    """Verify generated Python files are syntactically valid."""

    def test_init_py_parses(self, full_project):
        """__init__.py is valid Python."""
        source = (full_project / "src" / "my_app" / "__init__.py").read_text()
        tree = ast.parse(source)
        assert tree is not None

    def test_main_py_parses(self, full_project):
        """main.py is valid Python."""
        source = (full_project / "src" / "my_app" / "main.py").read_text()
        tree = ast.parse(source)
        assert tree is not None

    def test_interactive_job_parses(self, full_project):
        """interactive_job.py is valid Python."""
        source = (
            full_project / "src" / "my_app" / "jobs" / "interactive_job.py"
        ).read_text()
        tree = ast.parse(source)
        assert tree is not None

    def test_workflow_job_parses(self, full_project):
        """workflow_job.py is valid Python."""
        source = (
            full_project / "src" / "my_app" / "jobs" / "workflow_job.py"
        ).read_text()
        tree = ast.parse(source)
        assert tree is not None

    def test_events_job_parses(self, full_project):
        """events_job.py is valid Python."""
        source = (
            full_project / "src" / "my_app" / "jobs" / "events_job.py"
        ).read_text()
        tree = ast.parse(source)
        assert tree is not None


class TestFullInteractivityTomlValidity:
    """Verify generated TOML files parse correctly."""

    def test_pyproject_toml_parses(self, full_project):
        """pyproject.toml is valid TOML."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

        content = (full_project / "pyproject.toml").read_text()
        data = tomllib.loads(content)
        assert "project" in data
        assert data["project"]["name"] == "my-app"

    def test_pyproject_toml_has_scripts(self, full_project):
        """pyproject.toml has the correct script entry point."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

        content = (full_project / "pyproject.toml").read_text()
        data = tomllib.loads(content)
        assert "scripts" in data["project"]
        assert "my-app" in data["project"]["scripts"]
        assert data["project"]["scripts"]["my-app"] == "my_app.main:run"

    def test_pyproject_toml_has_build_system(self, full_project):
        """pyproject.toml declares a valid build system."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

        content = (full_project / "pyproject.toml").read_text()
        data = tomllib.loads(content)
        assert "build-system" in data
        assert "hatchling" in data["build-system"]["requires"]


class TestFullInteractivityPluginDependencies:
    """Verify pyproject.toml declares interactivity plugin dependencies (R5-AC4)."""

    def test_has_functualize_dependency(self, full_project):
        """pyproject.toml lists functualize as a dependency."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

        content = (full_project / "pyproject.toml").read_text()
        data = tomllib.loads(content)
        deps = data["project"]["dependencies"]
        assert any("functualize" in d for d in deps)

    def test_has_inline_plugin_dependency(self, full_project):
        """pyproject.toml lists functualize-inline as a dependency."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

        content = (full_project / "pyproject.toml").read_text()
        data = tomllib.loads(content)
        deps = data["project"]["dependencies"]
        assert any("functualize-inline" in d for d in deps)

    def test_has_flow_viz_plugin_dependency(self, full_project):
        """pyproject.toml lists functualize-flow-viz as a dependency."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

        content = (full_project / "pyproject.toml").read_text()
        data = tomllib.loads(content)
        deps = data["project"]["dependencies"]
        assert any("functualize-flow-viz" in d for d in deps)

    def test_has_execution_state_plugin_dependency(self, full_project):
        """pyproject.toml lists functualize-state-sqlite as a dependency."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

        content = (full_project / "pyproject.toml").read_text()
        data = tomllib.loads(content)
        deps = data["project"]["dependencies"]
        assert any("functualize-state-sqlite" in d for d in deps)

    def test_has_plugin_entry_points(self, full_project):
        """pyproject.toml has functualize.plugins entry-point group (R5-AC4)."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

        content = (full_project / "pyproject.toml").read_text()
        data = tomllib.loads(content)
        entry_points = data.get("project", {}).get("entry-points", {})
        assert "functualize.plugins" in entry_points

    def test_entry_points_has_inline(self, full_project):
        """Entry points configure the inline plugin."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

        content = (full_project / "pyproject.toml").read_text()
        data = tomllib.loads(content)
        plugins = data["project"]["entry-points"]["functualize.plugins"]
        assert "inline" in plugins

    def test_entry_points_has_execution_state(self, full_project):
        """Entry points configure the execution-state plugin."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

        content = (full_project / "pyproject.toml").read_text()
        data = tomllib.loads(content)
        plugins = data["project"]["entry-points"]["functualize.plugins"]
        assert "execution-state" in plugins


class TestFullInteractivityContent:
    """Verify template content demonstrates all interactivity features (R4-AC5)."""

    def test_main_has_functualize_app(self, full_project):
        """main.py contains a FunctualizeApp instance."""
        source = (full_project / "src" / "my_app" / "main.py").read_text()
        assert "FunctualizeApp" in source

    def test_main_has_plugins_configured(self, full_project):
        """main.py opts into entry-point plugin discovery.

        It used to list `functualize_inline` / `_flow_viz` / `_state_sqlite` as
        `explicit_plugins`, which was wrong twice over: those are *strings*
        where the field takes constructed plugin objects, and the entry-point
        group above already discovers them from the installed packages. On the
        standard boot path the list was dropped silently; once
        `explicit_plugins` was honoured there (F1) it would have started
        warning on every boot instead.
        """
        source = (full_project / "src" / "my_app" / "main.py").read_text()
        assert 'entry_point_group="functualize.plugins"' in source
        for stale in ("functualize_inline", "functualize_flow_viz"):
            assert stale not in source

    def test_interactive_job_has_prompt_confirm(self, full_project):
        """interactive_job.py demonstrates rc.prompt_confirm() (R4-AC5)."""
        source = (
            full_project / "src" / "my_app" / "jobs" / "interactive_job.py"
        ).read_text()
        assert "prompt_confirm" in source

    def test_interactive_job_has_prompt_choice(self, full_project):
        """interactive_job.py demonstrates rc.prompt_choice() (R4-AC5)."""
        source = (
            full_project / "src" / "my_app" / "jobs" / "interactive_job.py"
        ).read_text()
        assert "prompt_choice" in source

    def test_interactive_job_has_prompt_text(self, full_project):
        """interactive_job.py demonstrates rc.prompt_text() (R4-AC5)."""
        source = (
            full_project / "src" / "my_app" / "jobs" / "interactive_job.py"
        ).read_text()
        assert "prompt_text" in source

    def test_workflow_job_has_track_phase(self, full_project):
        """workflow_job.py demonstrates rc.track_phase() (R4-AC5)."""
        source = (
            full_project / "src" / "my_app" / "jobs" / "workflow_job.py"
        ).read_text()
        assert "track_phase" in source

    def test_events_job_has_emit(self, full_project):
        """events_job.py demonstrates rc.emit() (R4-AC5)."""
        source = (
            full_project / "src" / "my_app" / "jobs" / "events_job.py"
        ).read_text()
        assert "rc.emit(" in source

    def test_readme_has_configuration_section(self, full_project):
        """README.md has a Configuration section (R5-AC2)."""
        content = (full_project / "README.md").read_text()
        assert "## Configuration" in content

    def test_readme_has_usage_section(self, full_project):
        """README.md has a Usage section (R5-AC2)."""
        content = (full_project / "README.md").read_text()
        assert "## Usage" in content

    def test_readme_has_extension_points_section(self, full_project):
        """README.md has an Extension Points section (R5-AC2)."""
        content = (full_project / "README.md").read_text()
        assert "## Extension Points" in content

    def test_init_has_version(self, full_project):
        """__init__.py has a __version__ attribute."""
        source = (full_project / "src" / "my_app" / "__init__.py").read_text()
        assert "__version__" in source


class TestFullInteractivityWithHyphenatedName:
    """Verify template handles project names with hyphens correctly."""

    def test_hyphenated_name_creates_underscore_package(self, tmp_path, generator):
        """Hyphens in project name become underscores in package name."""
        project_dir = tmp_path / "my-cool-app"
        generator.init_project(
            "my-cool-app", project_dir, template="full-interactivity"
        )

        assert (project_dir / "src" / "my_cool_app" / "__init__.py").exists()
        assert (project_dir / "src" / "my_cool_app" / "main.py").exists()
        assert (
            project_dir / "src" / "my_cool_app" / "jobs" / "interactive_job.py"
        ).exists()
        assert (
            project_dir / "src" / "my_cool_app" / "jobs" / "workflow_job.py"
        ).exists()
        assert (project_dir / "src" / "my_cool_app" / "jobs" / "events_job.py").exists()

    def test_pyproject_preserves_hyphenated_name(self, tmp_path, generator):
        """pyproject.toml uses the original hyphenated project name."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

        project_dir = tmp_path / "my-cool-app"
        generator.init_project(
            "my-cool-app", project_dir, template="full-interactivity"
        )

        content = (project_dir / "pyproject.toml").read_text()
        data = tomllib.loads(content)
        assert data["project"]["name"] == "my-cool-app"
