"""Property-based tests for CachedDirectoryScanProvider (Properties 19 & 20).

Property 19: CachedDirectoryScanProvider cache validity
    For any cached job descriptor whose source file mtime has not changed,
    get_job(name) SHALL return the cached descriptor without re-importing the
    module. For any cached descriptor whose source file mtime has changed, the
    provider SHALL re-import that single module and update the cache.

Property 20: Pre-filter decision caching correctness
    For any source file where ModulePreFilter.should_import() returned False and
    the file's mtime has not changed since the decision was cached, the
    CachedDirectoryScanProvider SHALL skip re-running the pre-filter and use the
    cached negative decision. For any cached decision where the mtime differs,
    the provider SHALL re-run the pre-filter.

**Validates: Requirements 13.2, 13.3, 13.4, 19.1, 19.3, 19.4**
"""

from __future__ import annotations

import keyword
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from functualize._discovery.cached_provider import CachedDirectoryScanProvider
from functualize._primitives.locator import ResourceLocator

# --- Strategies ---

_PYTHON_KEYWORDS = set(keyword.kwlist) | {"True", "False", "None"}

# Valid Python function/module names (public, no underscore prefix)
_valid_names = st.from_regex(r"[a-z][a-z0-9_]{2,12}", fullmatch=True).filter(
    lambda n: n.isidentifier() and not n.startswith("__") and n not in _PYTHON_KEYWORDS
)


@st.composite
def job_module_specs(draw: st.DrawFn) -> list[tuple[str, list[str]]]:
    """Generate a list of (module_filename, [function_names]) specs.

    Each module has 1-3 public functions. Module filenames are unique.
    Function names are globally unique across all modules.
    """
    num_modules = draw(st.integers(min_value=1, max_value=5))
    module_names = draw(
        st.lists(_valid_names, min_size=num_modules, max_size=num_modules, unique=True)
    )

    all_func_names: list[str] = []
    specs: list[tuple[str, list[str]]] = []

    for mod_name in module_names:
        num_funcs = draw(st.integers(min_value=1, max_value=3))
        func_names = draw(
            st.lists(
                _valid_names.filter(
                    lambda n: n not in all_func_names and n not in module_names
                ),
                min_size=num_funcs,
                max_size=num_funcs,
                unique=True,
            )
        )
        all_func_names.extend(func_names)
        specs.append((mod_name, func_names))

    return specs


def _build_module_source(func_names: list[str]) -> str:
    """Build a Python module source file with given public functions."""
    lines = ['"""Generated test module."""', ""]
    for name in func_names:
        lines.append(f"def {name}():")
        lines.append(f'    """Docstring for {name}."""')
        lines.append("    pass")
        lines.append("")
    return "\n".join(lines)


def _make_locator(tmp_path: Path) -> ResourceLocator:
    """Create a ResourceLocator that reads/writes to tmp_path/cache."""
    return (
        ResourceLocator()
        .search_explicit(tmp_path / "cache")
        .write_to_explicit(tmp_path / "cache")
    )


def _write_module(directory: Path, name: str, func_names: list[str]) -> Path:
    """Write a module file with the given functions."""
    source = _build_module_source(func_names)
    module_file = directory / f"{name}.py"
    module_file.write_text(source, encoding="utf-8")
    return module_file


# =============================================================================
# Property 19: CachedDirectoryScanProvider cache validity
# =============================================================================


class TestProperty19CacheValidity:
    """Property 19: CachedDirectoryScanProvider cache validity.

    For any cached job descriptor whose source file mtime has not changed,
    get_job(name) SHALL return the cached descriptor without re-importing the
    module. For any cached descriptor whose source file mtime has changed, the
    provider SHALL re-import that single module and update the cache.

    **Validates: Requirements 13.2, 13.3, 13.4**
    """

    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=10000,
    )
    @given(spec=job_module_specs())
    def test_unchanged_mtime_returns_cached_without_reimport(
        self, spec: list[tuple[str, list[str]]]
    ) -> None:
        """For any cached job descriptor whose source file mtime has not changed,
        get_job(name) SHALL return the cached descriptor without re-importing.

        **Validates: Requirements 13.2**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            jobs_dir = tmp_path / "jobs"
            jobs_dir.mkdir()
            locator = _make_locator(tmp_path)

            # Create module files
            all_func_names: list[str] = []
            for mod_name, func_names in spec:
                _write_module(jobs_dir, mod_name, func_names)
                all_func_names.extend(func_names)

            # Create provider and populate cache via list_jobs
            provider = CachedDirectoryScanProvider(
                directories=[str(jobs_dir)], locator=locator
            )
            provider.list_jobs()

            # Now verify: get_job() for each name returns cached descriptor
            # without re-importing (patch _safe_import to detect re-imports)
            with patch.object(
                provider, "_safe_import", wraps=provider._safe_import
            ) as mock_import:
                for func_name in all_func_names:
                    result = provider.get_job(func_name)
                    assert result is not None, (
                        f"get_job('{func_name}') returned None despite being "
                        f"previously cached. Module specs: {spec}"
                    )
                    assert result.name == func_name, (
                        f"Expected descriptor name '{func_name}', got '{result.name}'"
                    )

                # No re-imports should have occurred (mtimes unchanged)
                (
                    mock_import.assert_not_called(),
                    (
                        f"_safe_import was called {mock_import.call_count} times "
                        f"during get_job() calls with unchanged mtimes. "
                        f"Calls: {mock_import.call_args_list}"
                    ),
                )

    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=10000,
    )
    @given(spec=job_module_specs())
    def test_changed_mtime_triggers_reimport_and_cache_update(
        self, spec: list[tuple[str, list[str]]]
    ) -> None:
        """For any cached descriptor whose source file mtime has changed,
        the provider SHALL re-import that single module and update the cache.

        **Validates: Requirements 13.3**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            jobs_dir = tmp_path / "jobs"
            jobs_dir.mkdir()
            locator = _make_locator(tmp_path)

            # Create module files
            for mod_name, func_names in spec:
                _write_module(jobs_dir, mod_name, func_names)

            # Create provider and populate cache
            provider = CachedDirectoryScanProvider(
                directories=[str(jobs_dir)], locator=locator
            )
            provider.list_jobs()

            # Pick the first module and modify it (changing mtime)
            target_mod_name, target_func_names = spec[0]
            target_file = jobs_dir / f"{target_mod_name}.py"

            # Get original content hash
            original_descriptor = provider.get_job(target_func_names[0])
            assert original_descriptor is not None
            original_hash = original_descriptor.content_hash

            # Modify the file to change mtime and content
            time.sleep(0.05)  # Ensure mtime differs
            new_source = _build_module_source(target_func_names)
            new_source += "\n# Modified\n"
            target_file.write_text(new_source, encoding="utf-8")

            # get_job should detect stale entry, re-import, and return updated
            updated_descriptor = provider.get_job(target_func_names[0])
            assert updated_descriptor is not None, (
                f"get_job('{target_func_names[0]}') returned None after "
                f"file modification. Expected re-import and cache update."
            )
            assert updated_descriptor.content_hash != original_hash, (
                f"Content hash unchanged after file modification. "
                f"Expected re-import to produce new hash. "
                f"Original: {original_hash}, Updated: {updated_descriptor.content_hash}"
            )

    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=10000,
    )
    @given(spec=job_module_specs())
    def test_only_stale_module_is_reimported_not_others(
        self, spec: list[tuple[str, list[str]]]
    ) -> None:
        """When one module's mtime changes, only that single module SHALL be
        re-imported — other cached modules remain untouched.

        **Validates: Requirements 13.3**
        """
        # Need at least 2 modules to test isolation
        if len(spec) < 2:
            return

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            jobs_dir = tmp_path / "jobs"
            jobs_dir.mkdir()
            locator = _make_locator(tmp_path)

            # Create module files
            for mod_name, func_names in spec:
                _write_module(jobs_dir, mod_name, func_names)

            # Create provider and populate cache
            provider = CachedDirectoryScanProvider(
                directories=[str(jobs_dir)], locator=locator
            )
            provider.list_jobs()

            # Modify only the first module
            target_mod_name, target_func_names = spec[0]
            target_file = jobs_dir / f"{target_mod_name}.py"
            time.sleep(0.05)
            new_source = _build_module_source(target_func_names) + "\n# Modified\n"
            target_file.write_text(new_source, encoding="utf-8")

            # Track imports during get_job on the modified file
            with patch.object(
                provider, "_safe_import", wraps=provider._safe_import
            ) as mock_import:
                provider.get_job(target_func_names[0])

                # Only one re-import should have occurred (for the modified file)
                assert mock_import.call_count == 1, (
                    f"Expected exactly 1 re-import for the modified module, "
                    f"but got {mock_import.call_count}. "
                    f"Calls: {mock_import.call_args_list}"
                )

                # The import should be for the target file
                imported_file = mock_import.call_args[0][0]
                assert target_mod_name in imported_file, (
                    f"Expected re-import of '{target_mod_name}', "
                    f"but imported: {imported_file}"
                )


# =============================================================================
# Property 20: Pre-filter decision caching correctness
# =============================================================================


class TestProperty20PreFilterDecisionCaching:
    """Property 20: Pre-filter decision caching correctness.

    For any source file where ModulePreFilter.should_import() returned False and
    the file's mtime has not changed since the decision was cached, the
    CachedDirectoryScanProvider SHALL skip re-running the pre-filter and use the
    cached negative decision. For any cached decision where the mtime differs,
    the provider SHALL re-run the pre-filter.

    **Validates: Requirements 19.1, 19.3, 19.4**
    """

    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=10000,
    )
    @given(
        excluded_names=st.lists(_valid_names, min_size=1, max_size=5, unique=True),
        included_names=st.lists(_valid_names, min_size=1, max_size=3, unique=True),
    )
    def test_negative_decision_cached_skips_prefilter_on_unchanged_mtime(
        self,
        excluded_names: list[str],
        included_names: list[str],
    ) -> None:
        """For any source file where should_import() returned False and the mtime
        has not changed, the provider SHALL skip re-running the pre-filter.

        **Validates: Requirements 19.1, 19.3**
        """
        # Ensure no overlap
        included_names = [n for n in included_names if n not in excluded_names]
        if not included_names:
            return

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            jobs_dir = tmp_path / "jobs"
            jobs_dir.mkdir()
            locator = _make_locator(tmp_path)

            # Create modules: some should be excluded, some included
            for name in excluded_names:
                _write_module(jobs_dir, name, [name])
            for name in included_names:
                _write_module(jobs_dir, name, [name])

            # Create a pre-filter that excludes certain modules
            excluded_set = set(excluded_names)
            call_count = [0]

            class TrackingFilter:
                def should_import(self, source_file: Path) -> bool:
                    call_count[0] += 1
                    return source_file.stem not in excluded_set

            tracking_filter = TrackingFilter()

            # First list_jobs() call: pre-filter called for all files
            provider = CachedDirectoryScanProvider(
                directories=[str(jobs_dir)],
                locator=locator,
                pre_filter=tracking_filter,
            )
            jobs1 = provider.list_jobs()
            call_count[0]

            # Verify excluded modules are not in results
            job_names = {j.name for j in jobs1}
            for excl in excluded_names:
                assert excl not in job_names, (
                    f"Excluded module '{excl}' should not appear in list_jobs() results"
                )

            # Verify included modules are in results
            for incl in included_names:
                assert incl in job_names, (
                    f"Included module '{incl}' should appear in list_jobs() results"
                )

            # Reset counter
            call_count[0] = 0

            # Second list_jobs() call: pre-filter should NOT be called for
            # excluded files (decision cached), and should NOT be called for
            # included files (they're already in the job cache)
            provider.list_jobs()
            second_call_count = call_count[0]

            assert second_call_count == 0, (
                f"Pre-filter was called {second_call_count} times on the second "
                f"list_jobs() call with unchanged mtimes. Expected 0 calls "
                f"(all decisions should be cached). "
                f"Excluded: {excluded_names}, Included: {included_names}"
            )

    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=10000,
    )
    @given(
        excluded_names=st.lists(_valid_names, min_size=1, max_size=4, unique=True),
    )
    def test_prefilter_rerun_on_mtime_change_for_cached_decision(
        self,
        excluded_names: list[str],
    ) -> None:
        """For any cached decision where the mtime differs, the provider
        SHALL re-run the pre-filter.

        **Validates: Requirements 19.4**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            jobs_dir = tmp_path / "jobs"
            jobs_dir.mkdir()
            locator = _make_locator(tmp_path)

            # Create excluded modules
            for name in excluded_names:
                _write_module(jobs_dir, name, [name])

            call_count = [0]
            excluded_set = set(excluded_names)

            class TrackingFilter:
                def should_import(self, source_file: Path) -> bool:
                    call_count[0] += 1
                    return source_file.stem not in excluded_set

            tracking_filter = TrackingFilter()

            # First list_jobs(): populate decision cache
            provider = CachedDirectoryScanProvider(
                directories=[str(jobs_dir)],
                locator=locator,
                pre_filter=tracking_filter,
            )
            provider.list_jobs()

            # Modify one of the excluded files (change mtime)
            target_name = excluded_names[0]
            target_file = jobs_dir / f"{target_name}.py"
            time.sleep(0.05)
            target_file.write_text(
                _build_module_source([target_name]) + "\n# Modified\n",
                encoding="utf-8",
            )

            # Reset counter
            call_count[0] = 0

            # Second list_jobs(): should re-run pre-filter for the modified file
            provider.list_jobs()

            assert call_count[0] >= 1, (
                f"Pre-filter was not re-run after mtime change for "
                f"'{target_name}'. Expected at least 1 call, got 0. "
                f"The cached negative decision should be invalidated "
                f"when mtime changes."
            )
