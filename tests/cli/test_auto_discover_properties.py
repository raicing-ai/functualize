"""Property-based tests for auto_discover().

# Feature: cli-simplification-and-robustness, Property 1: Config dirs in output
# Feature: cli-simplification-and-robustness, Property 2: Pre-filter qualification
"""

from __future__ import annotations

import keyword as _kw
import string
import tempfile
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize.app.utils import _SKIP_DIRECTORIES, auto_discover

# =============================================================================
# Property 1: Config directories always appear in auto_discover output
# =============================================================================


@pytest.mark.slow
class TestConfigDirsInOutput:
    """Property 1: Config directories always appear in auto_discover output.

    For any valid configuration state (pyproject.toml, .functualize.toml, or
    XDG global config) containing `jobs_directories` or `extra_directories`
    entries that reference existing directories, calling `auto_discover()`
    SHALL include all those directories in the returned
    `JobSources.directories`.

    **Validates: Requirements 1.1**
    """

    def test_pyproject_jobs_directories_appear_in_output(self, tmp_path: Path) -> None:
        """Directories declared in pyproject.toml [tool.functualize].jobs_directories
        appear in auto_discover output."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[tool.functualize]\njobs_directories = ["jobs"]\n',
            encoding="utf-8",
        )

        result = auto_discover(cwd=tmp_path, scan_depth=0)
        discovered = result.directories or []
        assert str(jobs_dir.resolve()) in discovered

    def test_pyproject_extra_directories_appear_in_output(self, tmp_path: Path) -> None:
        """Directories declared in pyproject.toml [tool.functualize].extra_directories
        appear in auto_discover output."""
        extra_dir = tmp_path / "extra"
        extra_dir.mkdir()

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[tool.functualize]\nextra_directories = ["extra"]\n',
            encoding="utf-8",
        )

        result = auto_discover(cwd=tmp_path, scan_depth=0)
        discovered = result.directories or []
        assert str(extra_dir.resolve()) in discovered

    def test_functualize_toml_jobs_directories_appear_in_output(
        self, tmp_path: Path
    ) -> None:
        """Directories declared in .functualize.toml jobs_directories
        appear in auto_discover output."""
        jobs_dir = tmp_path / "myjobs"
        jobs_dir.mkdir()

        toml_file = tmp_path / ".functualize.toml"
        toml_file.write_text(
            'jobs_directories = ["myjobs"]\n',
            encoding="utf-8",
        )

        result = auto_discover(cwd=tmp_path, scan_depth=0)
        discovered = result.directories or []
        assert str(jobs_dir.resolve()) in discovered

    def test_functualize_toml_extra_directories_appear_in_output(
        self, tmp_path: Path
    ) -> None:
        """Directories declared in .functualize.toml extra_directories
        appear in auto_discover output."""
        extra_dir = tmp_path / "extras"
        extra_dir.mkdir()

        toml_file = tmp_path / ".functualize.toml"
        toml_file.write_text(
            'extra_directories = ["extras"]\n',
            encoding="utf-8",
        )

        result = auto_discover(cwd=tmp_path, scan_depth=0)
        discovered = result.directories or []
        assert str(extra_dir.resolve()) in discovered

    def test_xdg_global_config_jobs_directories_appear_in_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Directories declared in XDG global config appear in auto_discover output."""
        jobs_dir = tmp_path / "global_jobs"
        jobs_dir.mkdir()

        xdg_config = tmp_path / "xdg_config"
        xdg_config.mkdir()
        functualize_config = xdg_config / "functualize"
        functualize_config.mkdir()
        config_file = functualize_config / "config.toml"
        config_file.write_text(
            f'jobs_directories = ["{jobs_dir.resolve()}"]\n',
            encoding="utf-8",
        )

        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_config))

        result = auto_discover(cwd=tmp_path, scan_depth=0)
        discovered = result.directories or []
        assert str(jobs_dir.resolve()) in discovered

    def test_nonexistent_config_dirs_silently_skipped(self, tmp_path: Path) -> None:
        """Non-existent directories in config are silently skipped."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[tool.functualize]\njobs_directories = ["nonexistent_dir"]\n',
            encoding="utf-8",
        )

        result = auto_discover(cwd=tmp_path, scan_depth=0)
        discovered = result.directories or []
        # Non-existent dir should not be in results
        assert not any("nonexistent_dir" in d for d in discovered)


# =============================================================================
# Strategies for Property 2
# =============================================================================

# Valid Python identifier characters for function names (no leading underscore for public)
_public_func_name_start = st.sampled_from("abcdefghijklmnopqrstuvwxyz")
_identifier_chars = st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789_")
_public_func_name = st.builds(
    lambda first, rest: first + rest,
    _public_func_name_start,
    st.text(_identifier_chars, min_size=1, max_size=15),
).filter(lambda name: not _kw.iskeyword(name) and name.isidentifier())

# Valid non-underscore-prefixed Python file stems
_valid_stem_start = st.sampled_from("abcdefghijklmnopqrstuvwxyz")
_valid_stem_chars = st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789_")
_non_underscore_stem = st.builds(
    lambda first, rest: first + rest,
    _valid_stem_start,
    st.text(_valid_stem_chars, min_size=0, max_size=10),
)

# Underscore-prefixed file stems (fail DefaultModulePreFilter)
_underscore_stem = st.builds(
    lambda rest: "_" + rest,
    st.text(_valid_stem_chars, min_size=1, max_size=10),
)


@st.composite
def qualifying_python_content(draw: st.DrawFn) -> str:
    """Generate Python file content that passes ASTModulePreFilter.

    Contains at least one public (non-underscore) top-level function definition.
    """
    func_name = draw(_public_func_name)
    # Optionally add some extra content before/after the function
    extra_lines = draw(
        st.lists(
            st.sampled_from(
                [
                    "import os",
                    "x = 42",
                    "# comment line",
                    "",
                    "JOB_GROUP = 'test'",
                ]
            ),
            min_size=0,
            max_size=3,
        )
    )
    use_async = draw(st.booleans())
    func_keyword = "async def" if use_async else "def"

    lines = extra_lines + [
        f"{func_keyword} {func_name}():",
        "    pass",
        "",
    ]
    return "\n".join(lines)


@st.composite
def non_qualifying_content_no_public_func(draw: st.DrawFn) -> str:
    """Generate Python content that fails ASTModulePreFilter.

    Contains no public top-level function definitions. May have:
    - Only private functions (underscore-prefixed)
    - Only class definitions
    - Only assignments
    - Empty module
    """
    variant = draw(
        st.sampled_from(["private_func", "class_only", "assignment_only", "empty"])
    )

    if variant == "private_func":
        name = "_" + draw(st.text(_valid_stem_chars, min_size=1, max_size=8))
        return f"def {name}():\n    pass\n"
    elif variant == "class_only":
        return "class MyClass:\n    def method(self):\n        pass\n"
    elif variant == "assignment_only":
        return "x = 42\ny = 'hello'\n"
    else:
        return "# empty module\n"


# Strategy for directory names (valid, non-dot-prefixed, not in skip set)
_safe_dir_name = st.text(
    st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789"),
    min_size=1,
    max_size=10,
).filter(lambda s: s[0].isalpha() and s not in _SKIP_DIRECTORIES)


# =============================================================================
# Property 2: Pre-filter scan discovers only qualifying directories
# =============================================================================


@pytest.mark.slow
class TestPreFilterQualification:
    """Property 2: Pre-filter scan discovers only qualifying directories.

    For any directory tree below CWD, `auto_discover()` SHALL include a
    directory in its scan results if and only if that directory contains at
    least one `.py` file that passes both `DefaultModulePreFilter`
    (non-underscore-prefixed filename) AND `ASTModulePreFilter` (contains
    at least one public top-level function definition).

    **Validates: Requirements 1.2, 8.1, 8.2, 8.3**
    """

    @given(
        dir_name=_safe_dir_name,
        file_stem=_non_underscore_stem,
        content=qualifying_python_content(),
    )
    def test_property_2_directory_with_qualifying_file_is_discovered(
        self,
        dir_name: str,
        file_stem: str,
        content: str,
    ) -> None:
        """A directory with a qualifying .py file IS included in scan results.

        A qualifying file has:
        - Non-underscore-prefixed filename (passes DefaultModulePreFilter)
        - At least one public top-level function (passes ASTModulePreFilter)

        **Validates: Requirements 1.2, 8.1, 8.2, 8.3**
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Create a subdirectory with a qualifying Python file
            sub_dir = tmp_path / dir_name
            sub_dir.mkdir(parents=True, exist_ok=True)
            py_file = sub_dir / f"{file_stem}.py"
            py_file.write_text(content, encoding="utf-8")

            result = auto_discover(cwd=tmp_path, scan_depth=1)

            discovered = result.directories or []
            resolved_sub_dir = str(sub_dir.resolve())

            assert resolved_sub_dir in discovered, (
                f"Directory with qualifying file should be discovered.\n"
                f"  dir: {resolved_sub_dir}\n"
                f"  file: {file_stem}.py\n"
                f"  discovered: {discovered}"
            )

    @given(
        dir_name=_safe_dir_name,
        file_stem=_underscore_stem,
        content=qualifying_python_content(),
    )
    def test_property_2_underscore_prefixed_file_does_not_qualify(
        self,
        dir_name: str,
        file_stem: str,
        content: str,
    ) -> None:
        """A directory with ONLY underscore-prefixed .py files is NOT discovered.

        DefaultModulePreFilter rejects files with underscore-prefixed names,
        so even if the content has public functions, the directory won't qualify.

        **Validates: Requirements 1.2, 8.1**
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sub_dir = tmp_path / dir_name
            sub_dir.mkdir(parents=True, exist_ok=True)
            py_file = sub_dir / f"{file_stem}.py"
            py_file.write_text(content, encoding="utf-8")

            result = auto_discover(cwd=tmp_path, scan_depth=1)

            discovered = result.directories or []
            resolved_sub_dir = str(sub_dir.resolve())

            assert resolved_sub_dir not in discovered, (
                f"Directory with only underscore-prefixed files should NOT be discovered.\n"
                f"  dir: {resolved_sub_dir}\n"
                f"  file: {file_stem}.py\n"
                f"  discovered: {discovered}"
            )

    @given(
        dir_name=_safe_dir_name,
        file_stem=_non_underscore_stem,
        content=non_qualifying_content_no_public_func(),
    )
    def test_property_2_no_public_function_does_not_qualify(
        self,
        dir_name: str,
        file_stem: str,
        content: str,
    ) -> None:
        """A directory with .py files lacking public functions is NOT discovered.

        ASTModulePreFilter requires at least one public (non-underscore) top-level
        function definition. Without it, the directory doesn't qualify.

        **Validates: Requirements 1.2, 8.2**
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sub_dir = tmp_path / dir_name
            sub_dir.mkdir(parents=True, exist_ok=True)
            py_file = sub_dir / f"{file_stem}.py"
            py_file.write_text(content, encoding="utf-8")

            result = auto_discover(cwd=tmp_path, scan_depth=1)

            discovered = result.directories or []
            resolved_sub_dir = str(sub_dir.resolve())

            assert resolved_sub_dir not in discovered, (
                f"Directory without public functions should NOT be discovered.\n"
                f"  dir: {resolved_sub_dir}\n"
                f"  file: {file_stem}.py\n"
                f"  content type: no public function\n"
                f"  discovered: {discovered}"
            )

    @given(
        dir_name=_safe_dir_name,
        qualifying_stem=_non_underscore_stem,
        non_qualifying_stem=_underscore_stem,
        qualifying_content=qualifying_python_content(),
        non_qualifying_content=non_qualifying_content_no_public_func(),
    )
    def test_property_2_one_qualifying_file_suffices(
        self,
        dir_name: str,
        qualifying_stem: str,
        non_qualifying_stem: str,
        qualifying_content: str,
        non_qualifying_content: str,
    ) -> None:
        """A directory qualifies if it has at least ONE qualifying file.

        Even if other files don't qualify (underscore-prefixed or no public
        functions), the directory is still included.

        **Validates: Requirements 1.2, 8.1, 8.2, 8.3**
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sub_dir = tmp_path / dir_name
            sub_dir.mkdir(parents=True, exist_ok=True)

            # One qualifying file
            good_file = sub_dir / f"{qualifying_stem}.py"
            good_file.write_text(qualifying_content, encoding="utf-8")

            # One non-qualifying file
            bad_file = sub_dir / f"{non_qualifying_stem}.py"
            bad_file.write_text(non_qualifying_content, encoding="utf-8")

            result = auto_discover(cwd=tmp_path, scan_depth=1)

            discovered = result.directories or []
            resolved_sub_dir = str(sub_dir.resolve())

            assert resolved_sub_dir in discovered, (
                f"Directory with at least one qualifying file should be discovered.\n"
                f"  dir: {resolved_sub_dir}\n"
                f"  qualifying file: {qualifying_stem}.py\n"
                f"  non-qualifying file: {non_qualifying_stem}.py\n"
                f"  discovered: {discovered}"
            )

    @given(
        dir_name=_safe_dir_name,
        file_stem=_non_underscore_stem,
        content=qualifying_python_content(),
    )
    def test_property_2_both_filters_required_via_allof(
        self,
        dir_name: str,
        file_stem: str,
        content: str,
    ) -> None:
        """Both DefaultModulePreFilter AND ASTModulePreFilter must pass (AllOf).

        This confirms the filters are composed with AllOf semantics - both
        conditions must hold simultaneously for a file to qualify.

        **Validates: Requirements 8.3**
        """
        import tempfile

        from functualize._primitives import (
            AllOf,
            ASTModulePreFilter,
            DefaultModulePreFilter,
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sub_dir = tmp_path / dir_name
            sub_dir.mkdir(parents=True, exist_ok=True)
            py_file = sub_dir / f"{file_stem}.py"
            py_file.write_text(content, encoding="utf-8")

            # Directly verify the AllOf composition behavior
            pre_filter = AllOf(DefaultModulePreFilter(), ASTModulePreFilter())
            file_qualifies = pre_filter.should_import(py_file)

            result = auto_discover(cwd=tmp_path, scan_depth=1)
            discovered = result.directories or []
            resolved_sub_dir = str(sub_dir.resolve())
            is_discovered = resolved_sub_dir in discovered

            # The directory should be discovered if and only if the file qualifies
            assert is_discovered == file_qualifies, (
                f"Discovery result should match AllOf filter result.\n"
                f"  file_qualifies (AllOf): {file_qualifies}\n"
                f"  is_discovered: {is_discovered}\n"
                f"  file: {file_stem}.py"
            )


# =============================================================================
# Strategies for Property 3: Merge/Dedup
# =============================================================================

# Strategy for generating qualifying Python file content (public function def)
_QUALIFYING_PY_CONTENT = '''\
def hello():
    """A public function."""
    return "hello"
'''

# Generate valid subdirectory names for the scan.
#
# Filtered against `_SKIP_DIRECTORIES`, the names discovery skips
# unconditionally (`build`, `dist`, `node_modules`, ...). Without this the
# strategy can generate one of them, and every property here that asserts "a
# directory with a qualifying file IS discovered" fails — correctly, since that
# directory is excluded by design. It is a latent flake: it fires only on the
# seed that happens to produce such a name.
_subdir_name_strategy = st.text(
    alphabet=string.ascii_lowercase,
    min_size=1,
    max_size=8,
).filter(lambda name: name not in _SKIP_DIRECTORIES)


def _make_qualifying_dir(parent: Path, name: str) -> Path:
    """Create a directory with a qualifying .py file inside it."""
    dir_path = parent / name
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "job.py").write_text(_QUALIFYING_PY_CONTENT, encoding="utf-8")
    return dir_path


def _write_pyproject_toml(
    cwd: Path, directories: list[str], key: str = "jobs_directories"
) -> None:
    """Write a pyproject.toml with functualize config listing directories."""
    dirs_str = ", ".join(f'"{d}"' for d in directories)
    content = f"[tool.functualize]\n{key} = [{dirs_str}]\n"
    (cwd / "pyproject.toml").write_text(content, encoding="utf-8")


# =============================================================================
# Property 3: Merge produces deduplicated union
# Feature: cli-simplification-and-robustness, Property 3: Merge/dedup
# =============================================================================


@pytest.mark.slow
class TestMergeProducesDedupUnion:
    """Property 3: Merge produces deduplicated union.

    For any set of config-declared directories and CWD-scan-discovered
    directories, the output SHALL be the set union of both sources with
    no duplicate path entries.

    **Validates: Requirements 1.3**
    """

    @given(
        config_dirs=st.lists(
            _subdir_name_strategy,
            min_size=1,
            max_size=4,
            unique=True,
        ),
        scan_dirs=st.lists(
            _subdir_name_strategy,
            min_size=1,
            max_size=4,
            unique=True,
        ),
    )
    def test_output_is_union_of_config_and_scan(
        self, config_dirs: list[str], scan_dirs: list[str]
    ) -> None:
        """auto_discover output contains all config dirs AND all scan dirs.

        **Validates: Requirements 1.3**
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Create config-declared directories (these exist on disk)
            config_resolved: set[str] = set()
            for name in config_dirs:
                dir_path = tmp_path / f"cfg_{name}"
                dir_path.mkdir(exist_ok=True)
                config_resolved.add(str(dir_path.resolve()))

            # Create scan-discoverable directories (with qualifying .py files)
            scan_resolved: set[str] = set()
            for name in scan_dirs:
                dir_path = _make_qualifying_dir(tmp_path, f"scan_{name}")
                scan_resolved.add(str(dir_path.resolve()))

            # Write config listing the config dirs
            cfg_dir_names = [f"cfg_{name}" for name in config_dirs]
            _write_pyproject_toml(tmp_path, cfg_dir_names, key="jobs_directories")

            # Call auto_discover with scan_depth=0 (scans CWD itself)
            # Since scan dirs are children of CWD, use depth=1
            result = auto_discover(cwd=tmp_path, scan_depth=1)
            result_dirs = set(result.directories or [])

            # All config directories should be in output
            for d in config_resolved:
                assert d in result_dirs, (
                    f"Config directory '{d}' not in output.\nResult: {result_dirs}"
                )

            # All scan directories should be in output
            for d in scan_resolved:
                assert d in result_dirs, (
                    f"Scan directory '{d}' not in output.\nResult: {result_dirs}"
                )

    @given(
        shared_dirs=st.lists(
            _subdir_name_strategy,
            min_size=1,
            max_size=4,
            unique=True,
        ),
    )
    def test_no_duplicates_when_sources_overlap(self, shared_dirs: list[str]) -> None:
        """When config and scan discover the same directory, no duplicates appear.

        **Validates: Requirements 1.3**
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Create directories that qualify for scanning AND are in config
            for name in shared_dirs:
                _make_qualifying_dir(tmp_path, name)

            # Write config listing the same directories
            _write_pyproject_toml(tmp_path, shared_dirs, key="jobs_directories")

            # Call auto_discover with scan_depth=1 (discovers children)
            result = auto_discover(cwd=tmp_path, scan_depth=1)
            result_dirs = result.directories or []

            # Verify no duplicates
            assert len(result_dirs) == len(set(result_dirs)), (
                f"Duplicate entries found in output.\n"
                f"Result: {result_dirs}\n"
                f"Unique: {set(result_dirs)}"
            )

            # Verify all shared directories are present exactly once
            for name in shared_dirs:
                expected_path = str((tmp_path / name).resolve())
                count = result_dirs.count(expected_path)
                assert count == 1, (
                    f"Directory '{name}' appears {count} times, expected exactly 1.\n"
                    f"Result: {result_dirs}"
                )


# =============================================================================
# Strategies for Property 4: Blacklisted directories
# =============================================================================

_BLACKLISTED_DIRS: list[str] = [
    ".venv",
    "__pycache__",
    ".git",
    "node_modules",
    "dist",
    "build",
]

# Strategy for selecting a blacklisted directory name
_blacklisted_dir_strategy = st.sampled_from(_BLACKLISTED_DIRS)

# Strategy for generating dot-prefixed directory names
_dot_prefixed_strategy = st.text(
    alphabet=string.ascii_lowercase,
    min_size=1,
    max_size=8,
).map(lambda s: f".{s}")


# =============================================================================
# Property 4: Blacklisted directories are never scanned
# Feature: cli-simplification-and-robustness, Property 4: Blacklisted dirs
# =============================================================================


@pytest.mark.slow
class TestBlacklistedDirsNeverScanned:
    """Property 4: Blacklisted directories are never scanned.

    For any directory tree where directories named .venv, __pycache__, .git,
    node_modules, dist, build, or any dot-prefixed name exist (even if they
    contain qualifying .py files), auto_discover() SHALL never include those
    directories in scan results.

    **Validates: Requirements 1.4**
    """

    @given(blacklisted=_blacklisted_dir_strategy)
    def test_named_blacklisted_dirs_excluded_from_scan(self, blacklisted: str) -> None:
        """Named blacklisted directories are never in scan results even with qualifying files.

        **Validates: Requirements 1.4**
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Create a blacklisted directory with a qualifying .py file
            _make_qualifying_dir(tmp_path, blacklisted)

            # Also create a legitimate qualifying directory (so we know scanning works)
            _make_qualifying_dir(tmp_path, "legit")

            # Call auto_discover with depth=1 to scan children
            result = auto_discover(cwd=tmp_path, scan_depth=1)
            result_dirs = set(result.directories or [])

            # The blacklisted directory must NOT appear
            blacklisted_path = str((tmp_path / blacklisted).resolve())
            assert blacklisted_path not in result_dirs, (
                f"Blacklisted directory '{blacklisted}' should not appear "
                f"in scan results.\nResult: {result_dirs}"
            )

            # The legitimate directory SHOULD appear (sanity check)
            legit_path = str((tmp_path / "legit").resolve())
            assert legit_path in result_dirs, (
                f"Legitimate directory 'legit' should appear in scan results.\n"
                f"Result: {result_dirs}"
            )

    @given(dot_name=_dot_prefixed_strategy)
    def test_dot_prefixed_dirs_excluded_from_scan(self, dot_name: str) -> None:
        """Dot-prefixed directories are never in scan results even with qualifying files.

        **Validates: Requirements 1.4**
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Create a dot-prefixed directory with a qualifying .py file
            _make_qualifying_dir(tmp_path, dot_name)

            # Also create a legitimate qualifying directory
            _make_qualifying_dir(tmp_path, "legit")

            # Call auto_discover with depth=1
            result = auto_discover(cwd=tmp_path, scan_depth=1)
            result_dirs = set(result.directories or [])

            # The dot-prefixed directory must NOT appear
            dot_path = str((tmp_path / dot_name).resolve())
            assert dot_path not in result_dirs, (
                f"Dot-prefixed directory '{dot_name}' should not appear "
                f"in scan results.\nResult: {result_dirs}"
            )

    @given(
        blacklisted=_blacklisted_dir_strategy,
        depth=st.integers(min_value=1, max_value=5),
    )
    def test_blacklisted_dirs_excluded_at_any_depth(
        self, blacklisted: str, depth: int
    ) -> None:
        """Blacklisted directories nested at any depth are never scanned.

        **Validates: Requirements 1.4**
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Create a nested structure: legit/blacklisted/
            legit_dir = tmp_path / "legit"
            legit_dir.mkdir()
            # Put a qualifying file in legit so it's discovered
            (legit_dir / "job.py").write_text(_QUALIFYING_PY_CONTENT, encoding="utf-8")

            # Put a blacklisted dir inside the legit dir
            nested_blacklisted = legit_dir / blacklisted
            nested_blacklisted.mkdir()
            (nested_blacklisted / "job.py").write_text(
                _QUALIFYING_PY_CONTENT, encoding="utf-8"
            )

            # Call auto_discover with enough depth to reach nested
            result = auto_discover(cwd=tmp_path, scan_depth=depth)
            result_dirs = set(result.directories or [])

            # The nested blacklisted directory must NOT appear
            nested_path = str(nested_blacklisted.resolve())
            assert nested_path not in result_dirs, (
                f"Nested blacklisted directory '{blacklisted}' at depth should "
                f"not appear in scan results.\nResult: {result_dirs}"
            )


# =============================================================================
# Property 5: Scan depth clamping
# Feature: cli-simplification-and-robustness, Property 5: Depth clamping
# =============================================================================


@pytest.mark.slow
class TestScanDepthClamping:
    """Property 5: Scan depth clamping.

    For any integer value passed as scan_depth, the effective scan depth
    SHALL equal max(0, min(scan_depth, 5)).

    **Validates: Requirements 1.6, 1.7, 1.8, 2.4, 2.5**
    """

    @given(scan_depth=st.integers(min_value=-100, max_value=100))
    def test_depth_clamping_behavior(self, scan_depth: int) -> None:
        """Effective scan depth equals max(0, min(scan_depth, 5)).

        **Validates: Requirements 1.6, 1.7, 1.8, 2.4, 2.5**
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            expected_effective = max(0, min(scan_depth, 5))

            # Create a directory structure with qualifying files at various depths:
            # depth 0: CWD itself
            # depth 1: CWD/level1/
            # depth 2: CWD/level1/level2/
            # ... up to depth 6 (one beyond max)
            current = tmp_path
            dirs_at_depth: dict[int, Path] = {0: tmp_path}

            for level in range(1, 7):
                current = current / f"level{level}"
                current.mkdir()
                dirs_at_depth[level] = current
                # Put qualifying file at each level
                (current / "job.py").write_text(
                    _QUALIFYING_PY_CONTENT, encoding="utf-8"
                )

            # Also put a qualifying file at depth 0 (CWD itself)
            (tmp_path / "job.py").write_text(_QUALIFYING_PY_CONTENT, encoding="utf-8")

            # Call auto_discover with the given scan_depth
            result = auto_discover(cwd=tmp_path, scan_depth=scan_depth)
            result_dirs = set(result.directories or [])

            # Directories at depths 0..effective_depth should be discoverable
            for depth_level in range(expected_effective + 1):
                dir_path = str(dirs_at_depth[depth_level].resolve())
                assert dir_path in result_dirs, (
                    f"Directory at depth {depth_level} should be discovered "
                    f"with effective depth {expected_effective} "
                    f"(raw scan_depth={scan_depth}).\n"
                    f"Result: {result_dirs}"
                )

            # Directories BEYOND effective_depth should NOT be discovered
            for depth_level in range(expected_effective + 1, 7):
                dir_path = str(dirs_at_depth[depth_level].resolve())
                assert dir_path not in result_dirs, (
                    f"Directory at depth {depth_level} should NOT be discovered "
                    f"with effective depth {expected_effective} "
                    f"(raw scan_depth={scan_depth}).\n"
                    f"Result: {result_dirs}"
                )


# =============================================================================
# Property 6: JOB_GROUP is not a discovery gate
# Feature: cli-simplification-and-robustness, Property 6: JOB_GROUP irrelevance
# =============================================================================

# Python file content with JOB_GROUP assignment
_PY_WITH_JOB_GROUP = '''\
JOB_GROUP = "my_job"

def hello():
    """A public function."""
    return "hello"
'''

# Python file content without JOB_GROUP assignment
_PY_WITHOUT_JOB_GROUP = '''\
def hello():
    """A public function."""
    return "hello"
'''


@pytest.mark.slow
class TestJobGroupNotDiscoveryGate:
    """Property 6: JOB_GROUP is not a discovery gate.

    For any Python file that passes the pre-filter stack, the presence or
    absence of JOB_GROUP module-level assignment SHALL NOT affect whether
    auto_discover() includes that file's directory.

    **Validates: Requirements 3.3**
    """

    @given(
        dir_names=st.lists(
            _subdir_name_strategy,
            min_size=1,
            max_size=4,
            unique=True,
        ),
        has_job_group=st.lists(st.booleans(), min_size=1, max_size=4),
    )
    def test_job_group_does_not_affect_discovery(
        self, dir_names: list[str], has_job_group: list[bool]
    ) -> None:
        """Directories are discovered regardless of JOB_GROUP presence in files.

        **Validates: Requirements 3.3**
        """
        # Ensure lists are same length
        count = min(len(dir_names), len(has_job_group))
        dir_names = dir_names[:count]
        has_job_group = has_job_group[:count]

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            expected_dirs: set[str] = set()

            for name, with_job_group in zip(dir_names, has_job_group, strict=False):
                dir_path = tmp_path / name
                dir_path.mkdir(exist_ok=True)

                # Write a qualifying .py file with or without JOB_GROUP
                content = (
                    _PY_WITH_JOB_GROUP if with_job_group else _PY_WITHOUT_JOB_GROUP
                )
                (dir_path / "job.py").write_text(content, encoding="utf-8")
                expected_dirs.add(str(dir_path.resolve()))

            # Call auto_discover with depth=1 to find child dirs
            result = auto_discover(cwd=tmp_path, scan_depth=1)
            result_dirs = set(result.directories or [])

            # ALL directories with qualifying files should be discovered,
            # regardless of JOB_GROUP
            for expected in expected_dirs:
                assert expected in result_dirs, (
                    f"Directory should be discovered regardless of JOB_GROUP.\n"
                    f"Expected: {expected}\n"
                    f"Result: {result_dirs}"
                )

    @given(
        dir_name=_subdir_name_strategy,
    )
    def test_same_directory_discovered_with_and_without_job_group(
        self, dir_name: str
    ) -> None:
        """The same directory is discovered identically with or without JOB_GROUP.

        **Validates: Requirements 3.3**
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # First: create dir with JOB_GROUP
            dir_path = tmp_path / dir_name
            dir_path.mkdir(exist_ok=True)
            (dir_path / "job.py").write_text(_PY_WITH_JOB_GROUP, encoding="utf-8")

            result_with = auto_discover(cwd=tmp_path, scan_depth=1)
            dirs_with = set(result_with.directories or [])

            # Replace file content without JOB_GROUP
            (dir_path / "job.py").write_text(_PY_WITHOUT_JOB_GROUP, encoding="utf-8")

            result_without = auto_discover(cwd=tmp_path, scan_depth=1)
            dirs_without = set(result_without.directories or [])

            # Both runs should discover the same directory
            resolved = str(dir_path.resolve())
            in_with = resolved in dirs_with
            in_without = resolved in dirs_without

            assert in_with == in_without, (
                f"JOB_GROUP presence affected discovery: "
                f"with JOB_GROUP={in_with}, without JOB_GROUP={in_without}\n"
                f"Dir: {resolved}\n"
                f"With: {dirs_with}\n"
                f"Without: {dirs_without}"
            )


# =============================================================================
# Property 7: CLI filter flags do not affect auto_discover
# Feature: cli-simplification-and-robustness, Property 7: CLI flags independence
# =============================================================================


@pytest.mark.slow
class TestCliFilterFlagsDoNotAffectAutoDiscover:
    """Property 7: CLI filter flags do not affect auto_discover.

    For any invocation of auto_discover(), directories returned SHALL be
    independent of per-invocation CLI filter flags.

    auto_discover() does not accept filter parameters (--require-file-import,
    --require-file-prefix, --require-file-postfix, --require-job-decorators,
    --exclude). Those filters are applied later by DirectoryScanProvider.
    Calling auto_discover() with the same filesystem state always produces
    the same result.

    **Validates: Requirements 8.4**
    """

    @given(
        dir_names=st.lists(
            _subdir_name_strategy,
            min_size=1,
            max_size=4,
            unique=True,
        ),
        scan_depth=st.integers(min_value=0, max_value=3),
        num_calls=st.integers(min_value=2, max_value=5),
    )
    def test_auto_discover_is_deterministic_for_same_filesystem(
        self, dir_names: list[str], scan_depth: int, num_calls: int
    ) -> None:
        """Repeated calls to auto_discover() with same state produce same result.

        **Validates: Requirements 8.4**
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Create qualifying directories
            for name in dir_names:
                _make_qualifying_dir(tmp_path, name)

            # Call auto_discover multiple times with same parameters
            results: list[list[str]] = []
            for _ in range(num_calls):
                result = auto_discover(cwd=tmp_path, scan_depth=scan_depth)
                results.append(list(result.directories or []))

            # All calls must produce identical results
            first_result = results[0]
            for i, result in enumerate(results[1:], start=1):
                assert result == first_result, (
                    f"auto_discover() call {i} produced different result.\n"
                    f"First: {first_result}\n"
                    f"Call {i}: {result}"
                )

    @given(
        dir_names=st.lists(
            _subdir_name_strategy,
            min_size=1,
            max_size=3,
            unique=True,
        ),
    )
    def test_auto_discover_signature_has_no_filter_params(
        self, dir_names: list[str]
    ) -> None:
        """auto_discover() does not accept CLI filter parameters in its signature.

        This verifies the API design ensures filter flags CANNOT affect discovery.
        The function only takes cwd and scan_depth — no filter-related params.

        **Validates: Requirements 8.4**
        """
        import inspect

        sig = inspect.signature(auto_discover)
        param_names = set(sig.parameters.keys())

        # These filter-related parameters must NOT exist on auto_discover
        filter_params = {
            "require_file_import",
            "require_file_prefix",
            "require_file_postfix",
            "require_job_decorators",
            "exclude",
            "exclude_patterns",
        }

        overlap = param_names & filter_params
        assert not overlap, (
            f"auto_discover() should NOT accept filter parameters, "
            f"but it has: {overlap}\n"
            f"All params: {param_names}"
        )

        # Verify only expected params exist
        expected_params = {"cwd", "scan_depth", "overrides", "search_ancestors"}
        assert param_names == expected_params, (
            f"auto_discover() should only accept {expected_params}, "
            f"but has: {param_names}"
        )
