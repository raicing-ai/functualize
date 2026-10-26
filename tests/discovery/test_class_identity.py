"""A class method's cache identity includes its declaring class."""

from __future__ import annotations

from pathlib import Path

from functualize._discovery.cached_provider import CachedDirectoryScanProvider
from functualize._discovery.collisions import claim_order, resolve_name_collisions
from functualize._discovery.providers import DirectoryScanProvider
from functualize._primitives.locator import ResourceLocator
from functualize._types.descriptors import JobDescriptor
from functualize._types.discovery_report import collecting_discovery_failures


def _provider(tmp_path: Path) -> CachedDirectoryScanProvider:
    cache_dir = tmp_path / "cache"
    locator = (
        ResourceLocator()
        .search_explicit(str(cache_dir))
        .write_to_explicit(str(cache_dir))
    )
    return CachedDirectoryScanProvider(
        directories=[], locator=locator, project_root=tmp_path
    )


def test_distinct_classes_keep_both_method_claims(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    source_file = str(tmp_path / "databases.py")
    descriptors = [
        JobDescriptor(
            name="postgres.start",
            group="postgres",
            source_file=source_file,
            python_name="start",
            owner_class=owner,
        )
        for owner in ("OtherPostgres", "LocalPostgres")
    ]

    for descriptor in descriptors:
        provider._add_entry(descriptor)

    assert set(provider._entries) == {
        f"{source_file}::OtherPostgres.start",
        f"{source_file}::LocalPostgres.start",
    }
    assert len(provider._entries) == 2
    assert [
        descriptor.owner_class for descriptor in sorted(descriptors, key=claim_order)
    ] == [
        "LocalPostgres",
        "OtherPostgres",
    ]
    for descriptor in descriptors:
        assert provider._entry_key(descriptor) == (
            f"{claim_order(descriptor)[0]}::{claim_order(descriptor)[1]}"
        )

    # The strict class-specific diagnostic arrives later; both claims already
    # reach the existing collision resolver instead of being overwritten.
    with collecting_discovery_failures() as findings:
        (winner,) = resolve_name_collisions(provider._entries.values())
    assert winner.owner_class == "OtherPostgres"
    assert len(findings) == 1


def test_plain_function_identity_is_unchanged_on_directory_scan(tmp_path: Path) -> None:
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    source_file = jobs_dir / "plain.py"
    source_file.write_text("def alpha(): pass\n\ndef beta(): pass\n")
    descriptors = DirectoryScanProvider(
        directories=[str(jobs_dir)], project_root=tmp_path
    ).list_jobs()

    assert {descriptor.python_name for descriptor in descriptors} == {"alpha", "beta"}
    assert all(descriptor.owner_class is None for descriptor in descriptors)
    assert {claim_order(descriptor) for descriptor in descriptors} == {
        (str(source_file), "alpha"),
        (str(source_file), "beta"),
    }
    provider = _provider(tmp_path)
    assert {provider._entry_key(descriptor) for descriptor in descriptors} == {
        f"{source_file}::alpha",
        f"{source_file}::beta",
    }
