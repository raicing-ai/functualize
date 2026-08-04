"""Version resolution for functualize hierarchy validation.

Extracts and parses functualize version requirements from project metadata,
supporting PEP 440 specifiers and Poetry-style caret specifiers.
"""

from __future__ import annotations

import importlib.metadata
import logging
import re
import tomllib
from pathlib import Path
from typing import NamedTuple

try:
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version
except ImportError:  # pragma: no cover
    SpecifierSet = None  # type: ignore[assignment, misc]
    Version = None  # type: ignore[assignment, misc]

logger = logging.getLogger(__name__)


class ResolvedVersion(NamedTuple):
    """Result of version resolution.

    Attributes:
        minimum: The minimum required version (major, minor, patch), or None
            if unknown.
        raw_specifier: The original specifier string from pyproject.toml,
            or None.
    """

    minimum: tuple[int, int, int] | None
    raw_specifier: str | None


class VersionResolver:
    """Extracts functualize version requirements from project metadata."""

    FUNCTUALIZE_PATTERN = re.compile(
        r"functualize\s*([><=!~^][^\s,;]+(?:\s*,\s*[><=!~^][^\s,;]+)*)?",
    )
    CARET_PATTERN = re.compile(r"\^(\d+\.\d+\.\d+)")

    @classmethod
    def resolve(cls, project_path: Path) -> ResolvedVersion:
        """Resolve the functualize version requirement for a project.

        Tries pyproject.toml first, falls back to importlib.metadata.

        Args:
            project_path: Absolute path to the project root.

        Returns:
            ResolvedVersion with the minimum version or None if undetermined.
        """
        pyproject_path = project_path / "pyproject.toml"

        if pyproject_path.is_file():
            result = cls._extract_from_pyproject(pyproject_path)
            if result.minimum is not None or result.raw_specifier is not None:
                return result

        # Fallback to importlib.metadata
        try:
            version_str = importlib.metadata.version("functualize")
            parts = version_str.split(".")
            if len(parts) >= 3:
                version_tuple = (int(parts[0]), int(parts[1]), int(parts[2]))
                return ResolvedVersion(minimum=version_tuple, raw_specifier=None)
        except (importlib.metadata.PackageNotFoundError, ValueError):
            pass

        return ResolvedVersion(minimum=None, raw_specifier=None)

    @classmethod
    def resolve_running_version(cls) -> tuple[int, int, int] | None:
        """Resolve the currently running functualize version.

        Uses importlib.metadata to get the installed version.

        Returns:
            Tuple of (major, minor, patch) or None if not determinable.
        """
        try:
            version_str = importlib.metadata.version("functualize")
            parts = version_str.split(".")
            if len(parts) >= 3:
                return (int(parts[0]), int(parts[1]), int(parts[2]))
        except (importlib.metadata.PackageNotFoundError, ValueError):
            pass
        return None

    @classmethod
    def _extract_from_pyproject(cls, pyproject_path: Path) -> ResolvedVersion:
        """Parse pyproject.toml and extract functualize specifier.

        Searches the [project.dependencies] list for a functualize entry
        and extracts the version specifier.

        Args:
            pyproject_path: Path to the pyproject.toml file.

        Returns:
            ResolvedVersion with parsed version info.
        """
        try:
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError):
            logger.debug(f"Failed to parse pyproject.toml at {pyproject_path}")
            return ResolvedVersion(minimum=None, raw_specifier=None)

        dependencies: list[str] = data.get("project", {}).get("dependencies", [])

        for dep in dependencies:
            match = cls.FUNCTUALIZE_PATTERN.match(dep.strip())
            if match:
                specifier_str = match.group(1)
                if specifier_str is None:
                    # Bare "functualize" with no version constraint
                    return ResolvedVersion(minimum=None, raw_specifier=None)

                specifier_str = specifier_str.strip()
                minimum = cls._extract_minimum_version(specifier_str)
                return ResolvedVersion(minimum=minimum, raw_specifier=specifier_str)

        return ResolvedVersion(minimum=None, raw_specifier=None)

    @classmethod
    def _extract_minimum_version(
        cls, specifier_str: str
    ) -> tuple[int, int, int] | None:
        """Extract the lowest bounded version from a specifier string.

        Handles PEP 440 specifiers (>=, ==, ~=) and Poetry caret (^).
        Returns None for specifiers with no lower bound (!=, <, <=, bare).

        Args:
            specifier_str: The version specifier string (e.g., ">=0.1.0").

        Returns:
            Tuple of (major, minor, patch) or None if no lower bound.
        """
        # Handle Poetry caret specifier
        caret_match = cls.CARET_PATTERN.search(specifier_str)
        if caret_match:
            version_str = caret_match.group(1)
            parts = version_str.split(".")
            return (int(parts[0]), int(parts[1]), int(parts[2]))

        if SpecifierSet is None:  # pragma: no cover
            logger.debug("packaging library not available; cannot parse specifier")
            return None

        # Convert to PEP 440 specifier set and find lower bound
        try:
            spec_set = SpecifierSet(specifier_str)
        except Exception:
            logger.debug(f"Failed to parse specifier: {specifier_str}")
            return None

        # Find the lowest bounded version from the specifier set
        min_version: Version | None = None

        for spec in spec_set:
            op = spec.operator
            ver = spec.version

            if op in (">=", "==", "~="):
                parsed = Version(ver)
                if min_version is None or parsed < min_version:
                    min_version = parsed

        if min_version is None:
            return None

        # Extract major.minor.patch from the version
        major = min_version.major
        minor = min_version.minor
        micro = min_version.micro
        return (major, minor, micro)

    @classmethod
    def _convert_caret_to_pep440(cls, specifier_str: str) -> str:
        """Convert Poetry caret specifier (^X.Y.Z) to PEP 440 (>=X.Y.Z,<NEXT).

        The caret specifier ^X.Y.Z means >=X.Y.Z and <NEXT where NEXT is
        determined by the leftmost non-zero component:
        - ^1.2.3 -> >=1.2.3,<2.0.0
        - ^0.2.3 -> >=0.2.3,<0.3.0
        - ^0.0.3 -> >=0.0.3,<0.0.4

        Args:
            specifier_str: A caret specifier string (e.g., "^1.2.3").

        Returns:
            PEP 440 equivalent specifier string.
        """
        match = cls.CARET_PATTERN.match(specifier_str)
        if not match:
            return specifier_str

        version_str = match.group(1)
        parts = [int(p) for p in version_str.split(".")]
        major, minor, patch = parts[0], parts[1], parts[2]

        if major != 0:
            # ^X.Y.Z -> >=X.Y.Z,<(X+1).0.0
            upper = f"{major + 1}.0.0"
        elif minor != 0:
            # ^0.Y.Z -> >=0.Y.Z,<0.(Y+1).0
            upper = f"0.{minor + 1}.0"
        else:
            # ^0.0.Z -> >=0.0.Z,<0.0.(Z+1)
            upper = f"0.0.{patch + 1}"

        return f">={version_str},<{upper}"
