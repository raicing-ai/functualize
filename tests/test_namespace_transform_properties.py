"""Property-based tests for NamespaceTransform (Property 17).

Tests:
- Property 17: NamespaceTransform prefix/strip round-trip

# Feature: unified-architecture-redesign, Property 17
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._discovery.transforms import NamespaceTransform
from functualize._types.descriptors import JobDescriptor
from functualize._types.naming import normalize_name

# =============================================================================
# Strategies
# =============================================================================

# Strategy: non-empty namespace prefix strings (valid identifiers, no dots)
_namespace_strategy = st.from_regex(r"[a-z][a-z0-9_]{0,15}", fullmatch=True)

# Strategy: non-empty job name strings (valid identifiers, no dots)
_job_name_strategy = st.from_regex(r"[a-z][a-z0-9_]{0,15}", fullmatch=True)


def _make_descriptor(name: str) -> JobDescriptor:
    """Create a minimal JobDescriptor with the given name."""
    return JobDescriptor(
        name=name,
        group=None,
        module_path="__test__.module",
        source_file="<test>",
        source_mtime=0.0,
        content_hash="abc123",
        docstring=None,
        config_fields=[],
        dependencies={},
        metadata=None,
    )


# =============================================================================
# Property 17: NamespaceTransform prefix/strip round-trip
# =============================================================================


class TestNamespaceTransformPrefixStripRoundTrip:
    """Property 17: NamespaceTransform prefix/strip round-trip.

    For any namespace string ns and any JobDescriptor with name n,
    NamespaceTransform(ns).transform_list([desc]) SHALL produce a descriptor
    named `normalize_name(f"{ns}.{n}")`. Conversely, transform_get on that
    name SHALL strip the prefix before delegation and re-add it to the result.

    The *prefix* is canonicalized (a namespace is a group segment as far as
    the CLI is concerned), so a prefix of `a_` namespaces under `a`. The job
    name is passed through untouched — descriptors arrive already canonical
    from discovery.

    **Validates: Requirements 24.1, 24.2, 24.3, 24.4**
    """

    @given(ns=_namespace_strategy, name=_job_name_strategy)
    @settings(max_examples=200)
    def test_transform_list_produces_prefixed_name(self, ns: str, name: str):
        """transform_list produces descriptors with name "{ns}.{name}".

        **Validates: Requirements 24.1, 24.2, 24.3**
        """
        transform = NamespaceTransform(prefix=ns)
        desc = _make_descriptor(name)

        result = transform.transform_list([desc])

        assert len(result) == 1
        assert result[0].name == f"{normalize_name(ns)}.{name}"

    @given(ns=_namespace_strategy, name=_job_name_strategy)
    @settings(max_examples=200)
    def test_transform_get_with_prefixed_name_returns_prefixed_descriptor(
        self, ns: str, name: str
    ):
        """transform_get with prefixed name returns descriptor with prefixed name.

        **Validates: Requirements 24.3, 24.4**
        """
        transform = NamespaceTransform(prefix=ns)
        desc = _make_descriptor(name)
        prefixed_name = f"{normalize_name(ns)}.{name}"

        result = transform.transform_get(prefixed_name, desc)

        assert result is not None
        assert result.name == prefixed_name

    @given(ns=_namespace_strategy, name=_job_name_strategy)
    @settings(max_examples=200)
    def test_transform_get_with_non_prefixed_name_returns_none(
        self, ns: str, name: str
    ):
        """transform_get with non-prefixed name returns None.

        **Validates: Requirements 24.4**
        """
        transform = NamespaceTransform(prefix=ns)
        desc = _make_descriptor(name)

        # Pass the raw name (not prefixed) — should return None
        # unless name accidentally starts with "{ns}."
        if not name.startswith(f"{ns}."):
            result = transform.transform_get(name, desc)
            assert result is None

    @given(ns=_namespace_strategy, name=_job_name_strategy)
    @settings(max_examples=200)
    def test_transform_list_and_get_roundtrip_consistency(self, ns: str, name: str):
        """transform_list and transform_get produce consistent prefixed names.

        **Validates: Requirements 24.1, 24.3, 24.4**
        """
        transform = NamespaceTransform(prefix=ns)
        desc = _make_descriptor(name)

        # transform_list produces prefixed descriptor
        listed = transform.transform_list([desc])
        assert len(listed) == 1
        prefixed_name = listed[0].name

        # transform_get with the prefixed name returns descriptor with
        # same prefixed name
        got = transform.transform_get(prefixed_name, desc)
        assert got is not None
        assert got.name == prefixed_name

    @given(ns=_namespace_strategy)
    @settings(max_examples=100)
    def test_transform_get_with_none_descriptor_returns_none(self, ns: str):
        """transform_get returns None when descriptor is None.

        **Validates: Requirements 24.4**
        """
        transform = NamespaceTransform(prefix=ns)
        prefixed_name = f"{ns}.somejob"

        result = transform.transform_get(prefixed_name, None)
        assert result is None

    @given(
        ns=_namespace_strategy,
        names=st.lists(_job_name_strategy, min_size=1, max_size=10),
    )
    @settings(max_examples=200)
    def test_transform_list_preserves_count(self, ns: str, names: list[str]):
        """transform_list preserves the number of descriptors in the list.

        **Validates: Requirements 24.1, 24.3**
        """
        transform = NamespaceTransform(prefix=ns)
        descs = [_make_descriptor(n) for n in names]

        result = transform.transform_list(descs)

        assert len(result) == len(names)
        for original, transformed in zip(names, result, strict=False):
            assert transformed.name == f"{normalize_name(ns)}.{original}"
