"""Tests for shared config layer templates.


Tests that init_project() renders config.base.toml, config.dev.toml, and
config.prod.toml for templates with has_config_layers=True, that all three
are valid TOML, and that log_level has distinct values across the three files.
"""

import pytest

from functualize._cli.scaffold.generator import ScaffoldGenerator

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


@pytest.fixture
def generator() -> ScaffoldGenerator:
    """Create a fresh ScaffoldGenerator instance."""
    return ScaffoldGenerator()


class TestSimpleTemplateConfigLayers:
    """Verify shared config layers are rendered for the simple template."""

    @pytest.fixture
    def project(self, tmp_path, generator):
        project_dir = tmp_path / "my-app"
        generator.init_project("my-app", project_dir, template="simple")
        return project_dir

    def test_config_base_toml_exists(self, project):
        """config.base.toml is created at project root."""
        assert (project / "config.base.toml").exists()

    def test_config_dev_toml_exists(self, project):
        """config.dev.toml is created at project root."""
        assert (project / "config.dev.toml").exists()

    def test_config_prod_toml_exists(self, project):
        """config.prod.toml is created at project root."""
        assert (project / "config.prod.toml").exists()

    def test_config_base_is_valid_toml(self, project):
        """config.base.toml parses as valid TOML."""
        content = (project / "config.base.toml").read_text()
        data = tomllib.loads(content)
        assert isinstance(data, dict)

    def test_config_dev_is_valid_toml(self, project):
        """config.dev.toml parses as valid TOML."""
        content = (project / "config.dev.toml").read_text()
        data = tomllib.loads(content)
        assert isinstance(data, dict)

    def test_config_prod_is_valid_toml(self, project):
        """config.prod.toml parses as valid TOML."""
        content = (project / "config.prod.toml").read_text()
        data = tomllib.loads(content)
        assert isinstance(data, dict)

    def test_log_level_distinct_across_layers(self, project):
        """log_level appears in all three configs with distinct values."""
        base = tomllib.loads((project / "config.base.toml").read_text())
        dev = tomllib.loads((project / "config.dev.toml").read_text())
        prod = tomllib.loads((project / "config.prod.toml").read_text())

        base_level = base["general"]["log_level"]
        dev_level = dev["general"]["log_level"]
        prod_level = prod["general"]["log_level"]

        # All three must be distinct
        levels = {base_level, dev_level, prod_level}
        assert len(levels) == 3, (
            f"log_level must be distinct across layers, got: "
            f"base={base_level}, dev={dev_level}, prod={prod_level}"
        )


class TestFullInteractivityTemplateConfigLayers:
    """Verify shared config layers are rendered for the full-interactivity template."""

    @pytest.fixture
    def project(self, tmp_path, generator):
        project_dir = tmp_path / "my-app"
        generator.init_project("my-app", project_dir, template="full-interactivity")
        return project_dir

    def test_config_base_toml_exists(self, project):
        """config.base.toml is created at project root."""
        assert (project / "config.base.toml").exists()

    def test_config_dev_toml_exists(self, project):
        """config.dev.toml is created at project root."""
        assert (project / "config.dev.toml").exists()

    def test_config_prod_toml_exists(self, project):
        """config.prod.toml is created at project root."""
        assert (project / "config.prod.toml").exists()

    def test_all_configs_valid_toml(self, project):
        """All three config files are valid TOML."""
        for name in ("config.base.toml", "config.dev.toml", "config.prod.toml"):
            content = (project / name).read_text()
            data = tomllib.loads(content)
            assert isinstance(data, dict), f"{name} did not parse as TOML dict"


class TestPluginProjectTemplateConfigLayers:
    """Verify shared config layers are rendered for the plugin-project template."""

    @pytest.fixture
    def project(self, tmp_path, generator):
        project_dir = tmp_path / "my-plugin"
        generator.init_project("my-plugin", project_dir, template="plugin-project")
        return project_dir

    def test_config_base_toml_exists(self, project):
        """config.base.toml is created at project root."""
        assert (project / "config.base.toml").exists()

    def test_config_dev_toml_exists(self, project):
        """config.dev.toml is created at project root."""
        assert (project / "config.dev.toml").exists()

    def test_config_prod_toml_exists(self, project):
        """config.prod.toml is created at project root."""
        assert (project / "config.prod.toml").exists()

    def test_all_configs_valid_toml(self, project):
        """All three config files are valid TOML."""
        for name in ("config.base.toml", "config.dev.toml", "config.prod.toml"):
            content = (project / name).read_text()
            data = tomllib.loads(content)
            assert isinstance(data, dict), f"{name} did not parse as TOML dict"


class TestJobFolderTemplateConfigLayers:
    """Verify job-folder template keeps its own config.base.toml but gets dev/prod from _shared."""

    @pytest.fixture
    def project(self, tmp_path, generator):
        project_dir = tmp_path / "my-jobs"
        generator.init_project("my-jobs", project_dir, template="job-folder")
        return project_dir

    def test_config_base_toml_exists(self, project):
        """config.base.toml exists (from the job-folder template's own file)."""
        assert (project / "config.base.toml").exists()

    def test_config_dev_toml_exists(self, project):
        """config.dev.toml is created from _shared."""
        assert (project / "config.dev.toml").exists()

    def test_config_prod_toml_exists(self, project):
        """config.prod.toml is created from _shared."""
        assert (project / "config.prod.toml").exists()

    def test_config_base_is_template_specific(self, project):
        """config.base.toml uses the job-folder's own version (has [plugins] section)."""
        content = (project / "config.base.toml").read_text()
        data = tomllib.loads(content)
        # The job-folder specific config has a [plugins] section
        assert "plugins" in data

    def test_config_dev_is_valid_toml(self, project):
        """config.dev.toml is valid TOML."""
        content = (project / "config.dev.toml").read_text()
        data = tomllib.loads(content)
        assert isinstance(data, dict)

    def test_config_prod_is_valid_toml(self, project):
        """config.prod.toml is valid TOML."""
        content = (project / "config.prod.toml").read_text()
        data = tomllib.loads(content)
        assert isinstance(data, dict)


class TestConfigLayerLogLevelDistinctness:
    """Verify log_level has distinct values across all three config layers."""

    @pytest.fixture(params=["simple", "full-interactivity", "plugin-project"])
    def project(self, tmp_path, generator, request):
        project_dir = tmp_path / "test-proj"
        generator.init_project("test-proj", project_dir, template=request.param)
        return project_dir

    def test_log_level_in_all_three_files(self, project):
        """log_level key exists in all three config files."""
        for name in ("config.base.toml", "config.dev.toml", "config.prod.toml"):
            content = (project / name).read_text()
            data = tomllib.loads(content)
            assert "general" in data, f"{name} missing [general] section"
            assert "log_level" in data["general"], f"{name} missing log_level key"

    def test_log_level_values_are_distinct(self, project):
        """log_level values are distinct across base, dev, and prod."""
        base = tomllib.loads((project / "config.base.toml").read_text())
        dev = tomllib.loads((project / "config.dev.toml").read_text())
        prod = tomllib.loads((project / "config.prod.toml").read_text())

        levels = {
            base["general"]["log_level"],
            dev["general"]["log_level"],
            prod["general"]["log_level"],
        }
        assert len(levels) == 3
