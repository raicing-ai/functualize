"""Bug condition exploration test for auto_discover upward-walk discovery.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.6**

This test is EXPECTED TO FAIL on unfixed code — failure confirms the bug exists.
It encodes the expected behavior: auto_discover should perform upward-walk,
convention directory detection, nested candidate resolution, and multi-level
config merging. Currently it only checks the immediate CWD.

DO NOT fix the test or the code when it fails.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from functualize.app.utils import auto_discover

# =============================================================================
# Strategies
# =============================================================================

# Strategy for tree depth (1-4 levels of nesting below a root)
tree_depth_st = st.integers(min_value=1, max_value=4)

# Strategy for config placement: True = ancestor (not CWD), False = CWD
config_in_ancestor_st = st.booleans()

# Strategy for convention directory presence
has_convention_dir_st = st.booleans()


# =============================================================================
# Helpers
# =============================================================================


def _build_nested_path(root: Path, depth: int) -> Path:
    """Build a nested directory path: root/child_0/child_1/.../child_{depth-1}."""
    current = root
    for i in range(depth):
        current = current / f"child_{i}"
    current.mkdir(parents=True, exist_ok=True)
    return current


# =============================================================================
# Bug Condition Test Cases (Concrete Scenarios)
# =============================================================================


class TestAncestorConfigMissing:
    """Requirement 1.1: auto_discover misses config in ancestor directories."""

    def test_ancestor_config_not_found_by_auto_discover(self, tmp_path: Path) -> None:
        """CWD is a child directory; config is at the parent.

        Current behavior: auto_discover only checks CWD, returns empty.
        Expected behavior: walks up, finds config, resolves directories.
        """
        # Setup: config at root, CWD at root/child/
        root = tmp_path / "project"
        root.mkdir()
        child = root / "child"
        child.mkdir()

        # Config at root level with jobs_directories pointing to "jobs"
        jobs_dir = root / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / "deploy.py").write_text("def deploy(): pass\n")

        config = root / ".functualize.toml"
        config.write_text('jobs_directories = ["jobs"]\n')

        # Call auto_discover from child — should walk up and find config
        result = auto_discover(cwd=child)

        # Expected: result should contain the jobs directory resolved from root
        assert result.directories is not None, (
            "auto_discover(child_cwd) returns None when config exists at parent level"
        )
        assert str(jobs_dir.resolve()) in result.directories, (
            f"Expected {jobs_dir.resolve()} in result, got {result.directories}"
        )

    @settings(max_examples=20, deadline=None)
    @given(depth=tree_depth_st)
    def test_ancestor_config_at_variable_depth(self, depth: int) -> None:
        """Property: for any depth 1-4, config in ancestor is discovered.

        Bug condition: projectHasConfigInAncestor(cwd) = True
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / f"project_d{depth}"
            root.mkdir(parents=True, exist_ok=True)

            jobs_dir = root / "jobs"
            jobs_dir.mkdir(exist_ok=True)
            (jobs_dir / "task.py").write_text("def task(): pass\n")

            config = root / ".functualize.toml"
            config.write_text('jobs_directories = ["jobs"]\n')

            # CWD is at depth levels below root
            cwd = _build_nested_path(root, depth)

            result = auto_discover(cwd=cwd)

            # Expected: should find jobs_dir via upward walk
            assert result.directories is not None, (
                f"auto_discover at depth={depth} returns None when config at ancestor"
            )
            assert str(jobs_dir.resolve()) in result.directories, (
                f"depth={depth}: Expected {jobs_dir.resolve()} in {result.directories}"
            )


class TestConventionDirectoryMissing:
    """Requirement 1.2: auto_discover misses convention directories."""

    def test_convention_jobs_directory_not_detected(self, tmp_path: Path) -> None:
        """CWD has .functualize/jobs/ with job files — should be auto-included.

        Current behavior: ignores convention directory.
        Expected behavior: auto-includes .functualize/jobs/ in discovered paths.
        """
        project = tmp_path / "project"
        project.mkdir()

        # Convention directory: .functualize/jobs/ with a job file
        convention_jobs = project / ".functualize" / "jobs"
        convention_jobs.mkdir(parents=True)
        (convention_jobs / "deploy.py").write_text("def deploy(): pass\n")

        result = auto_discover(cwd=project)

        # Expected: convention_jobs should be in the result
        assert result.directories is not None, (
            "auto_discover returns None when .functualize/jobs/ convention dir exists"
        )
        assert str(convention_jobs.resolve()) in result.directories, (
            f"Expected convention dir {convention_jobs.resolve()} in {result.directories}"
        )

    def test_convention_lib_directory_not_detected(self, tmp_path: Path) -> None:
        """CWD has .functualize/lib/ — should be detected for import_libs.

        Current behavior: ignores convention directory entirely.
        Expected behavior: detects .functualize/lib/ and includes it.
        """
        project = tmp_path / "project"
        project.mkdir()

        # Convention directory: .functualize/lib/ with a library file
        convention_lib = project / ".functualize" / "lib"
        convention_lib.mkdir(parents=True)
        (convention_lib / "helpers.py").write_text("def helper(): pass\n")

        # We also need a config or convention jobs dir to trigger discovery
        convention_jobs = project / ".functualize" / "jobs"
        convention_jobs.mkdir(parents=True)
        (convention_jobs / "task.py").write_text("def task(): pass\n")

        result = auto_discover(cwd=project)

        # At minimum, the convention jobs directory should be found
        assert result.directories is not None, (
            "auto_discover returns None when .functualize/jobs/ and .functualize/lib/ exist"
        )
        assert str(convention_jobs.resolve()) in result.directories, (
            f"Expected {convention_jobs.resolve()} in {result.directories}"
        )


class TestNestedCandidateMissing:
    """Requirement 1.3: auto_discover misses .functualize/.functualize.toml candidate."""

    def test_nested_config_candidate_not_found(self, tmp_path: Path) -> None:
        """Project uses .functualize/.functualize.toml as config file.

        Current behavior: only checks pyproject.toml and .functualize.toml in CWD.
        Expected behavior: also checks .functualize/.functualize.toml candidate.
        """
        project = tmp_path / "project"
        project.mkdir()

        # Nested candidate: .functualize/.functualize.toml
        functualize_dir = project / ".functualize"
        functualize_dir.mkdir()

        jobs_dir = project / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / "build.py").write_text("def build(): pass\n")

        nested_config = functualize_dir / ".functualize.toml"
        nested_config.write_text('jobs_directories = ["jobs"]\n')

        result = auto_discover(cwd=project)

        # Expected: should find jobs_dir via nested candidate
        assert result.directories is not None, (
            "auto_discover returns None when .functualize/.functualize.toml exists"
        )
        assert str(jobs_dir.resolve()) in result.directories, (
            f"Expected {jobs_dir.resolve()} in {result.directories}"
        )


class TestMultiLevelMergeMissing:
    """Requirement 1.4: auto_discover doesn't merge configs from multiple levels."""

    def test_multi_level_config_not_merged(self, tmp_path: Path) -> None:
        """Configs at two ancestor levels with different jobs_directories.

        Current behavior: only finds config in CWD (first-found-wins per key).
        Expected behavior: merges both layers (nearest-first priority).
        """
        # Setup: root has shared-jobs, mid-level has local-jobs, CWD is deepest
        root = tmp_path / "root"
        root.mkdir()
        mid = root / "mid"
        mid.mkdir()
        child = mid / "child"
        child.mkdir()

        # Root config: extra shared jobs
        shared_jobs = root / "shared-jobs"
        shared_jobs.mkdir()
        (shared_jobs / "shared_task.py").write_text("def shared_task(): pass\n")

        root_config = root / ".functualize.toml"
        root_config.write_text('jobs_directories = ["shared-jobs"]\n')

        # Mid-level config: local jobs
        local_jobs = mid / "local-jobs"
        local_jobs.mkdir()
        (local_jobs / "local_task.py").write_text("def local_task(): pass\n")

        mid_config = mid / ".functualize.toml"
        mid_config.write_text('jobs_directories = ["local-jobs"]\n')

        # Call from deepest child
        result = auto_discover(cwd=child)

        # Expected: both directories should be found via multi-level merge
        assert result.directories is not None, (
            "auto_discover returns None when configs at multiple ancestor levels"
        )
        # At minimum, the nearest config's directories should be found
        assert str(local_jobs.resolve()) in result.directories, (
            f"Expected {local_jobs.resolve()} (nearest) in {result.directories}"
        )
        # After merge, the root config's directories should also be included
        assert str(shared_jobs.resolve()) in result.directories, (
            f"Expected {shared_jobs.resolve()} (root) in {result.directories}"
        )


class TestCLIDivergence:
    """Requirement 1.6: CLI uses same code path as auto_discover (divergence fixed)."""

    def test_cli_resolution_matches_auto_discover(self, tmp_path: Path) -> None:
        """Compare CLI resolution vs auto_discover for same CWD.

        Both resolve_project_config + resolve_effective_directories and
        auto_discover should find configs via upward walk identically.
        """
        from functualize.app.utils import (
            resolve_effective_directories,
            resolve_project_config,
        )

        # Setup: config at root, CWD at root/child
        root = tmp_path / "project"
        root.mkdir()
        child = root / "child"
        child.mkdir()

        jobs_dir = root / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / "deploy.py").write_text("def deploy(): pass\n")

        config = root / ".functualize.toml"
        config.write_text('jobs_directories = ["jobs"]\n')

        # CLI resolution (now uses same path as auto_discover)
        anchor, merged_config = resolve_project_config(child)
        effective = resolve_effective_directories(anchor, merged_config)
        cli_jobs_dirs = effective.get("jobs_directories", [])

        # auto_discover (unified behavior)
        result = auto_discover(cwd=child)
        auto_dirs = result.directories or []

        # Both should find jobs_dir
        assert str(jobs_dir.resolve()) in cli_jobs_dirs, (
            f"CLI should find {jobs_dir.resolve()}, got {cli_jobs_dirs}"
        )

        # auto_discover should produce the same result as the CLI pipeline
        assert str(jobs_dir.resolve()) in auto_dirs, (
            f"auto_discover diverges from CLI: CLI finds {cli_jobs_dirs}, "
            f"auto_discover finds {auto_dirs}"
        )


# =============================================================================
# Property-Based Test: Combined Bug Condition
# =============================================================================


class TestBugConditionProperty:
    """Property test combining all bug conditions with Hypothesis."""

    @settings(max_examples=30, deadline=None)
    @given(
        depth=st.integers(min_value=1, max_value=4),
        has_convention_jobs=st.booleans(),
        has_nested_candidate=st.booleans(),
    )
    def test_bug_condition_auto_discover_finds_expected_dirs(
        self,
        depth: int,
        has_convention_jobs: bool,
        has_nested_candidate: bool,
    ) -> None:
        """For all inputs satisfying bug condition, auto_discover returns expected dirs.

        **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.6**

        Bug condition: at least one of:
        - projectHasConfigInAncestor(cwd)
        - projectHasConventionDirectories(cwd)
        - projectHasNestedConfigCandidate(cwd)
        - projectHasMultiLevelConfigs(cwd)
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = (
                Path(tmp) / f"root_{depth}_{has_convention_jobs}_{has_nested_candidate}"
            )
            root.mkdir(parents=True, exist_ok=True)

            expected_dirs: list[Path] = []

            # Always create ancestor config (satisfies projectHasConfigInAncestor)
            jobs_dir = root / "jobs"
            jobs_dir.mkdir(exist_ok=True)
            (jobs_dir / "task.py").write_text("def task(): pass\n")

            config = root / ".functualize.toml"
            config.write_text('jobs_directories = ["jobs"]\n')
            expected_dirs.append(jobs_dir)

            # Optionally add convention directory
            if has_convention_jobs:
                convention_jobs = root / ".functualize" / "jobs"
                convention_jobs.mkdir(parents=True, exist_ok=True)
                (convention_jobs / "conv_task.py").write_text("def conv(): pass\n")
                expected_dirs.append(convention_jobs)

            # Optionally use nested candidate instead of root-level config
            if has_nested_candidate:
                functualize_dir = root / ".functualize"
                functualize_dir.mkdir(exist_ok=True)
                nested_config = functualize_dir / ".functualize.toml"
                nested_config.write_text('jobs_directories = ["jobs"]\n')
                # The nested candidate also points to jobs_dir (already in expected)

            # CWD is at depth levels below root
            cwd = _build_nested_path(root, depth)

            result = auto_discover(cwd=cwd)

            # Assert: auto_discover finds all expected directories
            assert result.directories is not None, (
                f"auto_discover returns None for depth={depth}, "
                f"convention={has_convention_jobs}, nested={has_nested_candidate}"
            )
            for expected in expected_dirs:
                assert str(expected.resolve()) in result.directories, (
                    f"Missing {expected.resolve()} in result {result.directories} "
                    f"(depth={depth}, convention={has_convention_jobs}, "
                    f"nested={has_nested_candidate})"
                )
