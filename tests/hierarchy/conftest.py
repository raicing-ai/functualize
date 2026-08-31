"""Shared pytest fixtures for hierarchy validation tests.

Provides reusable fixtures for creating temporary parent/child project
structures, pyproject.toml files with various functualize version specifiers,
and config files with strict_hierarchy_validation options.

Requirements: 1.1, 3.3, 4.5
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def parent_project(tmp_path: Path) -> Path:
    """Create a parent project directory with functualize dependency and config.

    Creates:
        - pyproject.toml with functualize>=0.2.0 dependency
        - src/parent_app/__init__.py
        - src/parent_app/jobs/ directory
        - config.base.toml with [general] and [children] sections

    Returns:
        Path to the parent project directory.
    """
    project_dir = tmp_path / "parent_project"
    project_dir.mkdir()

    # pyproject.toml with functualize dependency
    pyproject = project_dir / "pyproject.toml"
    pyproject.write_text(
        "[project]\n"
        'name = "parent-app"\n'
        'version = "1.0.0"\n'
        "dependencies = [\n"
        '    "functualize>=0.2.0",\n'
        '    "typer>=0.9.0",\n'
        "]\n"
    )

    # Source structure
    src_dir = project_dir / "src" / "parent_app"
    src_dir.mkdir(parents=True)
    (src_dir / "__init__.py").write_text('"""Parent application."""\n')
    jobs_dir = src_dir / "jobs"
    jobs_dir.mkdir()
    (jobs_dir / "__init__.py").write_text("")

    # Config with [general] and [children] sections
    config_file = project_dir / "config.base.toml"
    config_file.write_text(
        '[general]\napp_name = "parent_app"\n\n'
        '[children]\nchild_app = "../child_project"\n'
    )

    return project_dir


@pytest.fixture
def child_project(tmp_path: Path) -> Path:
    """Create a child project directory with functualize dependency.

    Creates:
        - pyproject.toml with functualize>=0.2.0 dependency
        - src/child_app/__init__.py
        - src/child_app/jobs/ directory

    Returns:
        Path to the child project directory.
    """
    project_dir = tmp_path / "child_project"
    project_dir.mkdir()

    # pyproject.toml with compatible functualize dependency
    pyproject = project_dir / "pyproject.toml"
    pyproject.write_text(
        "[project]\n"
        'name = "child-app"\n'
        'version = "0.1.0"\n'
        "dependencies = [\n"
        '    "functualize>=0.2.0",\n'
        "]\n"
    )

    # Source structure
    src_dir = project_dir / "src" / "child_app"
    src_dir.mkdir(parents=True)
    (src_dir / "__init__.py").write_text('"""Child application."""\n')
    jobs_dir = src_dir / "jobs"
    jobs_dir.mkdir()
    (jobs_dir / "__init__.py").write_text("")

    return project_dir


@pytest.fixture
def child_project_incompatible(tmp_path: Path) -> Path:
    """Create a child project with an older functualize version.

    Creates a child project whose functualize dependency (>=0.1.0) is
    older than the parent's running version, triggering version
    incompatibility warnings.

    Returns:
        Path to the incompatible child project directory.
    """
    project_dir = tmp_path / "child_incompatible"
    project_dir.mkdir()

    # pyproject.toml with older functualize version
    pyproject = project_dir / "pyproject.toml"
    pyproject.write_text(
        "[project]\n"
        'name = "child-incompatible"\n'
        'version = "0.1.0"\n'
        "dependencies = [\n"
        '    "functualize>=0.1.0",\n'
        "]\n"
    )

    # Source structure
    src_dir = project_dir / "src" / "child_incompatible"
    src_dir.mkdir(parents=True)
    (src_dir / "__init__.py").write_text('"""Incompatible child."""\n')
    jobs_dir = src_dir / "jobs"
    jobs_dir.mkdir()
    (jobs_dir / "__init__.py").write_text("")

    return project_dir


@pytest.fixture
def child_project_no_version(tmp_path: Path) -> Path:
    """Create a child project without functualize in dependencies.

    Creates a child project whose pyproject.toml does not list functualize
    as a dependency, resulting in unknown version resolution.

    Returns:
        Path to the child project directory without functualize dependency.
    """
    project_dir = tmp_path / "child_no_version"
    project_dir.mkdir()

    # pyproject.toml without functualize dependency
    pyproject = project_dir / "pyproject.toml"
    pyproject.write_text(
        "[project]\n"
        'name = "child-no-version"\n'
        'version = "0.1.0"\n'
        "dependencies = [\n"
        '    "requests>=2.0.0",\n'
        '    "click>=8.0.0",\n'
        "]\n"
    )

    # Source structure
    src_dir = project_dir / "src" / "child_no_version"
    src_dir.mkdir(parents=True)
    (src_dir / "__init__.py").write_text('"""Child without functualize."""\n')
    jobs_dir = src_dir / "jobs"
    jobs_dir.mkdir()
    (jobs_dir / "__init__.py").write_text("")

    return project_dir


@pytest.fixture
def strict_config(tmp_path: Path) -> Path:
    """Create a config directory with strict_hierarchy_validation = true.

    Creates a config.base.toml with the [general] section containing
    strict_hierarchy_validation = true.

    Returns:
        Path to the config directory.
    """
    config_dir = tmp_path / "strict_config"
    config_dir.mkdir()

    config_file = config_dir / "config.base.toml"
    config_file.write_text(
        "[general]\n"
        'app_name = "strict_app"\n'
        "strict_hierarchy_validation = true\n"
        "\n"
        "[children]\n"
        'child = "../child_project"\n'
    )

    return config_dir


@pytest.fixture
def non_strict_config(tmp_path: Path) -> Path:
    """Create a config directory without the strict_hierarchy_validation option.

    Creates a config.base.toml with a [general] section that does not
    include the strict_hierarchy_validation option, defaulting to
    non-strict mode.

    Returns:
        Path to the config directory.
    """
    config_dir = tmp_path / "non_strict_config"
    config_dir.mkdir()

    config_file = config_dir / "config.base.toml"
    config_file.write_text(
        '[general]\napp_name = "non_strict_app"\n\n'
        '[children]\nchild = "../child_project"\n'
    )

    return config_dir
