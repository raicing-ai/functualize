"""Unit tests verifying cache serialization preserves qualified names.

Validates Requirement 15: Cached descriptors SHALL serialize/deserialize
with qualified names. The cache `name` field stores the full qualified name
(e.g., "infra.provision", "infra.aws.provision") and is preserved as-is on
round-trip through CachedDirectoryScanProvider and
read_routing_names_from_cache.
"""

from __future__ import annotations

import json
from pathlib import Path

from functualize._discovery.cached_provider import CachedDirectoryScanProvider
from functualize._primitives.cache_format import CACHE_FILENAME
from functualize._primitives.locator import ResourceLocator
from functualize._types.descriptors import JobDescriptor
from functualize.app.utils import read_routing_names_from_cache


def _make_grouped_descriptor(
    name: str,
    group: str,
    source_file: str = "/tmp/project/jobs/infra.py",
    module_path: str = "my_project.jobs.infra",
) -> JobDescriptor:
    """Create a grouped JobDescriptor with a qualified name."""
    return JobDescriptor(
        name=name,
        group=group,
        module_path=module_path,
        source_file=source_file,
        source_mtime=1000.0,
        content_hash="abc123",
        docstring=f"Job {name}",
        config_fields=[],
        dependencies={},
    )


def _make_provider(project_root: Path) -> CachedDirectoryScanProvider:
    """Create a cache provider whose store lives in <root>/.functualize/."""
    cache_dir = project_root / ".functualize"
    locator = (
        ResourceLocator()
        .search_explicit(str(cache_dir))
        .write_to_explicit(str(cache_dir))
    )
    return CachedDirectoryScanProvider(
        directories=[], locator=locator, project_root=project_root
    )


def _cache_path(project_root: Path) -> Path:
    return project_root / ".functualize" / CACHE_FILENAME


class TestCacheSerializationPreservesQualifiedNames:
    """Verify that cache round-trip preserves qualified names like 'infra.provision'."""

    def test_add_and_persist_preserves_qualified_name_in_json(
        self, tmp_path: Path
    ) -> None:
        """Adding a grouped descriptor serializes the qualified name to disk."""
        provider = _make_provider(tmp_path)

        descriptor = _make_grouped_descriptor(
            name="infra.provision",
            group="infra",
            source_file=str(tmp_path / "infra.py"),
        )
        provider._add_entry(descriptor)
        provider._persist_cache()

        # Read the raw JSON and verify the name field is the qualified name
        data = json.loads(_cache_path(tmp_path).read_text(encoding="utf-8"))

        entries = data["entries"]
        assert len(entries) == 1

        # The entry value should have name="infra.provision"
        entry = next(iter(entries.values()))
        assert entry["name"] == "infra.provision"
        assert entry["group"] == "infra"

    def test_round_trip_preserves_qualified_name(self, tmp_path: Path) -> None:
        """Persist → reload: deserialized descriptor retains the qualified name."""
        provider = _make_provider(tmp_path)

        descriptor = _make_grouped_descriptor(
            name="infra.provision",
            group="infra",
            source_file=str(tmp_path / "infra.py"),
        )
        provider._add_entry(descriptor)
        provider._persist_cache()

        # Create a new provider to reload from disk
        provider2 = _make_provider(tmp_path)
        descriptors = list(provider2._by_name.values())

        assert len(descriptors) == 1
        assert descriptors[0].name == "infra.provision"
        assert descriptors[0].group == "infra"
        assert descriptors[0].func_name == "provision"

    def test_nested_group_round_trip(self, tmp_path: Path) -> None:
        """Nested group 'infra.aws' with qualified name 'infra.aws.provision' survives round-trip."""
        provider = _make_provider(tmp_path)

        descriptor = _make_grouped_descriptor(
            name="infra.aws.provision",
            group="infra.aws",
            source_file=str(tmp_path / "aws.py"),
            module_path="my_project.jobs.aws",
        )
        provider._add_entry(descriptor)
        provider._persist_cache()

        provider2 = _make_provider(tmp_path)
        descriptors = list(provider2._by_name.values())

        assert len(descriptors) == 1
        assert descriptors[0].name == "infra.aws.provision"
        assert descriptors[0].group == "infra.aws"
        assert descriptors[0].func_name == "provision"

    def test_read_routing_names_from_cache_reads_qualified_names(
        self, tmp_path: Path
    ) -> None:
        """read_routing_names_from_cache extracts qualified names from serialized cache."""
        provider = _make_provider(tmp_path)

        # Add multiple grouped descriptors
        provider._add_entry(
            _make_grouped_descriptor(
                name="infra.provision",
                group="infra",
                source_file=str(tmp_path / "infra.py"),
            )
        )
        provider._add_entry(
            _make_grouped_descriptor(
                name="infra.teardown",
                group="infra",
                source_file=str(tmp_path / "infra.py"),
                module_path="my_project.jobs.infra",
            )
        )
        provider._add_entry(
            _make_grouped_descriptor(
                name="infra.aws.provision",
                group="infra.aws",
                source_file=str(tmp_path / "aws.py"),
                module_path="my_project.jobs.aws",
            )
        )
        provider._persist_cache()

        # Now use read_routing_names_from_cache on the written file
        result = read_routing_names_from_cache(_cache_path(tmp_path))

        assert result is not None
        job_names, group_names = result

        # All qualified names should be in job_names
        assert "infra.provision" in job_names
        assert "infra.teardown" in job_names
        assert "infra.aws.provision" in job_names

        # Groups and ancestor prefixes should be in group_names
        assert "infra" in group_names
        assert "infra.aws" in group_names

    def test_ungrouped_descriptor_preserves_bare_name(self, tmp_path: Path) -> None:
        """Ungrouped descriptors serialize with bare name and no group."""
        provider = _make_provider(tmp_path)

        descriptor = JobDescriptor(
            name="deploy",
            group=None,
            module_path="my_project.jobs.deploy",
            source_file=str(tmp_path / "deploy.py"),
            source_mtime=1000.0,
            content_hash="abc123",
            docstring="Deploy job",
            config_fields=[],
            dependencies={},
        )
        provider._add_entry(descriptor)
        provider._persist_cache()

        # Reload and verify
        provider2 = _make_provider(tmp_path)
        descriptors = list(provider2._by_name.values())

        assert len(descriptors) == 1
        assert descriptors[0].name == "deploy"
        assert descriptors[0].group is None
        assert descriptors[0].func_name == "deploy"
