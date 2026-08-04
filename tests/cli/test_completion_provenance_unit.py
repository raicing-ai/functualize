"""Unit tests for CompletionProvenance examples.

Tests specific classification examples, ProvenanceInfo dataclass fields,
and badge_style values for each source_type.

Requirements: 3.5, 3.7
"""

from __future__ import annotations

from dataclasses import fields
from unittest.mock import MagicMock

import pytest

from functualize._cli.completions.provenance import (
    CompletionProvenanceClassifier,
    ProvenanceInfo,
)
from functualize.types import JobDescriptor

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture()
def mock_app() -> MagicMock:
    """A minimal mock FunctualizeApp with no plugins or children."""
    app = MagicMock()
    app.get_jobs.return_value = []
    del app.plugin_loader
    app.child_projects = []
    return app


@pytest.fixture()
def classifier(mock_app: MagicMock) -> CompletionProvenanceClassifier:
    """Classifier with a simple mock app (no plugins, no children)."""
    return CompletionProvenanceClassifier(app=mock_app)


def _make_job(name: str, **kwargs) -> JobDescriptor:
    """Helper to create a minimal JobDescriptor."""
    defaults = {
        "group": None,
        "function": None,
        "source_file": "",
        "metadata": {},
    }
    defaults.update(kwargs)
    return JobDescriptor(name=name, **defaults)


# =============================================================================
# ProvenanceInfo dataclass structure
# =============================================================================


class TestProvenanceInfoDataclass:
    """Test ProvenanceInfo dataclass has correct fields."""

    def test_has_source_type_field(self) -> None:
        field_names = {f.name for f in fields(ProvenanceInfo)}
        assert "source_type" in field_names

    def test_has_display_label_field(self) -> None:
        field_names = {f.name for f in fields(ProvenanceInfo)}
        assert "display_label" in field_names

    def test_has_badge_style_field(self) -> None:
        field_names = {f.name for f in fields(ProvenanceInfo)}
        assert "badge_style" in field_names

    def test_exactly_three_fields(self) -> None:
        assert len(fields(ProvenanceInfo)) == 3

    def test_is_frozen(self) -> None:
        info = ProvenanceInfo(
            source_type="local", display_label="local", badge_style="bold"
        )
        with pytest.raises(AttributeError):
            info.source_type = "plugin"  # type: ignore[misc]


# =============================================================================
# Builtin classification
# =============================================================================


class TestBuiltinClassification:
    """Test each builtin name returns 'builtin' classification."""

    @pytest.mark.parametrize(
        "builtin_name",
        ["builtin"],
    )
    def test_builtin_name_classified_as_builtin(
        self, classifier: CompletionProvenanceClassifier, builtin_name: str
    ) -> None:
        job = _make_job(builtin_name)
        result = classifier.get_provenance(job)
        assert result.source_type == "builtin"

    @pytest.mark.parametrize(
        "builtin_name",
        ["builtin"],
    )
    def test_builtin_display_label(
        self, classifier: CompletionProvenanceClassifier, builtin_name: str
    ) -> None:
        job = _make_job(builtin_name)
        result = classifier.get_provenance(job)
        assert result.display_label == "built-in"

    @pytest.mark.parametrize(
        "builtin_name",
        ["builtin"],
    )
    def test_builtin_badge_style(
        self, classifier: CompletionProvenanceClassifier, builtin_name: str
    ) -> None:
        job = _make_job(builtin_name)
        result = classifier.get_provenance(job)
        assert result.badge_style == "dim cyan"

    def test_non_builtin_not_classified_as_builtin(
        self, classifier: CompletionProvenanceClassifier
    ) -> None:
        job = _make_job("deploy")
        result = classifier.get_provenance(job)
        assert result.source_type != "builtin"


# =============================================================================
# Badge style values for each source_type
# =============================================================================


class TestBadgeStyles:
    """Test badge_style values for each source_type."""

    def test_local_badge_style(
        self, classifier: CompletionProvenanceClassifier
    ) -> None:
        job = _make_job("my-local-job")
        result = classifier.get_provenance(job)
        assert result.source_type == "local"
        assert result.badge_style == "bold"

    def test_plugin_badge_style(self, mock_app: MagicMock) -> None:
        # Restore plugin_loader so the classifier can detect plugins
        mock_app.plugin_loader = MagicMock()
        mock_app.plugin_loader.loaded_plugins = {"my-plugin-job": "entry_point"}
        classifier = CompletionProvenanceClassifier(app=mock_app)

        job = _make_job("my-plugin-job")
        result = classifier.get_provenance(job)
        assert result.source_type == "plugin"
        assert result.badge_style == "bold magenta"

    def test_child_badge_style(self) -> None:
        # Create a fresh mock with child projects but no plugin_loader
        from types import SimpleNamespace

        app = MagicMock()
        app.get_jobs.return_value = []
        del app.plugin_loader
        app.child_projects = [SimpleNamespace(name="childapp")]
        classifier = CompletionProvenanceClassifier(app=app)

        job = _make_job(
            "some-job", group="childapp", metadata={"child_app": "childapp"}
        )
        result = classifier.get_provenance(job)
        assert result.source_type == "child"
        assert result.badge_style == "bold blue"

    def test_builtin_badge_style(
        self, classifier: CompletionProvenanceClassifier
    ) -> None:
        job = _make_job("builtin")
        result = classifier.get_provenance(job)
        assert result.source_type == "builtin"
        assert result.badge_style == "dim cyan"
