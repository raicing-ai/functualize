"""Unit tests for qualified_name utility."""

from __future__ import annotations

import pytest

from functualize._discovery.naming import qualified_name


class TestQualifiedNameUngrouped:
    """Tests for ungrouped jobs (group=None)."""

    def test_none_group_returns_bare_func_name(self) -> None:
        assert qualified_name(None, "deploy") == "deploy"


class TestQualifiedNameSingleLevel:
    """Tests for single-level group."""

    def test_single_level_group(self) -> None:
        assert qualified_name("infra", "provision") == "infra.provision"


class TestQualifiedNameNested:
    """Tests for nested (multi-level) groups."""

    def test_nested_group(self) -> None:
        assert qualified_name("infra.aws", "provision") == "infra.aws.provision"


class TestQualifiedNameInvalidInputs:
    """Tests for invalid inputs that should raise ValueError."""

    def test_dot_in_func_name_raises(self) -> None:
        with pytest.raises(ValueError, match="must not contain '\\.'"):
            qualified_name(None, "foo.bar")

    def test_empty_segment_in_group_raises(self) -> None:
        with pytest.raises(ValueError, match="valid identifier"):
            qualified_name("infra..aws", "provision")

    def test_empty_group_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty string"):
            qualified_name("", "provision")

    def test_empty_func_name_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty string"):
            qualified_name(None, "")


class TestNormalizeSegment:
    """Canonical identity: lowercase, hyphenated (ratified 2026-07-21).

    Python identifiers cannot contain hyphens and CLI names conventionally do,
    so without one canonical form the same job has two spellings and each
    consumer picks one. That is the divergence class that already produced
    three disagreeing dependency resolvers in this codebase.
    """

    def test_underscores_become_hyphens(self) -> None:
        from functualize._discovery.naming import normalize_segment

        assert normalize_segment("my_job_name") == "my-job-name"

    def test_camel_case_becomes_hyphenated(self) -> None:
        from functualize._discovery.naming import normalize_segment

        assert normalize_segment("MyJobName") == "my-job-name"

    def test_spaces_become_hyphens(self) -> None:
        from functualize._discovery.naming import normalize_segment

        assert normalize_segment("my job") == "my-job"

    def test_an_already_canonical_name_is_unchanged(self) -> None:
        """Normalization must be idempotent, or repeated passes drift."""
        from functualize._discovery.naming import normalize_segment

        assert normalize_segment("my-job-name") == "my-job-name"
        assert normalize_segment(normalize_segment("MyJob")) == "my-job"

    def test_leading_and_trailing_separators_are_trimmed(self) -> None:
        from functualize._discovery.naming import normalize_segment

        assert normalize_segment("_private_") == "private"


class TestResolveName:
    """One naming policy, shared by the dependency graph and (later) the trie."""

    def test_an_exact_match_wins(self) -> None:
        from functualize._discovery.naming import resolve_name

        assert resolve_name("a.build", ["a.build", "b.build"]) == "a.build"

    def test_a_leaf_name_resolves_to_its_qualified_form(self) -> None:
        from functualize._discovery.naming import resolve_name

        assert resolve_name("compile", ["build.compile", "other"]) == "build.compile"

    def test_an_ambiguous_leaf_raises(self) -> None:
        """Guessing between two groups would silently pick one."""
        import pytest

        from functualize._discovery.naming import resolve_name

        with pytest.raises(LookupError, match="ambiguous"):
            resolve_name("build", ["a.build", "b.build"])

    def test_an_unknown_name_raises(self) -> None:
        import pytest

        from functualize._discovery.naming import resolve_name

        with pytest.raises(LookupError, match="matches no known name"):
            resolve_name("nope", ["a.build"])
