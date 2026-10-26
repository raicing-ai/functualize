"""Class provenance survives descriptor serialization and cache invalidation."""

from __future__ import annotations

import json
from pathlib import Path

from functualize._discovery.cached_provider import CachedDirectoryScanProvider
from functualize._primitives.cache_format import CACHE_FILENAME, CACHE_VERSION
from functualize._primitives.locator import ResourceLocator
from functualize._types.descriptors import JobDescriptor


def test_owner_class_round_trip_preserves_method_identity() -> None:
    descriptor = JobDescriptor(
        name="pg.start",
        group="pg",
        python_name="start",
        owner_class="Postgres",
    )

    payload = descriptor.to_dict()
    assert payload["owner_class"] == "Postgres"
    restored = JobDescriptor.from_dict(payload)
    assert restored.owner_class == "Postgres"
    assert restored.python_name == "start"
    assert restored.attribute_name == "start"


def test_plain_function_and_old_payload_have_no_owner_class() -> None:
    payload = JobDescriptor(name="run", group=None).to_dict()
    assert "owner_class" in payload
    assert payload["owner_class"] is None

    payload.pop("owner_class")
    assert JobDescriptor.from_dict(payload).owner_class is None


def test_cache_reader_refuses_version_22(tmp_path: Path) -> None:
    assert CACHE_VERSION == 23
    cache_dir = tmp_path / ".functualize"
    cache_dir.mkdir()
    cache_file = cache_dir / CACHE_FILENAME
    cache_file.write_text(json.dumps({"version": 22, "entries": {}}))
    locator = (
        ResourceLocator()
        .search_explicit(str(cache_dir))
        .write_to_explicit(str(cache_dir))
    )

    provider = CachedDirectoryScanProvider(
        directories=[], locator=locator, project_root=tmp_path
    )

    assert provider._entries == {}
    assert not cache_file.exists()
