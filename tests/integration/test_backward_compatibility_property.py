"""Property-based test for backward compatibility equivalence (Property 13).

Tests that creating a DirectoryScanProvider directly produces the same job names
as using it through the resolution pipeline. This validates that constructor
parameter usage produces the same discovery results as explicit
`add_provider(DirectoryScanProvider(...))`.

The key property: for any list of temp directories with simple job files,
DirectoryScanProvider(dirs).list_jobs() produces consistent results — names
from list_jobs are retrievable via get_job, and registering the provider in
a ResolutionPipeline yields the same set of job names.

**Validates: Requirements 13.4, 13.5**
"""

from __future__ import annotations

import keyword
import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._discovery.pipeline import ResolutionPipeline
from functualize._discovery.providers import DirectoryScanProvider

# --- Strategies ---

# Valid Python identifiers for job function names (simple lowercase names)
job_function_names = st.from_regex(r"[a-z][a-z0-9_]{0,15}", fullmatch=True).filter(
    lambda s: s.isidentifier() and not s.startswith("_") and not keyword.iskeyword(s)
)


@st.composite
def directory_with_jobs(draw: st.DrawFn) -> tuple[str, list[str]]:
    """Strategy that creates a temp directory with simple job Python files.

    Returns a tuple of (directory_path, list_of_expected_job_names).
    Each job file contains a minimal public function that can be discovered
    by scan_directory_for_descriptors.
    """
    # Generate 1-5 unique job names for this directory
    names = draw(st.lists(job_function_names, min_size=1, max_size=5, unique=True))

    # Create a temp directory and write job files
    tmp_dir = tempfile.mkdtemp()

    for name in names:
        job_file = Path(tmp_dir) / f"{name}.py"
        job_file.write_text(f'def {name}():\n    """Job: {name}."""\n    pass\n')

    return tmp_dir, names


@st.composite
def multiple_directories_with_jobs(
    draw: st.DrawFn,
) -> tuple[list[str], list[str]]:
    """Strategy that creates 1-3 temp directories, each with unique job files.

    Returns (list_of_directories, list_of_all_expected_job_names).
    Ensures job names are unique across all directories to avoid duplicates.
    """
    # Generate a pool of unique names and distribute across directories
    num_dirs = draw(st.integers(min_value=1, max_value=3))
    total_names = draw(
        st.lists(
            job_function_names,
            min_size=num_dirs,
            max_size=num_dirs * 4,
            unique=True,
        )
    )

    # Distribute names across directories (at least 1 per directory)
    dirs: list[str] = []
    all_names: list[str] = []

    # Ensure at least 1 name per directory
    remaining_names = list(total_names)
    for i in range(num_dirs):
        tmp_dir = tempfile.mkdtemp()
        dirs.append(tmp_dir)

        # Give at least 1 name to this directory
        if i < num_dirs - 1:
            # Distribute names: give 1-3 to this dir, keep rest for remaining
            names_for_dir_count = draw(
                st.integers(
                    min_value=1,
                    max_value=max(1, len(remaining_names) - (num_dirs - i - 1)),
                )
            )
        else:
            names_for_dir_count = len(remaining_names)

        names_for_dir = remaining_names[:names_for_dir_count]
        remaining_names = remaining_names[names_for_dir_count:]

        for name in names_for_dir:
            job_file = Path(tmp_dir) / f"{name}.py"
            job_file.write_text(f'def {name}():\n    """Job: {name}."""\n    pass\n')
            all_names.append(name)

    return dirs, all_names


# --- Property 13: Backward compatibility equivalence ---


@settings(deadline=30000)
@given(data=multiple_directories_with_jobs())
def test_property_13_constructor_vs_explicit_provider_same_job_names(
    data: tuple[list[str], list[str]],
) -> None:
    """Creating a DirectoryScanProvider with directories produces the same job
    names whether used directly or registered in a ResolutionPipeline via
    add_provider.

    This validates that constructor parameter usage (jobs_directories=dirs)
    produces the same job names as explicit add_provider(DirectoryScanProvider(dirs)).

    **Validates: Requirements 13.4, 13.5**
    """
    dirs, expected_names = data

    # Approach 1: Direct DirectoryScanProvider usage (simulates constructor param)
    direct_provider = DirectoryScanProvider(directories=dirs)
    direct_jobs = direct_provider.list_jobs()
    direct_names = {d.name for d in direct_jobs}

    # Approach 2: Explicit add_provider through ResolutionPipeline
    pipeline = ResolutionPipeline()
    pipeline_provider = DirectoryScanProvider(directories=dirs)
    pipeline.add_provider(pipeline_provider)
    pipeline_jobs = pipeline.resolve_all()
    pipeline_names = {d.name for d in pipeline_jobs}

    # Property: Both approaches produce the same set of job names
    assert direct_names == pipeline_names, (
        f"Direct provider names differ from pipeline names. "
        f"Direct: {sorted(direct_names)}, Pipeline: {sorted(pipeline_names)}"
    )

    # Additionally verify all expected names are discovered
    assert set(expected_names).issubset(direct_names), (
        f"Not all expected names were discovered. "
        f"Expected: {sorted(expected_names)}, Got: {sorted(direct_names)}"
    )


@settings(deadline=30000)
@given(data=multiple_directories_with_jobs())
def test_property_13_list_jobs_get_job_consistency_in_pipeline(
    data: tuple[list[str], list[str]],
) -> None:
    """For any DirectoryScanProvider registered in a ResolutionPipeline,
    every name from resolve_all() is retrievable via resolve_one().

    This ensures the backward compatibility path through the pipeline
    maintains the provider consistency contract.

    **Validates: Requirements 13.4, 13.5**
    """
    dirs, _expected_names = data

    # Set up pipeline with DirectoryScanProvider (as constructor would do)
    pipeline = ResolutionPipeline()
    provider = DirectoryScanProvider(directories=dirs)
    pipeline.add_provider(provider)

    # Resolve all jobs
    all_jobs = pipeline.resolve_all()

    # Property: Every job name from resolve_all is retrievable via resolve_one
    for job in all_jobs:
        resolved = pipeline.resolve_one(job.name)
        assert resolved is not None, (
            f"resolve_one('{job.name}') returned None but name is in resolve_all(). "
            f"All names: {[j.name for j in all_jobs]}"
        )
        assert resolved.name == job.name, (
            f"resolve_one('{job.name}') returned descriptor with name '{resolved.name}'"
        )


@settings(deadline=30000)
@given(data=directory_with_jobs())
def test_property_13_direct_provider_list_get_consistency(
    data: tuple[str, list[str]],
) -> None:
    """For any DirectoryScanProvider created from temp directories,
    list_jobs and get_job are consistent: every name from list_jobs
    is retrievable via get_job, matching what the constructor path would do.

    **Validates: Requirements 13.4, 13.5**
    """
    dir_path, expected_names = data

    # Create provider directly (as constructor sugar would)
    provider = DirectoryScanProvider(directories=[dir_path])
    listed_jobs = provider.list_jobs()
    listed_names = {d.name for d in listed_jobs}

    # Property: Every listed name is retrievable via get_job
    for job in listed_jobs:
        retrieved = provider.get_job(job.name)
        assert retrieved is not None, (
            f"get_job('{job.name}') returned None but name is in list_jobs(). "
            f"Listed names: {sorted(listed_names)}"
        )
        assert retrieved.name == job.name, (
            f"get_job('{job.name}') returned descriptor with name '{retrieved.name}'"
        )

    # Property: All expected job files are discovered
    assert set(expected_names).issubset(listed_names), (
        f"Not all expected names were discovered. "
        f"Expected: {sorted(expected_names)}, Got: {sorted(listed_names)}"
    )
