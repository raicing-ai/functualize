"""Integration tests for the simple scaffold template.


Tests that init_project() with template="simple" creates the expected
project structure, generates valid Python and TOML files, and includes
required content (Pydantic config model, RunContext, README sections).
"""

import ast

import pytest

from functualize._cli.scaffold.generator import ScaffoldGenerator


@pytest.fixture
def generator() -> ScaffoldGenerator:
    """Create a fresh ScaffoldGenerator instance."""
    return ScaffoldGenerator()


@pytest.fixture
def simple_project(tmp_path, generator):
    """Scaffold a simple project and return the project directory."""
    project_dir = tmp_path / "my-app"
    generator.init_project("my-app", project_dir, template="simple")
    return project_dir


class TestSimpleTemplateFileStructure:
    """Verify all expected files exist after init (R4-AC4)."""

    def test_pyproject_toml_exists(self, simple_project):
        """pyproject.toml is created at project root."""
        assert (simple_project / "pyproject.toml").exists()

    def test_readme_exists(self, simple_project):
        """README.md is created at project root (R5-AC2)."""
        assert (simple_project / "README.md").exists()

    def test_package_init_exists(self, simple_project):
        """src/<package>/__init__.py is created."""
        assert (simple_project / "src" / "my_app" / "__init__.py").exists()

    def test_main_py_exists(self, simple_project):
        """src/<package>/main.py is created."""
        assert (simple_project / "src" / "my_app" / "main.py").exists()

    def test_sample_job_exists(self, simple_project):
        """src/<package>/jobs/sample_job.py is created."""
        assert (simple_project / "src" / "my_app" / "jobs" / "sample_job.py").exists()

    def test_jobs_init_exists(self, simple_project):
        """src/<package>/jobs/__init__.py is created."""
        assert (simple_project / "src" / "my_app" / "jobs" / "__init__.py").exists()

    def test_all_expected_files_present(self, simple_project):
        """All required files from R4-AC4 are present."""
        expected = [
            "pyproject.toml",
            "README.md",
            "src/my_app/__init__.py",
            "src/my_app/main.py",
            "src/my_app/jobs/sample_job.py",
            "src/my_app/jobs/__init__.py",
        ]
        for path in expected:
            assert (simple_project / path).exists(), f"Missing: {path}"


class TestSimpleTemplatePythonValidity:
    """Verify generated Python files are syntactically valid."""

    def test_init_py_parses(self, simple_project):
        """__init__.py is valid Python."""
        source = (simple_project / "src" / "my_app" / "__init__.py").read_text()
        tree = ast.parse(source)
        assert tree is not None

    def test_main_py_parses(self, simple_project):
        """main.py is valid Python."""
        source = (simple_project / "src" / "my_app" / "main.py").read_text()
        tree = ast.parse(source)
        assert tree is not None

    def test_sample_job_parses(self, simple_project):
        """sample_job.py is valid Python."""
        source = (
            simple_project / "src" / "my_app" / "jobs" / "sample_job.py"
        ).read_text()
        tree = ast.parse(source)
        assert tree is not None


class TestSimpleTemplateTomlValidity:
    """Verify generated TOML files parse correctly."""

    def test_pyproject_toml_parses(self, simple_project):
        """pyproject.toml is valid TOML."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

        content = (simple_project / "pyproject.toml").read_text()
        data = tomllib.loads(content)
        assert "project" in data
        assert data["project"]["name"] == "my-app"

    def test_pyproject_toml_has_scripts(self, simple_project):
        """pyproject.toml has the correct script entry point."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

        content = (simple_project / "pyproject.toml").read_text()
        data = tomllib.loads(content)
        assert "scripts" in data["project"]
        assert "my-app" in data["project"]["scripts"]
        assert data["project"]["scripts"]["my-app"] == "my_app.main:run"

    def test_pyproject_toml_has_build_system(self, simple_project):
        """pyproject.toml declares a valid build system."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

        content = (simple_project / "pyproject.toml").read_text()
        data = tomllib.loads(content)
        assert "build-system" in data
        assert "hatchling" in data["build-system"]["requires"]


class TestSimpleTemplateContent:
    """Verify template content meets requirements (R4-AC4, R5-AC2-3)."""

    def test_main_has_functualize_app(self, simple_project):
        """main.py contains a FunctualizeApp instance (R4-AC4)."""
        source = (simple_project / "src" / "my_app" / "main.py").read_text()
        assert "FunctualizeApp" in source

    def test_sample_job_has_pydantic_config(self, simple_project):
        """sample_job.py has a Pydantic config model (R4-AC4)."""
        source = (
            simple_project / "src" / "my_app" / "jobs" / "sample_job.py"
        ).read_text()
        assert "BaseModel" in source
        assert "Field" in source

    def test_sample_job_has_run_context(self, simple_project):
        """sample_job.py uses RunContext (R4-AC4)."""
        source = (
            simple_project / "src" / "my_app" / "jobs" / "sample_job.py"
        ).read_text()
        assert "RunContext" in source

    def test_sample_job_has_run_function(self, simple_project):
        """sample_job.py has a run function accepting config and RunContext."""
        source = (
            simple_project / "src" / "my_app" / "jobs" / "sample_job.py"
        ).read_text()
        tree = ast.parse(source)
        run_functions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "run"
        ]
        assert len(run_functions) == 1
        # Should have at least 2 params: config and rc
        assert len(run_functions[0].args.args) >= 2

    def test_readme_has_configuration_section(self, simple_project):
        """README.md has a Configuration section (R5-AC2)."""
        content = (simple_project / "README.md").read_text()
        assert "## Configuration" in content

    def test_readme_has_usage_section(self, simple_project):
        """README.md has a Usage section (R5-AC2)."""
        content = (simple_project / "README.md").read_text()
        assert "## Usage" in content

    def test_readme_has_extension_points_section(self, simple_project):
        """README.md has an Extension Points section (R5-AC2)."""
        content = (simple_project / "README.md").read_text()
        assert "## Extension Points" in content

    def test_init_has_version(self, simple_project):
        """__init__.py has a __version__ attribute."""
        source = (simple_project / "src" / "my_app" / "__init__.py").read_text()
        assert "__version__" in source


class TestSimpleTemplateWithHyphenatedName:
    """Verify template handles project names with hyphens correctly."""

    def test_hyphenated_name_creates_underscore_package(self, tmp_path, generator):
        """Hyphens in project name become underscores in package name."""
        project_dir = tmp_path / "my-cool-app"
        generator.init_project("my-cool-app", project_dir, template="simple")

        assert (project_dir / "src" / "my_cool_app" / "__init__.py").exists()
        assert (project_dir / "src" / "my_cool_app" / "main.py").exists()
        assert (project_dir / "src" / "my_cool_app" / "jobs" / "sample_job.py").exists()

    def test_pyproject_preserves_hyphenated_name(self, tmp_path, generator):
        """pyproject.toml uses the original hyphenated project name."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

        project_dir = tmp_path / "my-cool-app"
        generator.init_project("my-cool-app", project_dir, template="simple")

        content = (project_dir / "pyproject.toml").read_text()
        data = tomllib.loads(content)
        assert data["project"]["name"] == "my-cool-app"
