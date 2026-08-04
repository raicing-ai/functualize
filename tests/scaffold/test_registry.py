"""Tests for scaffold template registry.

Validates: Requirements R4-AC3, R4-AC9
"""

import pytest

from functualize._cli.scaffold.registry import (
    TEMPLATES,
    TemplateManifest,
    get_template,
    list_templates,
    validate_template_name,
)

EXPECTED_TEMPLATE_NAMES = [
    "full-interactivity",
    "job-folder",
    "plugin-project",
    "simple",
]


class TestTemplatesDict:
    """Test that TEMPLATES contains all required templates (R4-AC3)."""

    def test_contains_all_four_templates(self) -> None:
        """All four template names are present in the TEMPLATES dict."""
        assert set(TEMPLATES.keys()) == {
            "simple",
            "full-interactivity",
            "plugin-project",
            "job-folder",
        }

    def test_templates_count(self) -> None:
        """Exactly four templates are defined."""
        assert len(TEMPLATES) == 4

    def test_all_values_are_template_manifests(self) -> None:
        """Every value in TEMPLATES is a TemplateManifest instance."""
        for name, manifest in TEMPLATES.items():
            assert isinstance(manifest, TemplateManifest), (
                f"{name} is not a TemplateManifest"
            )


class TestTemplateManifestFields:
    """Test TemplateManifest dataclass fields."""

    def test_manifest_has_required_fields(self) -> None:
        """TemplateManifest has name, description, template_dir, dependencies, has_config_layers."""
        manifest = TemplateManifest(
            name="test",
            description="A test template",
            template_dir="test-dir",
        )
        assert manifest.name == "test"
        assert manifest.description == "A test template"
        assert manifest.template_dir == "test-dir"
        assert manifest.dependencies == []
        assert manifest.has_config_layers is True

    def test_manifest_with_dependencies(self) -> None:
        """TemplateManifest can be created with explicit dependencies."""
        manifest = TemplateManifest(
            name="test",
            description="desc",
            template_dir="dir",
            dependencies=["dep-a", "dep-b"],
        )
        assert manifest.dependencies == ["dep-a", "dep-b"]

    def test_manifest_with_has_config_layers_false(self) -> None:
        """TemplateManifest can override has_config_layers to False."""
        manifest = TemplateManifest(
            name="test",
            description="desc",
            template_dir="dir",
            has_config_layers=False,
        )
        assert manifest.has_config_layers is False

    def test_manifest_is_frozen(self) -> None:
        """TemplateManifest is immutable (frozen dataclass)."""
        manifest = TemplateManifest(name="x", description="y", template_dir="z")
        with pytest.raises(AttributeError):
            manifest.name = "changed"  # type: ignore[misc]

    def test_simple_template_manifest(self) -> None:
        """Simple template has correct field values."""
        t = TEMPLATES["simple"]
        assert t.name == "simple"
        assert t.template_dir == "simple"
        assert t.dependencies == []
        assert t.has_config_layers is True
        assert "job" in t.description.lower() or "minimal" in t.description.lower()

    def test_full_interactivity_template_manifest(self) -> None:
        """Full-interactivity template has dependencies declared."""
        t = TEMPLATES["full-interactivity"]
        assert t.name == "full-interactivity"
        assert t.template_dir == "full-interactivity"
        assert len(t.dependencies) > 0
        assert "functualize-inline" in t.dependencies
        assert "functualize-state-sqlite" in t.dependencies

    def test_plugin_project_template_manifest(self) -> None:
        """Plugin-project template has correct fields."""
        t = TEMPLATES["plugin-project"]
        assert t.name == "plugin-project"
        assert t.template_dir == "plugin-project"
        assert t.dependencies == []

    def test_job_folder_template_manifest(self) -> None:
        """Job-folder template has correct fields."""
        t = TEMPLATES["job-folder"]
        assert t.name == "job-folder"
        assert t.template_dir == "job-folder"
        assert t.dependencies == []


class TestGetTemplate:
    """Test get_template() function."""

    @pytest.mark.parametrize("name", EXPECTED_TEMPLATE_NAMES)
    def test_returns_manifest_for_valid_name(self, name: str) -> None:
        """get_template() returns the correct TemplateManifest for each valid name."""
        result = get_template(name)
        assert isinstance(result, TemplateManifest)
        assert result.name == name

    def test_raises_value_error_for_invalid_name(self) -> None:
        """get_template() raises ValueError for an unknown template name (R4-AC9)."""
        with pytest.raises(ValueError, match="Unknown template 'nonexistent'"):
            get_template("nonexistent")

    def test_error_message_lists_available_templates(self) -> None:
        """ValueError message lists all available template names (R4-AC9)."""
        with pytest.raises(ValueError) as exc_info:
            get_template("bad-name")
        msg = str(exc_info.value)
        for name in EXPECTED_TEMPLATE_NAMES:
            assert name in msg

    def test_raises_for_empty_string(self) -> None:
        """get_template() raises ValueError for empty string."""
        with pytest.raises(ValueError, match="Unknown template ''"):
            get_template("")


class TestListTemplates:
    """Test list_templates() function."""

    def test_returns_sorted_list(self) -> None:
        """list_templates() returns template names in sorted order."""
        result = list_templates()
        assert result == EXPECTED_TEMPLATE_NAMES

    def test_returns_list_type(self) -> None:
        """list_templates() returns a list, not another iterable."""
        result = list_templates()
        assert isinstance(result, list)

    def test_contains_all_templates(self) -> None:
        """list_templates() contains all four template names."""
        result = list_templates()
        assert len(result) == 4
        assert set(result) == set(EXPECTED_TEMPLATE_NAMES)


class TestValidateTemplateName:
    """Test validate_template_name() function."""

    @pytest.mark.parametrize("name", EXPECTED_TEMPLATE_NAMES)
    def test_returns_true_for_valid_names(self, name: str) -> None:
        """validate_template_name() returns True for each valid template name."""
        assert validate_template_name(name) is True

    @pytest.mark.parametrize(
        "name",
        ["nonexistent", "", "Simple", "SIMPLE", "job_folder", "plugin project"],
    )
    def test_returns_false_for_invalid_names(self, name: str) -> None:
        """validate_template_name() returns False for invalid template names."""
        assert validate_template_name(name) is False
