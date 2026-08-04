"""Integration tests for the job-folder scaffold template.

Validates: Requirements R4-AC7, R5-AC2/6

Tests that init_project() with template="job-folder" creates a flat directory
structure (no src/, no main.py) with a standalone job, file-based plugin,
config file, and README.
"""

import ast

import pytest

from functualize._cli.scaffold.generator import ScaffoldGenerator


@pytest.fixture
def generator() -> ScaffoldGenerator:
    """Create a fresh ScaffoldGenerator instance."""
    return ScaffoldGenerator()


@pytest.fixture
def job_folder_project(tmp_path, generator):
    """Scaffold a job-folder project and return the project directory."""
    project_dir = tmp_path / "my-jobs"
    generator.init_project("my-jobs", project_dir, template="job-folder")
    return project_dir


class TestJobFolderFileStructure:
    """Verify all expected files exist after init (R4-AC7)."""

    def test_sample_job_exists(self, job_folder_project):
        """sample_job.py is created at project root."""
        assert (job_folder_project / "sample_job.py").exists()

    def test_file_plugin_exists(self, job_folder_project):
        """.functualize/plugins/file_plugin.py is created (R5-AC6)."""
        assert (
            job_folder_project / ".functualize" / "plugins" / "file_plugin.py"
        ).exists()

    def test_config_base_toml_exists(self, job_folder_project):
        """config.base.toml is created at project root."""
        assert (job_folder_project / "config.base.toml").exists()

    def test_readme_exists(self, job_folder_project):
        """README.md is created at project root (R5-AC2)."""
        assert (job_folder_project / "README.md").exists()

    def test_all_expected_files_present(self, job_folder_project):
        """All required files from R4-AC7 are present."""
        expected = [
            "sample_job.py",
            ".functualize/plugins/file_plugin.py",
            "config.base.toml",
            "README.md",
        ]
        for path in expected:
            assert (job_folder_project / path).exists(), f"Missing: {path}"

    def test_no_src_directory(self, job_folder_project):
        """Job folder does NOT have a src/ directory (R4-AC7)."""
        assert not (job_folder_project / "src").exists()

    def test_no_main_py(self, job_folder_project):
        """Job folder does NOT have a main.py (R4-AC7)."""
        assert not (job_folder_project / "main.py").exists()

    def test_no_pyproject_toml(self, job_folder_project):
        """Job folder does NOT have a pyproject.toml (not a package project)."""
        assert not (job_folder_project / "pyproject.toml").exists()


class TestJobFolderPythonValidity:
    """Verify generated Python files are syntactically valid."""

    def test_sample_job_parses(self, job_folder_project):
        """sample_job.py is valid Python."""
        source = (job_folder_project / "sample_job.py").read_text()
        tree = ast.parse(source)
        assert tree is not None

    def test_file_plugin_parses(self, job_folder_project):
        """file_plugin.py is valid Python."""
        source = (
            job_folder_project / ".functualize" / "plugins" / "file_plugin.py"
        ).read_text()
        tree = ast.parse(source)
        assert tree is not None


class TestJobFolderTomlValidity:
    """Verify generated TOML files parse correctly."""

    def test_config_base_toml_parses(self, job_folder_project):
        """config.base.toml is valid TOML."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

        content = (job_folder_project / "config.base.toml").read_text()
        data = tomllib.loads(content)
        assert "general" in data

    def test_config_has_log_level(self, job_folder_project):
        """config.base.toml has log_level setting in [general]."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

        content = (job_folder_project / "config.base.toml").read_text()
        data = tomllib.loads(content)
        assert data["general"]["log_level"] == "info"


class TestJobFolderContent:
    """Verify template content meets requirements (R4-AC7, R5-AC2/6)."""

    def test_sample_job_has_public_function(self, job_folder_project):
        """sample_job.py has at least one public function (R4-AC7)."""
        source = (job_folder_project / "sample_job.py").read_text()
        tree = ast.parse(source)
        public_functions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
        ]
        assert len(public_functions) >= 1

    def test_sample_job_uses_run_context(self, job_folder_project):
        """sample_job.py uses RunContext (R4-AC7)."""
        source = (job_folder_project / "sample_job.py").read_text()
        assert "RunContext" in source

    def test_sample_job_no_functualize_app(self, job_folder_project):
        """sample_job.py does NOT import FunctualizeApp (R4-AC7)."""
        source = (job_folder_project / "sample_job.py").read_text()
        assert "FunctualizeApp" not in source

    def test_file_plugin_has_callable_class(self, job_folder_project):
        """file_plugin.py has a callable class (R5-AC6)."""
        source = (
            job_folder_project / ".functualize" / "plugins" / "file_plugin.py"
        ).read_text()
        tree = ast.parse(source)
        classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        assert len(classes) >= 1

        # Check class has __call__ method (callable)
        plugin_class = classes[0]
        call_methods = [
            node
            for node in ast.walk(plugin_class)
            if isinstance(node, ast.FunctionDef) and node.name == "__call__"
        ]
        assert len(call_methods) == 1

    def test_file_plugin_has_name_attribute(self, job_folder_project):
        """file_plugin.py class has a name attribute (R5-AC6)."""
        source = (
            job_folder_project / ".functualize" / "plugins" / "file_plugin.py"
        ).read_text()
        assert "name = " in source

    def test_file_plugin_has_lifecycle_method(self, job_folder_project):
        """file_plugin.py implements at least one lifecycle method (R5-AC6)."""
        source = (
            job_folder_project / ".functualize" / "plugins" / "file_plugin.py"
        ).read_text()
        tree = ast.parse(source)
        classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        assert len(classes) >= 1

        plugin_class = classes[0]
        lifecycle_methods = [
            node
            for node in ast.walk(plugin_class)
            if isinstance(node, ast.FunctionDef)
            and node.name
            in (
                "on_job_start",
                "on_job_end",
                "on_run_start",
                "before_job",
                "after_success",
            )
        ]
        assert len(lifecycle_methods) >= 1

    def test_readme_has_configuration_section(self, job_folder_project):
        """README.md has a Configuration section (R5-AC2)."""
        content = (job_folder_project / "README.md").read_text()
        assert "## Configuration" in content

    def test_readme_has_usage_section(self, job_folder_project):
        """README.md has a Usage section (R5-AC2)."""
        content = (job_folder_project / "README.md").read_text()
        assert "## Usage" in content

    def test_readme_has_extension_points_section(self, job_folder_project):
        """README.md has an Extension Points section (R5-AC2)."""
        content = (job_folder_project / "README.md").read_text()
        assert "## Extension Points" in content


class TestJobFolderWithHyphenatedName:
    """Verify template handles project names with hyphens correctly."""

    def test_hyphenated_name_renders_correctly(self, tmp_path, generator):
        """Hyphens in project name are preserved in template context."""
        project_dir = tmp_path / "my-cool-jobs"
        generator.init_project("my-cool-jobs", project_dir, template="job-folder")

        assert (project_dir / "sample_job.py").exists()
        assert (project_dir / ".functualize" / "plugins" / "file_plugin.py").exists()
        assert (project_dir / "config.base.toml").exists()
        assert (project_dir / "README.md").exists()

    def test_hyphenated_name_no_src_directory(self, tmp_path, generator):
        """Job folder with hyphenated name still has no src/ directory."""
        project_dir = tmp_path / "my-cool-jobs"
        generator.init_project("my-cool-jobs", project_dir, template="job-folder")

        assert not (project_dir / "src").exists()

    def test_hyphenated_name_no_main_py(self, tmp_path, generator):
        """Job folder with hyphenated name still has no main.py."""
        project_dir = tmp_path / "my-cool-jobs"
        generator.init_project("my-cool-jobs", project_dir, template="job-folder")

        assert not (project_dir / "main.py").exists()
