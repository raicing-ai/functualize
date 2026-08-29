"""Unit tests for the discovery-config cache fingerprint.

The fingerprint is what makes the discovery cache filter-aware. Its one hard
requirement is that any change to an effective filter setting changes the digest
— including the change from "not configured" (``None``) to "configured empty"
(``()`` / ``""``), which mean different things to the filter factory.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from functualize._discovery.filter_factory import (
    _DISCOVERY_FINGERPRINT_FIELDS,
    discovery_hash_from_config,
)
from functualize._primitives.cache_format import compute_discovery_hash
from functualize.app.config import DiscoveryConfig

_SAMPLE_VALUES: dict[str, object] = {
    "exclude_patterns": ("test_*.py",),
    "extra_directories": ("ops",),
    "require_file_prefix": "job_",
    "require_file_postfix": "_job",
    "require_file_import": "functualize",
    "require_file_marker": "__functualize__",
    "require_job_decorators": ("job",),
    "require_job_prefix": "do_",
    "require_job_postfix": "_task",
}


class TestComputeDiscoveryHash:
    def test_returns_sha256_prefixed_digest(self) -> None:
        result = compute_discovery_hash([("exclude_patterns", ("a",))])
        assert result.startswith("sha256:")
        assert len(result) == len("sha256:") + 64

    def test_field_order_does_not_change_the_digest(self) -> None:
        forward = compute_discovery_hash([("a", "1"), ("b", "2")])
        reversed_ = compute_discovery_hash([("b", "2"), ("a", "1")])
        assert forward == reversed_

    def test_none_and_empty_sequence_hash_differently(self) -> None:
        """``None`` means "no constraint"; ``()`` means "configured empty".

        ``require_job_decorators=()`` even raises in the filter factory, so
        collapsing the two here would fingerprint two different filter stacks
        identically.
        """
        assert compute_discovery_hash([("f", None)]) != compute_discovery_hash(
            [("f", ())]
        )

    def test_none_and_empty_string_hash_differently(self) -> None:
        assert compute_discovery_hash([("f", None)]) != compute_discovery_hash(
            [("f", "")]
        )

    def test_sequence_boundaries_are_unambiguous(self) -> None:
        """``("a", "b")`` must not collide with ``("a,b",)``."""
        assert compute_discovery_hash([("f", ("a", "b"))]) != compute_discovery_hash(
            [("f", ("a,b",))]
        )

    def test_field_name_is_part_of_the_digest(self) -> None:
        assert compute_discovery_hash([("a", "x")]) != compute_discovery_hash(
            [("b", "x")]
        )


class TestDiscoveryHashFromConfig:
    def test_default_config_is_stable(self) -> None:
        assert discovery_hash_from_config(DiscoveryConfig()) == (
            discovery_hash_from_config(DiscoveryConfig())
        )

    def test_none_config_matches_the_all_unset_config(self) -> None:
        """A provider with no config must agree with one holding a default config.

        Otherwise the booted app and a bare provider would invalidate each
        other's cache on every alternation.
        """
        assert discovery_hash_from_config(None) == discovery_hash_from_config(
            DiscoveryConfig()
        )

    @pytest.mark.parametrize("field", [n for n, _ in _DISCOVERY_FINGERPRINT_FIELDS])
    def test_every_fingerprinted_field_changes_the_digest(self, field: str) -> None:
        """Each of the nine settings must be covered, one at a time.

        A field consumed by the filter builders but missing from the fingerprint
        is exactly the defect this feature fixes, one setting narrower.
        """
        baseline = discovery_hash_from_config(DiscoveryConfig())
        changed = replace(DiscoveryConfig(), **{field: _SAMPLE_VALUES[field]})
        assert discovery_hash_from_config(changed) != baseline

    def test_fingerprint_covers_every_discovery_config_field(self) -> None:
        """Guard against a tenth setting being added and silently uncovered."""
        declared = set(DiscoveryConfig.__dataclass_fields__)
        assert declared == {name for name, _ in _DISCOVERY_FINGERPRINT_FIELDS}

    def test_fingerprint_defaults_match_discovery_config(self) -> None:
        """The repeated defaults must track the dataclass they mirror.

        `_discovery` cannot import `app.config` at runtime, so the defaults are
        duplicated. This pins the duplicate: changing a DiscoveryConfig default
        without updating the fingerprint fails here instead of silently
        fingerprinting an unset config as a configured one.
        """
        actual = DiscoveryConfig()
        for name, default in _DISCOVERY_FINGERPRINT_FIELDS:
            assert getattr(actual, name) == default, name
