"""Integration tests for the plugin-project scaffold template.

Validates: Requirements R4-AC6, R5-AC2/5

Tests that init_project() with template="plugin-project" creates the expected
project structure, generates valid Python and TOML files, includes entry-point
configuration, and contains OutputRenderer and InputProvider implementations.
"""

import ast

import pytest

from functualize._cli.scaffold.generator import ScaffoldGenerator


@pytest.fixture
def generator() -> ScaffoldGenerator:
    """Create a fresh ScaffoldGenerator instance."""
    return ScaffoldGenerator()


@pytest.fixture
def plugin_project(tmp_path, generator):
    """Scaffold a plugin-project and return the project directory."""
    project_dir = tmp_path / "my-plugin"
    generator.init_project("my-plugin", project_dir, template="plugin-project")
    return project_dir


class TestPluginProjectFileStructure:
    """Verify all expected files exist after init (R4-AC6)."""

    def test_pyproject_toml_exists(self, plugin_project):
        """pyproject.toml is created at project root."""
        assert (plugin_project / "pyproject.toml").exists()

    def test_readme_exists(self, plugin_project):
        """README.md is created at project root (R5-AC2)."""
        assert (plugin_project / "README.md").exists()

    def test_package_init_exists(self, plugin_project):
        """src/<package>/__init__.py is created."""
        assert (plugin_project / "src" / "my_plugin" / "__init__.py").exists()

    def test_plugin_py_exists(self, plugin_project):
        """src/<package>/plugin.py is created."""
        assert (plugin_project / "src" / "my_plugin" / "plugin.py").exists()

    def test_renderer_py_exists(self, plugin_project):
        """src/<package>/renderer.py is created."""
        assert (plugin_project / "src" / "my_plugin" / "renderer.py").exists()

    def test_provider_py_exists(self, plugin_project):
        """src/<package>/provider.py is created."""
        assert (plugin_project / "src" / "my_plugin" / "provider.py").exists()

    def test_all_expected_files_present(self, plugin_project):
        """All required files from R4-AC6 are present."""
        expected = [
            "pyproject.toml",
            "README.md",
            "src/my_plugin/__init__.py",
            "src/my_plugin/plugin.py",
            "src/my_plugin/renderer.py",
            "src/my_plugin/provider.py",
        ]
        for path in expected:
            assert (plugin_project / path).exists(), f"Missing: {path}"

    def test_no_main_py(self, plugin_project):
        """Plugin project does NOT have a main.py (not an app project)."""
        assert not (plugin_project / "src" / "my_plugin" / "main.py").exists()

    def test_no_jobs_directory(self, plugin_project):
        """Plugin project does NOT have a jobs/ directory (not an app project)."""
        assert not (plugin_project / "src" / "my_plugin" / "jobs").exists()


class TestPluginProjectPythonValidity:
    """Verify generated Python files are syntactically valid."""

    def test_init_py_parses(self, plugin_project):
        """__init__.py is valid Python."""
        source = (plugin_project / "src" / "my_plugin" / "__init__.py").read_text()
        tree = ast.parse(source)
        assert tree is not None

    def test_plugin_py_parses(self, plugin_project):
        """plugin.py is valid Python."""
        source = (plugin_project / "src" / "my_plugin" / "plugin.py").read_text()
        tree = ast.parse(source)
        assert tree is not None

    def test_renderer_py_parses(self, plugin_project):
        """renderer.py is valid Python."""
        source = (plugin_project / "src" / "my_plugin" / "renderer.py").read_text()
        tree = ast.parse(source)
        assert tree is not None

    def test_provider_py_parses(self, plugin_project):
        """provider.py is valid Python."""
        source = (plugin_project / "src" / "my_plugin" / "provider.py").read_text()
        tree = ast.parse(source)
        assert tree is not None


class TestPluginProjectTomlValidity:
    """Verify generated TOML files parse correctly."""

    def test_pyproject_toml_parses(self, plugin_project):
        """pyproject.toml is valid TOML."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

        content = (plugin_project / "pyproject.toml").read_text()
        data = tomllib.loads(content)
        assert "project" in data
        assert data["project"]["name"] == "my-plugin"

    def test_pyproject_toml_has_build_system(self, plugin_project):
        """pyproject.toml declares a valid build system."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

        content = (plugin_project / "pyproject.toml").read_text()
        data = tomllib.loads(content)
        assert "build-system" in data
        assert "hatchling" in data["build-system"]["requires"]

    def test_pyproject_toml_has_entry_points(self, plugin_project):
        """pyproject.toml has functualize.plugins entry-point group (R5-AC5)."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

        content = (plugin_project / "pyproject.toml").read_text()
        data = tomllib.loads(content)
        entry_points = data.get("project", {}).get("entry-points", {})
        assert "functualize.plugins" in entry_points

    def test_entry_points_has_renderer(self, plugin_project):
        """Entry points configure the renderer plugin."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

        content = (plugin_project / "pyproject.toml").read_text()
        data = tomllib.loads(content)
        plugins = data["project"]["entry-points"]["functualize.plugins"]
        assert "my_plugin-renderer" in plugins

    def test_entry_points_has_provider(self, plugin_project):
        """Entry points configure the provider plugin."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

        content = (plugin_project / "pyproject.toml").read_text()
        data = tomllib.loads(content)
        plugins = data["project"]["entry-points"]["functualize.plugins"]
        assert "my_plugin-provider" in plugins

    def test_functualize_dependency(self, plugin_project):
        """pyproject.toml lists functualize as a dependency."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

        content = (plugin_project / "pyproject.toml").read_text()
        data = tomllib.loads(content)
        deps = data["project"]["dependencies"]
        assert any("functualize" in d for d in deps)


class TestPluginProjectContent:
    """Verify template content meets requirements (R4-AC6, R5-AC2)."""

    def test_renderer_has_render_method(self, plugin_project):
        """renderer.py has a class with a render() method (R4-AC6)."""
        source = (plugin_project / "src" / "my_plugin" / "renderer.py").read_text()
        tree = ast.parse(source)
        classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        assert len(classes) >= 1
        # Find render method in the class
        renderer_class = classes[0]
        methods = [
            node
            for node in ast.walk(renderer_class)
            if isinstance(node, ast.FunctionDef) and node.name == "render"
        ]
        assert len(methods) == 1

    def test_provider_has_provide_method(self, plugin_project):
        """provider.py has a class with a provide() method (R4-AC6)."""
        source = (plugin_project / "src" / "my_plugin" / "provider.py").read_text()
        tree = ast.parse(source)
        classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        assert len(classes) >= 1
        # Find provide method in the class
        provider_class = classes[0]
        methods = [
            node
            for node in ast.walk(provider_class)
            if isinstance(node, ast.FunctionDef) and node.name == "provide"
        ]
        assert len(methods) == 1

    def test_renderer_class_name(self, plugin_project):
        """Renderer class is named with PascalCase + 'Renderer'."""
        source = (plugin_project / "src" / "my_plugin" / "renderer.py").read_text()
        assert "MyPluginRenderer" in source

    def test_provider_class_name(self, plugin_project):
        """Provider class is named with PascalCase + 'Provider'."""
        source = (plugin_project / "src" / "my_plugin" / "provider.py").read_text()
        assert "MyPluginProvider" in source

    def test_readme_has_configuration_section(self, plugin_project):
        """README.md has a Configuration section (R5-AC2)."""
        content = (plugin_project / "README.md").read_text()
        assert "## Configuration" in content

    def test_readme_has_usage_section(self, plugin_project):
        """README.md has a Usage section (R5-AC2)."""
        content = (plugin_project / "README.md").read_text()
        assert "## Usage" in content

    def test_readme_has_extension_points_section(self, plugin_project):
        """README.md has an Extension Points section (R5-AC2)."""
        content = (plugin_project / "README.md").read_text()
        assert "## Extension Points" in content

    def test_init_has_version(self, plugin_project):
        """__init__.py has a __version__ attribute."""
        source = (plugin_project / "src" / "my_plugin" / "__init__.py").read_text()
        assert "__version__" in source


class TestPluginProjectWithHyphenatedName:
    """Verify template handles project names with hyphens correctly."""

    def test_hyphenated_name_creates_underscore_package(self, tmp_path, generator):
        """Hyphens in project name become underscores in package name."""
        project_dir = tmp_path / "my-cool-plugin"
        generator.init_project("my-cool-plugin", project_dir, template="plugin-project")

        assert (project_dir / "src" / "my_cool_plugin" / "__init__.py").exists()
        assert (project_dir / "src" / "my_cool_plugin" / "plugin.py").exists()
        assert (project_dir / "src" / "my_cool_plugin" / "renderer.py").exists()
        assert (project_dir / "src" / "my_cool_plugin" / "provider.py").exists()

    def test_pyproject_preserves_hyphenated_name(self, tmp_path, generator):
        """pyproject.toml uses the original hyphenated project name."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

        project_dir = tmp_path / "my-cool-plugin"
        generator.init_project("my-cool-plugin", project_dir, template="plugin-project")

        content = (project_dir / "pyproject.toml").read_text()
        data = tomllib.loads(content)
        assert data["project"]["name"] == "my-cool-plugin"

    def test_no_main_py_with_hyphenated_name(self, tmp_path, generator):
        """Plugin project with hyphenated name still has no main.py."""
        project_dir = tmp_path / "my-cool-plugin"
        generator.init_project("my-cool-plugin", project_dir, template="plugin-project")

        assert not (project_dir / "src" / "my_cool_plugin" / "main.py").exists()

    def test_no_jobs_directory_with_hyphenated_name(self, tmp_path, generator):
        """Plugin project with hyphenated name still has no jobs/ directory."""
        project_dir = tmp_path / "my-cool-plugin"
        generator.init_project("my-cool-plugin", project_dir, template="plugin-project")

        assert not (project_dir / "src" / "my_cool_plugin" / "jobs").exists()
