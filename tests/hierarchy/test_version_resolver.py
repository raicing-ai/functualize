"""Unit tests for VersionResolver.

Tests version resolution from pyproject.toml and importlib.metadata fallback,
covering the primary resolution paths and edge cases.

Requirements: 1.1, 1.2, 1.3, 1.6, 1.7
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from functualize._discovery.hierarchy import ResolvedVersion, VersionResolver

if TYPE_CHECKING:
    from pathlib import Path


class TestResolveWithPyprojectToml:
    """Test resolve() with a valid pyproject.toml containing functualize dependency."""

    def test_resolve_extracts_version_from_pyproject_gte_specifier(
        self, tmp_path: Path
    ):
        """resolve() extracts minimum version from >=X.Y.Z specifier in pyproject.toml.

        Validates: Requirement 1.1
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "my-child"\ndependencies = ["functualize>=0.2.0"]\n'
        )

        result = VersionResolver.resolve(tmp_path)

        assert result == ResolvedVersion(minimum=(0, 2, 0), raw_specifier=">=0.2.0")

    def test_resolve_extracts_version_from_pyproject_caret_specifier(
        self, tmp_path: Path
    ):
        """resolve() extracts minimum version from ^X.Y.Z (Poetry caret) specifier.

        Validates: Requirement 1.1
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "my-child"\ndependencies = ["functualize^0.3.1"]\n'
        )

        result = VersionResolver.resolve(tmp_path)

        assert result == ResolvedVersion(minimum=(0, 3, 1), raw_specifier="^0.3.1")

    def test_resolve_extracts_version_from_pyproject_eq_specifier(self, tmp_path: Path):
        """resolve() extracts minimum version from ==X.Y.Z specifier.

        Validates: Requirement 1.1
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "my-child"\ndependencies = ["functualize==1.2.3"]\n'
        )

        result = VersionResolver.resolve(tmp_path)

        assert result == ResolvedVersion(minimum=(1, 2, 3), raw_specifier="==1.2.3")

    def test_resolve_extracts_version_from_pyproject_compatible_release(
        self, tmp_path: Path
    ):
        """resolve() extracts minimum version from ~=X.Y.Z specifier.

        Validates: Requirement 1.1
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "my-child"\ndependencies = ["functualize~=0.2.0"]\n'
        )

        result = VersionResolver.resolve(tmp_path)

        assert result == ResolvedVersion(minimum=(0, 2, 0), raw_specifier="~=0.2.0")


class TestResolveFallbackToImportlibMetadata:
    """Test resolve() fallback to importlib.metadata when pyproject.toml is missing.

    Validates: Requirement 1.7
    """

    def test_resolve_falls_back_to_metadata_when_no_pyproject(self, tmp_path: Path):
        """resolve() uses importlib.metadata when pyproject.toml does not exist.

        Validates: Requirement 1.7
        """
        # tmp_path has no pyproject.toml
        with patch("importlib.metadata.version", return_value="0.1.0"):
            result = VersionResolver.resolve(tmp_path)

        assert result == ResolvedVersion(minimum=(0, 1, 0), raw_specifier=None)

    def test_resolve_falls_back_to_metadata_with_different_version(
        self, tmp_path: Path
    ):
        """resolve() correctly parses multi-digit version from metadata fallback.

        Validates: Requirement 1.7
        """
        with patch("importlib.metadata.version", return_value="2.10.3"):
            result = VersionResolver.resolve(tmp_path)

        assert result == ResolvedVersion(minimum=(2, 10, 3), raw_specifier=None)


class TestResolveFallbackNoDependency:
    """Test resolve() fallback when pyproject.toml has no functualize dependency.

    Validates: Requirement 1.2
    """

    def test_resolve_falls_back_when_no_functualize_in_dependencies(
        self, tmp_path: Path
    ):
        """resolve() falls back to metadata when functualize is not in dependencies.

        Validates: Requirement 1.2
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "my-child"\n'
            'dependencies = ["requests>=2.0.0", "click>=8.0"]\n'
        )

        with patch("importlib.metadata.version", return_value="0.1.0"):
            result = VersionResolver.resolve(tmp_path)

        assert result == ResolvedVersion(minimum=(0, 1, 0), raw_specifier=None)

    def test_resolve_falls_back_when_dependencies_list_empty(self, tmp_path: Path):
        """resolve() falls back to metadata when dependencies list is empty.

        Validates: Requirement 1.2
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "my-child"\ndependencies = []\n')

        with patch("importlib.metadata.version", return_value="1.0.0"):
            result = VersionResolver.resolve(tmp_path)

        assert result == ResolvedVersion(minimum=(1, 0, 0), raw_specifier=None)

    def test_resolve_falls_back_when_no_project_section(self, tmp_path: Path):
        """resolve() falls back to metadata when pyproject.toml has no [project] section.

        Validates: Requirement 1.2
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[build-system]\nrequires = ["hatchling"]\n')

        with patch("importlib.metadata.version", return_value="0.5.0"):
            result = VersionResolver.resolve(tmp_path)

        assert result == ResolvedVersion(minimum=(0, 5, 0), raw_specifier=None)


class TestResolveReturnsNone:
    """Test resolve() returns None when neither source has version info.

    Validates: Requirement 1.3
    """

    def test_resolve_returns_none_when_no_pyproject_and_package_not_found(
        self, tmp_path: Path
    ):
        """resolve() returns None minimum when no pyproject.toml and package not installed.

        Validates: Requirement 1.3
        """
        import importlib.metadata as im

        with patch(
            "importlib.metadata.version",
            side_effect=im.PackageNotFoundError("functualize"),
        ):
            result = VersionResolver.resolve(tmp_path)

        assert result == ResolvedVersion(minimum=None, raw_specifier=None)

    def test_resolve_returns_none_when_pyproject_has_no_functualize_and_package_not_found(
        self, tmp_path: Path
    ):
        """resolve() returns None when pyproject.toml exists but has no functualize dep
        and importlib.metadata also fails.

        Validates: Requirement 1.3
        """
        import importlib.metadata as im

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "other"\ndependencies = ["requests>=2.0"]\n'
        )

        with patch(
            "importlib.metadata.version",
            side_effect=im.PackageNotFoundError("functualize"),
        ):
            result = VersionResolver.resolve(tmp_path)

        assert result == ResolvedVersion(minimum=None, raw_specifier=None)

    def test_resolve_returns_none_when_bare_functualize_and_package_not_found(
        self, tmp_path: Path
    ):
        """resolve() returns None when functualize is listed without version constraint
        and importlib.metadata also fails.

        Validates: Requirement 1.3
        """
        import importlib.metadata as im

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "my-child"\ndependencies = ["functualize"]\n'
        )

        with patch(
            "importlib.metadata.version",
            side_effect=im.PackageNotFoundError("functualize"),
        ):
            result = VersionResolver.resolve(tmp_path)

        # Bare functualize has no specifier, so _extract_from_pyproject returns
        # (None, None) which triggers the fallback, and metadata also fails
        assert result.minimum is None


class TestResolveRunningVersion:
    """Test resolve_running_version() returns correct tuple from installed metadata.

    Validates: Requirement 1.6
    """

    def test_resolve_running_version_returns_tuple(self):
        """resolve_running_version() returns (major, minor, patch) from metadata.

        Validates: Requirement 1.6
        """
        with patch("importlib.metadata.version", return_value="0.1.0"):
            result = VersionResolver.resolve_running_version()

        assert result == (0, 1, 0)

    def test_resolve_running_version_with_higher_version(self):
        """resolve_running_version() correctly parses multi-digit versions.

        Validates: Requirement 1.6
        """
        with patch("importlib.metadata.version", return_value="3.12.7"):
            result = VersionResolver.resolve_running_version()

        assert result == (3, 12, 7)

    def test_resolve_running_version_returns_none_when_not_installed(self):
        """resolve_running_version() returns None when functualize is not installed.

        Validates: Requirement 1.6
        """
        import importlib.metadata as im

        with patch(
            "importlib.metadata.version",
            side_effect=im.PackageNotFoundError("functualize"),
        ):
            result = VersionResolver.resolve_running_version()

        assert result is None

    def test_resolve_running_version_returns_none_on_value_error(self):
        """resolve_running_version() returns None when version string is unparseable.

        Validates: Requirement 1.6
        """
        with patch("importlib.metadata.version", return_value="invalid"):
            result = VersionResolver.resolve_running_version()

        # "invalid".split(".") gives ["invalid"], len < 3, so returns None
        assert result is None
