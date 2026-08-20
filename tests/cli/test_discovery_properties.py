"""Property-based tests for discovery filters.

# Feature: cli-config-and-discovery-filtering, Property 7: Filename Filters Operate on Stem
# Feature: cli-config-and-discovery-filtering, Property 8: AND Composition of Filters
"""

from __future__ import annotations

import keyword as _kw
import tempfile
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._discovery.filter_factory import build_pre_filter_from_config
from functualize._primitives.pre_filter import FilePostfixPreFilter, FilePrefixPreFilter
from functualize.app.config import DiscoveryConfig

# =============================================================================
# Strategies for Property 7
# =============================================================================

# Generate valid characters for file stems (alphanumeric + underscores)
_stem_chars = st.sampled_from(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
)
_stem_strategy = st.text(_stem_chars, min_size=1, max_size=30)

# Generate directory components (non-empty, valid path segments)
_dir_component = st.text(
    st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789_-"),
    min_size=1,
    max_size=15,
)
_dir_path_strategy = st.lists(_dir_component, min_size=0, max_size=4)

# Prefix/postfix values (non-empty strings from stem-valid characters)
_affix_strategy = st.text(_stem_chars, min_size=1, max_size=10)


def _build_path(dir_parts: list[str], stem: str) -> Path:
    """Build a .py file path from directory components and a stem."""
    parts = dir_parts + [f"{stem}.py"]
    return Path(*parts) if len(parts) > 1 else Path(parts[0])


# =============================================================================
# Property 7: Filename Filters Operate on Stem
# =============================================================================


@pytest.mark.slow
class TestFilenameFiltersOperateOnStem:
    """Property 7: Filename Filters Operate on Stem.

    For any file path and configured prefix/postfix values, the
    FilePrefixPreFilter SHALL return True if and only if the file's stem
    (filename without .py extension) starts with the prefix, and the
    FilePostfixPreFilter SHALL return True if and only if the file's stem
    ends with the postfix — regardless of directory path components.

    **Validates: Requirements 8.1, 8.2, 8.4**
    """

    @given(
        dir_parts=_dir_path_strategy,
        stem=_stem_strategy,
        prefix=_affix_strategy,
    )
    def test_prefix_filter_matches_iff_stem_starts_with_prefix(
        self, dir_parts: list[str], stem: str, prefix: str
    ) -> None:
        """FilePrefixPreFilter returns True iff source_file.stem.startswith(prefix).

        **Validates: Requirements 8.1, 8.4**
        """
        path = _build_path(dir_parts, stem)
        f = FilePrefixPreFilter(prefix)

        actual = f.should_import(path)
        expected = stem.startswith(prefix)

        assert actual == expected, (
            f"FilePrefixPreFilter('{prefix}').should_import({path}) = {actual}, "
            f"but stem '{stem}'.startswith('{prefix}') = {expected}"
        )

    @given(
        dir_parts=_dir_path_strategy,
        stem=_stem_strategy,
        postfix=_affix_strategy,
    )
    def test_postfix_filter_matches_iff_stem_ends_with_postfix(
        self, dir_parts: list[str], stem: str, postfix: str
    ) -> None:
        """FilePostfixPreFilter returns True iff source_file.stem.endswith(postfix).

        **Validates: Requirements 8.2, 8.4**
        """
        path = _build_path(dir_parts, stem)
        f = FilePostfixPreFilter(postfix)

        actual = f.should_import(path)
        expected = stem.endswith(postfix)

        assert actual == expected, (
            f"FilePostfixPreFilter('{postfix}').should_import({path}) = {actual}, "
            f"but stem '{stem}'.endswith('{postfix}') = {expected}"
        )

    @given(
        dir_parts=_dir_path_strategy,
        stem=_stem_strategy,
        prefix=_affix_strategy,
    )
    def test_prefix_filter_ignores_directory_components(
        self, dir_parts: list[str], stem: str, prefix: str
    ) -> None:
        """FilePrefixPreFilter result is independent of directory path.

        The same stem with different directory prefixes must yield the same result.

        **Validates: Requirements 8.4**
        """
        path_with_dirs = _build_path(dir_parts, stem)
        path_without_dirs = Path(f"{stem}.py")
        f = FilePrefixPreFilter(prefix)

        assert f.should_import(path_with_dirs) == f.should_import(path_without_dirs)

    @given(
        dir_parts=_dir_path_strategy,
        stem=_stem_strategy,
        postfix=_affix_strategy,
    )
    def test_postfix_filter_ignores_directory_components(
        self, dir_parts: list[str], stem: str, postfix: str
    ) -> None:
        """FilePostfixPreFilter result is independent of directory path.

        The same stem with different directory prefixes must yield the same result.

        **Validates: Requirements 8.4**
        """
        path_with_dirs = _build_path(dir_parts, stem)
        path_without_dirs = Path(f"{stem}.py")
        f = FilePostfixPreFilter(postfix)

        assert f.should_import(path_with_dirs) == f.should_import(path_without_dirs)

    @given(
        dir_parts=_dir_path_strategy,
        stem=_stem_strategy,
        prefix=_affix_strategy,
    )
    def test_prefix_filter_not_affected_by_py_extension(
        self, dir_parts: list[str], stem: str, prefix: str
    ) -> None:
        """FilePrefixPreFilter operates on stem, not affected by .py extension.

        **Validates: Requirements 8.1, 8.4**
        """
        path = _build_path(dir_parts, stem)
        f = FilePrefixPreFilter(prefix)

        # The filter should match based on stem only
        assert f.should_import(path) == stem.startswith(prefix)

    @given(
        dir_parts=_dir_path_strategy,
        stem=_stem_strategy,
        postfix=_affix_strategy,
    )
    def test_postfix_filter_not_affected_by_py_extension(
        self, dir_parts: list[str], stem: str, postfix: str
    ) -> None:
        """FilePostfixPreFilter operates on stem, not affected by .py extension.

        The postfix matches the stem end, not the filename end (which would be .py).

        **Validates: Requirements 8.2, 8.4**
        """
        path = _build_path(dir_parts, stem)
        f = FilePostfixPreFilter(postfix)

        # The filter should match based on stem only
        assert f.should_import(path) == stem.endswith(postfix)


# =============================================================================
# Strategies for Property 8
# =============================================================================

# Feature: cli-config-and-discovery-filtering, Property 8: AND Composition of Filters

# Characters valid for file stems and affixes (no leading underscore for prefix test)
_p8_stem_chars = st.sampled_from(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
)
_p8_affix = st.text(_p8_stem_chars, min_size=1, max_size=8)

# Strategy for optional prefix
_p8_opt_prefix = st.one_of(st.none(), _p8_affix)

# Strategy for optional postfix
_p8_opt_postfix = st.one_of(st.none(), _p8_affix)

# Package names for require_file_import (must be valid identifier, not a keyword)
_p8_package_name = st.text(
    st.sampled_from("abcdefghijklmnopqrstuvwxyz_"),
    min_size=2,
    max_size=10,
).filter(lambda s: s[0].isalpha() and s.isidentifier() and not _kw.iskeyword(s))

_p8_opt_import = st.one_of(st.none(), _p8_package_name)

# Marker variable names (must be valid identifier, not keyword, not dunder to avoid
# conflicts with Python special names)
_p8_marker_name = st.text(
    st.sampled_from("abcdefghijklmnopqrstuvwxyz_"),
    min_size=3,
    max_size=15,
).filter(
    lambda s: (
        s.isidentifier()
        and not _kw.iskeyword(s)
        and not (s.startswith("__") and s.endswith("__"))
    )
)

_p8_opt_marker = st.one_of(st.none(), _p8_marker_name)

# Exclude patterns: simple glob patterns
_p8_glob_pattern = st.from_regex(r"[a-z]{1,5}\*\.py", fullmatch=True)
_p8_opt_exclude = st.one_of(
    st.just(()),
    st.tuples(_p8_glob_pattern).map(tuple),
)

# Booleans controlling whether the file satisfies each filter
_p8_bool = st.booleans()


def _make_file_content(
    *,
    has_public_func: bool,
    import_pkg: str | None,
    marker_name: str | None,
) -> str:
    """Generate Python file content based on desired filter outcomes."""
    lines: list[str] = []

    if import_pkg:
        lines.append(f"import {import_pkg}")

    if marker_name:
        lines.append(f"{marker_name} = True")

    lines.append("")

    if has_public_func:
        lines.append("def public_job():")
        lines.append("    pass")
    else:
        lines.append("def _private():")
        lines.append("    pass")

    return "\n".join(lines) + "\n"


# =============================================================================
# Property 8: AND Composition of Filters
# =============================================================================


@pytest.mark.slow
class TestANDCompositionOfFilters:
    """Property 8: AND Composition of Filters.

    For any DiscoveryConfig with multiple filters enabled and any source file,
    the file qualifies for discovery if and only if it passes ALL enabled
    file-level filters. A file that fails any single enabled filter SHALL be
    excluded.

    **Validates: Requirements 6.6, 7.4, 8.3, 8.6, 9.6, 11.3, 12.4**
    """

    @given(
        prefix=_p8_opt_prefix,
        postfix=_p8_opt_postfix,
        import_pkg=_p8_opt_import,
        marker=_p8_opt_marker,
        satisfy_prefix=_p8_bool,
        satisfy_postfix=_p8_bool,
        satisfy_import=_p8_bool,
        satisfy_marker=_p8_bool,
    )
    def test_combined_filter_requires_all_enabled_filters_to_pass(
        self,
        prefix: str | None,
        postfix: str | None,
        import_pkg: str | None,
        marker: str | None,
        satisfy_prefix: bool,
        satisfy_postfix: bool,
        satisfy_import: bool,
        satisfy_marker: bool,
    ) -> None:
        """build_pre_filter_from_config returns True iff ALL enabled filters pass.

        We generate a DiscoveryConfig with a random subset of filters enabled,
        then create a real file that satisfies or violates each enabled filter.
        The combined filter should return True only when every enabled filter
        is satisfied.

        **Validates: Requirements 6.6, 7.4, 8.3, 8.6, 9.6, 11.3, 12.4**
        """
        # Build file stem that satisfies/violates prefix and postfix
        # Core stem is always non-underscore to pass DefaultModulePreFilter
        core = "task"

        if prefix is not None:
            if satisfy_prefix:
                stem = prefix + core
            else:
                # Ensure stem does NOT start with prefix
                stem = "x" + core if core.startswith(prefix) else core
                if stem.startswith(prefix):
                    stem = "zz" + stem
            # Also handle postfix
            if postfix is not None:
                if satisfy_postfix:
                    stem = stem + postfix
                # If not satisfy_postfix, ensure stem doesn't end with postfix
                elif stem.endswith(postfix):
                    stem = stem + "xx"
        elif postfix is not None:
            stem = core
            if satisfy_postfix:
                stem = stem + postfix
            elif stem.endswith(postfix):
                stem = stem + "xx"
        else:
            stem = core

        # Determine what goes in the file content
        actual_import = (
            import_pkg if (import_pkg is not None and satisfy_import) else None
        )
        actual_marker = marker if (marker is not None and satisfy_marker) else None

        content = _make_file_content(
            has_public_func=True,  # Always have a public func for ASTModulePreFilter
            import_pkg=actual_import,
            marker_name=actual_marker,
        )

        # Build config
        config = DiscoveryConfig(
            require_file_prefix=prefix,
            require_file_postfix=postfix,
            require_file_import=import_pkg,
            require_file_marker=marker,
        )

        # Write file to temp directory and run filter
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            file_path = tmp_path / f"{stem}.py"
            file_path.write_text(content, encoding="utf-8")

            combined_filter = build_pre_filter_from_config(config, tmp_path)
            actual_result = combined_filter.should_import(file_path)

        # Compute expected result: AND of all enabled filters
        expected_passes: list[bool] = []

        # DefaultModulePreFilter always active — stem never starts with _
        expected_passes.append(not stem.startswith("_"))

        # ASTModulePreFilter always active — we always have a public func
        expected_passes.append(True)

        if prefix is not None:
            expected_passes.append(stem.startswith(prefix))
        if postfix is not None:
            expected_passes.append(stem.endswith(postfix))
        if import_pkg is not None:
            expected_passes.append(satisfy_import)
        if marker is not None:
            expected_passes.append(satisfy_marker)

        expected_result = all(expected_passes)

        assert actual_result == expected_result, (
            f"AND composition failed.\n"
            f"  Config: prefix={prefix!r}, postfix={postfix!r}, "
            f"import={import_pkg!r}, marker={marker!r}\n"
            f"  File: {stem}.py\n"
            f"  Individual passes: {expected_passes}\n"
            f"  Expected: {expected_result}, Got: {actual_result}"
        )

    @given(
        prefix=_p8_affix,
        postfix=_p8_affix,
        satisfy_prefix=_p8_bool,
        satisfy_postfix=_p8_bool,
    )
    def test_single_failing_filter_causes_rejection(
        self,
        prefix: str,
        postfix: str,
        satisfy_prefix: bool,
        satisfy_postfix: bool,
    ) -> None:
        """If any single enabled filter rejects, the combined result is False.

        This property ensures strict AND semantics: enabling N filters means
        all N must pass for the file to qualify.

        **Validates: Requirements 8.3, 8.6, 12.4**
        """
        # Build stem
        core = "job"
        if satisfy_prefix:
            stem = prefix + core
        else:
            stem = "q" + core
            if stem.startswith(prefix):
                stem = "zz" + stem

        if satisfy_postfix:
            stem = stem + postfix
        elif stem.endswith(postfix):
            stem = stem + "ww"

        content = _make_file_content(
            has_public_func=True,
            import_pkg=None,
            marker_name=None,
        )

        config = DiscoveryConfig(
            require_file_prefix=prefix,
            require_file_postfix=postfix,
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            file_path = tmp_path / f"{stem}.py"
            file_path.write_text(content, encoding="utf-8")

            combined_filter = build_pre_filter_from_config(config, tmp_path)
            actual_result = combined_filter.should_import(file_path)

        prefix_passes = stem.startswith(prefix)
        postfix_passes = stem.endswith(postfix)

        # If either filter rejects, combined must reject
        if not prefix_passes or not postfix_passes:
            assert actual_result is False, (
                f"Expected rejection when a filter fails.\n"
                f"  prefix={prefix!r} passes={prefix_passes}, "
                f"postfix={postfix!r} passes={postfix_passes}\n"
                f"  stem={stem!r}, result={actual_result}"
            )
        else:
            assert actual_result is True, (
                f"Expected acceptance when all filters pass.\n"
                f"  prefix={prefix!r}, postfix={postfix!r}, stem={stem!r}"
            )

    @given(
        import_pkg=_p8_package_name,
        marker=_p8_marker_name,
        satisfy_import=_p8_bool,
        satisfy_marker=_p8_bool,
    )
    def test_ast_filters_combine_with_and_semantics(
        self,
        import_pkg: str,
        marker: str,
        satisfy_import: bool,
        satisfy_marker: bool,
    ) -> None:
        """AST-based filters (import + marker) also combine via AND.

        **Validates: Requirements 6.6, 7.4, 12.4**
        """
        actual_import = import_pkg if satisfy_import else None
        actual_marker = marker if satisfy_marker else None

        content = _make_file_content(
            has_public_func=True,
            import_pkg=actual_import,
            marker_name=actual_marker,
        )

        config = DiscoveryConfig(
            require_file_import=import_pkg,
            require_file_marker=marker,
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            file_path = tmp_path / "module.py"
            file_path.write_text(content, encoding="utf-8")

            combined_filter = build_pre_filter_from_config(config, tmp_path)
            actual_result = combined_filter.should_import(file_path)

        # Both must pass for the file to qualify
        expected = satisfy_import and satisfy_marker

        assert actual_result == expected, (
            f"AST AND composition failed.\n"
            f"  import={import_pkg!r} satisfied={satisfy_import}, "
            f"marker={marker!r} satisfied={satisfy_marker}\n"
            f"  Expected: {expected}, Got: {actual_result}"
        )

    @given(
        prefix=_p8_affix,
        import_pkg=_p8_package_name,
        exclude_pattern=_p8_glob_pattern,
    )
    def test_exclude_pattern_combined_with_other_filters(
        self,
        prefix: str,
        import_pkg: str,
        exclude_pattern: str,
    ) -> None:
        """GlobExcludePreFilter combines via AND with other filters.

        A file that passes prefix + import filters but matches an exclude
        pattern is still rejected.

        **Validates: Requirements 11.3, 12.4**
        """
        # Create a file that satisfies prefix and import
        stem = prefix + "module"
        content = _make_file_content(
            has_public_func=True,
            import_pkg=import_pkg,
            marker_name=None,
        )

        config = DiscoveryConfig(
            require_file_prefix=prefix,
            require_file_import=import_pkg,
            exclude_patterns=(exclude_pattern,),
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            file_path = tmp_path / f"{stem}.py"
            file_path.write_text(content, encoding="utf-8")

            combined_filter = build_pre_filter_from_config(config, tmp_path)
            actual_result = combined_filter.should_import(file_path)

        # Check if the file matches the exclude pattern
        import fnmatch

        rel_path = f"{stem}.py"
        excluded = fnmatch.fnmatch(rel_path, exclude_pattern)

        if excluded:
            assert actual_result is False, (
                f"File should be excluded by pattern {exclude_pattern!r} "
                f"but got True. rel_path={rel_path!r}"
            )
        else:
            # File passes all filters (prefix matches, import present, not excluded)
            assert actual_result is True, (
                f"File passes all filters but got False.\n"
                f"  prefix={prefix!r}, stem={stem!r}, "
                f"exclude={exclude_pattern!r}, rel={rel_path!r}"
            )
