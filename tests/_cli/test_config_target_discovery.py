# Feature: tui-architecture-v2, Property 15: Config target deduplication and ordering
"""Property-based tests for config target discovery.

Tests discover_config_targets from functualize._cli.tui.config_target_discovery:
- Property 15: Config target deduplication and ordering

**Validates: Requirements 9.6, 9.8**
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.tui.config_target_discovery import discover_config_targets

# =============================================================================
# Strategies
# =============================================================================

# Job names: alphanumeric + dots + hyphens (qualified job names)
_job_name_strategy = st.from_regex(r"[a-z][a-z0-9\.\-]{0,20}", fullmatch=True)

# Field names: alphanumeric + underscores
_field_name_strategy = st.from_regex(r"[a-z][a-z0-9_]{0,15}", fullmatch=True)


# =============================================================================
# Property 15: Config target deduplication and ordering
# =============================================================================


@pytest.mark.slow
class TestConfigTargetDeduplicationAndOrdering:
    """Property 15: Config target deduplication and ordering.

    For any set of discovered config file paths (some possibly symlinks to
    the same target), the target selector should contain no duplicate entries
    (by resolved absolute path), and entries should appear in fixed order:
    project files nearest-to-CWD to farthest, then user-level config, then
    environment variable. There is no "session" target.

    **Validates: Requirements 9.6, 9.8**
    """

    @given(job_name=_job_name_strategy, field_name=_field_name_strategy)
    def test_no_session_target_and_file_or_env_first(
        self, job_name: str, field_name: str
    ) -> None:
        """No entry is type='session'; the first entry is a file (or env).

        Under the SmartBar-as-CLI model the discovery no longer offers a
        "This session only" target. The ordered result is
        project/user files first, then the env var.
        """
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            targets = discover_config_targets(
                job_name=job_name,
                field_name=field_name,
                cwd=cwd,
            )

            assert len(targets) >= 1
            assert all(t.type != "session" for t in targets)
            assert targets[0].type in ("file", "env")

    @given(job_name=_job_name_strategy, field_name=_field_name_strategy)
    def test_env_always_last(self, job_name: str, field_name: str) -> None:
        """Last entry is always type='env' (Req 9.8)."""
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            targets = discover_config_targets(
                job_name=job_name,
                field_name=field_name,
                cwd=cwd,
            )

            assert len(targets) >= 2
            assert targets[-1].type == "env"

    @given(job_name=_job_name_strategy, field_name=_field_name_strategy)
    def test_ordering_invariant(self, job_name: str, field_name: str) -> None:
        """Entries follow fixed ordering: file(s) → env (Req 9.8).

        Project and user-level config files (type='file') come first, then the
        environment variable (type='env') last. There is no "session" entry.
        """
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            targets = discover_config_targets(
                job_name=job_name,
                field_name=field_name,
                cwd=cwd,
            )

            # Build the type sequence
            types = [t.type for t in targets]

            # Last must be env
            assert types[-1] == "env"

            # Everything before the env entry should be 'file' type
            for entry_type in types[:-1]:
                assert entry_type == "file", (
                    f"Expected only 'file' types before env, got: {types}"
                )

    @given(job_name=_job_name_strategy, field_name=_field_name_strategy)
    def test_no_duplicate_resolved_paths(self, job_name: str, field_name: str) -> None:
        """No two file targets have the same resolved path (Req 9.6)."""
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            targets = discover_config_targets(
                job_name=job_name,
                field_name=field_name,
                cwd=cwd,
            )

            # Collect all resolved paths from file-type targets
            resolved_paths: list[Path] = []
            for target in targets:
                if target.type == "file" and target.path is not None:
                    resolved_paths.append(target.path)

            # Verify no duplicates
            assert len(resolved_paths) == len(set(resolved_paths)), (
                f"Duplicate resolved paths found: {resolved_paths}"
            )

    def test_symlink_deduplication(self, tmp_path: Path) -> None:
        """Symlinks to the same file produce only one entry (Req 9.6).

        Unit example: create a .functualize.toml and a symlink to it in a
        subdirectory. The discovery should not list both.
        """
        # Create a .functualize.toml in the parent directory
        config_file = tmp_path / ".functualize.toml"
        config_file.write_text("[tool]\n")

        # Create a subdirectory with a symlink to the same file
        subdir = tmp_path / "sub"
        subdir.mkdir()
        symlink = subdir / ".functualize.toml"
        symlink.symlink_to(config_file)

        # Discover from the subdirectory
        targets = discover_config_targets(
            job_name="test.job",
            field_name="field",
            cwd=subdir,
        )

        # Count file targets pointing to our config_file
        config_targets = [
            t for t in targets if t.type == "file" and t.path == config_file.resolve()
        ]

        # Only one entry for the resolved path (deduplication)
        assert len(config_targets) == 1, (
            f"Expected 1 target for {config_file.resolve()}, "
            f"got {len(config_targets)}: {config_targets}"
        )

    def test_nearest_to_farthest_ordering(self, tmp_path: Path) -> None:
        """Project files are ordered nearest-to-CWD to farthest (Req 9.8).

        Unit example: place .functualize.toml in both parent and grandparent
        directories. The nearest one should appear first.
        """
        # Create directory structure: grandparent/parent/child
        grandparent = tmp_path / "gp"
        grandparent.mkdir()
        parent = grandparent / "parent"
        parent.mkdir()
        child = parent / "child"
        child.mkdir()

        # Place .functualize.toml at both grandparent and parent levels
        gp_config = grandparent / ".functualize.toml"
        gp_config.write_text("[tool]\n")
        parent_config = parent / ".functualize.toml"
        parent_config.write_text("[tool]\n")

        # Discover from the child directory
        targets = discover_config_targets(
            job_name="test.job",
            field_name="field",
            cwd=child,
        )

        # Extract file targets (excluding user-level config)
        file_targets = [
            t
            for t in targets
            if t.type == "file"
            and t.path is not None
            and "config/functualize" not in str(t.path)
        ]

        # Parent config should come before grandparent config
        if len(file_targets) >= 2:
            parent_idx = next(
                (
                    i
                    for i, t in enumerate(file_targets)
                    if t.path == parent_config.resolve()
                ),
                None,
            )
            gp_idx = next(
                (
                    i
                    for i, t in enumerate(file_targets)
                    if t.path == gp_config.resolve()
                ),
                None,
            )

            assert parent_idx is not None and gp_idx is not None, (
                f"Expected both configs in targets, got: {file_targets}"
            )
            assert parent_idx < gp_idx, (
                f"Nearest config (parent) should come before farthest (grandparent): "
                f"parent_idx={parent_idx}, gp_idx={gp_idx}"
            )

    def test_non_writable_files_omitted(self, tmp_path: Path) -> None:
        """Non-writable config files are omitted from results (Req 9.7).

        Unit example: create a read-only .functualize.toml — it should
        not appear in the target list.
        """
        # Create a non-writable .functualize.toml
        config_file = tmp_path / ".functualize.toml"
        config_file.write_text("[tool]\n")
        os.chmod(config_file, 0o444)

        try:
            targets = discover_config_targets(
                job_name="test.job",
                field_name="field",
                cwd=tmp_path,
            )

            # The non-writable file should NOT appear
            file_paths = [
                t.path for t in targets if t.type == "file" and t.path is not None
            ]
            assert config_file.resolve() not in file_paths, (
                f"Non-writable file should be omitted: {file_paths}"
            )
        finally:
            # Restore permissions for cleanup
            os.chmod(config_file, 0o644)

    def test_pyproject_with_tool_functualize_included(self, tmp_path: Path) -> None:
        """pyproject.toml with [tool.functualize] section is discovered (Req 9.3)."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[project]\nname = 'test'\n\n[tool.functualize]\nkey = 'value'\n"
        )

        targets = discover_config_targets(
            job_name="test.job",
            field_name="field",
            cwd=tmp_path,
        )

        file_targets = [
            t
            for t in targets
            if t.type == "file" and t.path is not None and t.path == pyproject.resolve()
        ]
        assert len(file_targets) == 1, (
            f"Expected pyproject.toml in targets, got file targets: "
            f"{[t for t in targets if t.type == 'file']}"
        )

    def test_pyproject_without_tool_functualize_excluded(self, tmp_path: Path) -> None:
        """pyproject.toml without [tool.functualize] section is NOT discovered."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[project]\nname = 'test'\n\n[tool.other]\nkey = 'val'\n")

        targets = discover_config_targets(
            job_name="test.job",
            field_name="field",
            cwd=tmp_path,
        )

        file_targets = [
            t
            for t in targets
            if t.type == "file" and t.path is not None and t.path == pyproject.resolve()
        ]
        assert len(file_targets) == 0, (
            "pyproject.toml without [tool.functualize] should not be in targets"
        )

    def test_env_var_name_formatting(self, tmp_path: Path) -> None:
        """Env var label uses uppercase with dots/hyphens as underscores (Req 9.5)."""
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            targets = discover_config_targets(
                job_name="infra.deploy-prod",
                field_name="target-region",
                cwd=cwd,
            )

            env_target = targets[-1]
            assert env_target.type == "env"
            assert env_target.label == "INFRA_DEPLOY_PROD_TARGET_REGION"
