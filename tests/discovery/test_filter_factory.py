"""Unit tests for build_pre_filter_from_config() factory function."""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize._discovery.filter_factory import build_pre_filter_from_config
from functualize._primitives.pre_filter import (
    AllOf,
    AnyOf,
    ASTModulePreFilter,
    DecoratorModulePreFilter,
    DefaultModulePreFilter,
    DisplayClassPreFilter,
    FilePostfixPreFilter,
    FilePrefixPreFilter,
    GlobExcludePreFilter,
    GroupOptionsPreFilter,
    ImportModulePreFilter,
    MarkerModulePreFilter,
)
from functualize.app.config import DiscoveryConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_filter_types(result: AllOf) -> list[type]:
    """Extract the list of filter types from an AllOf combinator."""
    return [type(f) for f in result._filters]


def _any_of_containing(result: AllOf, member: type) -> AnyOf:
    """The single AnyOf slot whose members include `member`.

    Two positions in the stack are AnyOf slots, so they are addressed by
    content rather than by index.
    """
    slots = [
        f
        for f in result._filters
        if isinstance(f, AnyOf) and any(isinstance(x, member) for x in f._filters)
    ]
    assert len(slots) == 1, f"expected exactly one AnyOf holding {member.__name__}"
    return slots[0]


def _assert_privacy_slot(result: AllOf) -> None:
    """Assert the privacy position holds AnyOf(Default, GroupOptions).

    `_`-prefixed modules are skipped as private, *unless* they declare a
    group's flags — `jobs/deploy/_group.py` is the conventional home for a
    GroupOptions declaration, where the underscore means "defines no jobs",
    not "ignore me entirely".
    """
    slot = _any_of_containing(result, DefaultModulePreFilter)
    assert [type(f) for f in slot._filters] == [
        DefaultModulePreFilter,
        GroupOptionsPreFilter,
    ]


def _assert_ast_slot(result: AllOf) -> None:
    """Assert the AST position holds AnyOf(AST, DisplayClass, GroupOptions).

    A module qualifies with a public function (job candidate), a
    display-provider class, OR a GroupOptions declaration — display-only and
    declaration-only modules must still be imported so the scan's detection
    passes can cache them.
    """
    slot = _any_of_containing(result, ASTModulePreFilter)
    assert [type(f) for f in slot._filters] == [
        ASTModulePreFilter,
        DisplayClassPreFilter,
        GroupOptionsPreFilter,
    ]


# ---------------------------------------------------------------------------
# Baseline config (all None) → DefaultModulePreFilter + ASTModulePreFilter
# ---------------------------------------------------------------------------


class TestBaselineConfig:
    def test_default_config_produces_baseline_filters(self, tmp_path: Path) -> None:
        """DiscoveryConfig() with all defaults → only Default + AST filters."""
        config = DiscoveryConfig()
        result = build_pre_filter_from_config(config, tmp_path)

        assert isinstance(result, AllOf)
        types = _get_filter_types(result)
        assert types == [AnyOf, AnyOf]
        _assert_privacy_slot(result)
        _assert_ast_slot(result)

    def test_baseline_result_is_allof(self, tmp_path: Path) -> None:
        """Factory always returns an AllOf combinator."""
        config = DiscoveryConfig()
        result = build_pre_filter_from_config(config, tmp_path)
        assert isinstance(result, AllOf)


# ---------------------------------------------------------------------------
# Single filter: require_file_import → adds ImportModulePreFilter
# ---------------------------------------------------------------------------


class TestSingleFilterImport:
    def test_require_file_import_adds_import_filter(self, tmp_path: Path) -> None:
        config = DiscoveryConfig(require_file_import="functualize")
        result = build_pre_filter_from_config(config, tmp_path)

        types = _get_filter_types(result)
        assert ImportModulePreFilter in types
        # Baseline filters still present
        _assert_privacy_slot(result)
        _assert_ast_slot(result)


# ---------------------------------------------------------------------------
# Single filter: require_file_prefix → adds FilePrefixPreFilter
# ---------------------------------------------------------------------------


class TestSingleFilterPrefix:
    def test_require_file_prefix_adds_prefix_filter(self, tmp_path: Path) -> None:
        config = DiscoveryConfig(require_file_prefix="job_")
        result = build_pre_filter_from_config(config, tmp_path)

        types = _get_filter_types(result)
        assert FilePrefixPreFilter in types
        _assert_privacy_slot(result)
        _assert_ast_slot(result)


# ---------------------------------------------------------------------------
# Single filter: require_file_postfix → adds FilePostfixPreFilter
# ---------------------------------------------------------------------------


class TestSingleFilterPostfix:
    def test_require_file_postfix_adds_postfix_filter(self, tmp_path: Path) -> None:
        config = DiscoveryConfig(require_file_postfix="_task")
        result = build_pre_filter_from_config(config, tmp_path)

        types = _get_filter_types(result)
        assert FilePostfixPreFilter in types
        _assert_privacy_slot(result)
        _assert_ast_slot(result)


# ---------------------------------------------------------------------------
# Single filter: require_file_marker → adds MarkerModulePreFilter
# ---------------------------------------------------------------------------


class TestSingleFilterMarker:
    def test_require_file_marker_adds_marker_filter(self, tmp_path: Path) -> None:
        config = DiscoveryConfig(require_file_marker="__functualize__")
        result = build_pre_filter_from_config(config, tmp_path)

        types = _get_filter_types(result)
        assert MarkerModulePreFilter in types
        _assert_privacy_slot(result)
        _assert_ast_slot(result)


# ---------------------------------------------------------------------------
# Single filter: require_job_decorators → adds DecoratorModulePreFilter
# ---------------------------------------------------------------------------


class TestSingleFilterDecorators:
    def test_require_job_decorators_adds_decorator_filter(self, tmp_path: Path) -> None:
        config = DiscoveryConfig(require_job_decorators=("job",))
        result = build_pre_filter_from_config(config, tmp_path)

        types = _get_filter_types(result)
        assert DecoratorModulePreFilter in types
        _assert_privacy_slot(result)
        _assert_ast_slot(result)


# ---------------------------------------------------------------------------
# Single filter: exclude_patterns → adds GlobExcludePreFilter first
# ---------------------------------------------------------------------------


class TestSingleFilterExclude:
    def test_exclude_patterns_adds_glob_filter(self, tmp_path: Path) -> None:
        config = DiscoveryConfig(exclude_patterns=("test_*.py",))
        result = build_pre_filter_from_config(config, tmp_path)

        types = _get_filter_types(result)
        assert GlobExcludePreFilter in types
        # GlobExclude should be FIRST in the ordering
        assert types[0] is GlobExcludePreFilter


# ---------------------------------------------------------------------------
# All filters combined → correct ordering
# ---------------------------------------------------------------------------


class TestAllFiltersCombined:
    def test_all_filters_combined_ordering(self, tmp_path: Path) -> None:
        """When all filters are enabled, order is:
        GlobExclude → AnyOf(Default, GroupOptions) → FilePrefix → FilePostfix
        → AnyOf(AST, DisplayClass, GroupOptions) → Import → Marker → Decorator
        """
        config = DiscoveryConfig(
            exclude_patterns=("test_*.py",),
            require_file_prefix="job_",
            require_file_postfix="_task",
            require_file_import="functualize",
            require_file_marker="__functualize__",
            require_job_decorators=("job", "workflow"),
        )
        result = build_pre_filter_from_config(config, tmp_path)

        types = _get_filter_types(result)
        expected = [
            GlobExcludePreFilter,
            AnyOf,
            FilePrefixPreFilter,
            FilePostfixPreFilter,
            AnyOf,
            ImportModulePreFilter,
            MarkerModulePreFilter,
            DecoratorModulePreFilter,
        ]
        assert types == expected

    def test_all_filters_count(self, tmp_path: Path) -> None:
        """All filters enabled produces exactly 8 filters."""
        config = DiscoveryConfig(
            exclude_patterns=("*.pyc",),
            require_file_prefix="job_",
            require_file_postfix="_task",
            require_file_import="functualize",
            require_file_marker="__functualize__",
            require_job_decorators=("job",),
        )
        result = build_pre_filter_from_config(config, tmp_path)

        assert len(result._filters) == 8


# ---------------------------------------------------------------------------
# Empty decorators list raises ValueError
# ---------------------------------------------------------------------------


class TestEmptyDecoratorsRaises:
    def test_empty_tuple_raises_valueerror(self, tmp_path: Path) -> None:
        """require_job_decorators=() (empty, not None) → ValueError."""
        config = DiscoveryConfig(require_job_decorators=())
        with pytest.raises(ValueError, match="at least one decorator name"):
            build_pre_filter_from_config(config, tmp_path)

    def test_none_decorators_does_not_raise(self, tmp_path: Path) -> None:
        """require_job_decorators=None (unset) → no error."""
        config = DiscoveryConfig(require_job_decorators=None)
        result = build_pre_filter_from_config(config, tmp_path)
        assert isinstance(result, AllOf)


# ---------------------------------------------------------------------------
# Verify AND semantics — file must pass ALL filters
# ---------------------------------------------------------------------------


class TestAndSemantics:
    def test_file_passing_all_filters_is_accepted(self, tmp_path: Path) -> None:
        """A file that passes all configured filters is accepted."""
        f = tmp_path / "job_deploy_task.py"
        f.write_text(
            "import functualize\n"
            "__functualize__ = True\n"
            "\n"
            "@job\n"
            "def deploy():\n"
            "    pass\n"
        )

        config = DiscoveryConfig(
            require_file_prefix="job_",
            require_file_postfix="_task",
            require_file_import="functualize",
            require_file_marker="__functualize__",
            require_job_decorators=("job",),
        )
        result = build_pre_filter_from_config(config, tmp_path)
        assert result.should_import(f) is True

    def test_file_failing_one_filter_is_rejected(self, tmp_path: Path) -> None:
        """A file that fails one filter (wrong prefix) is rejected."""
        # File name does NOT start with "job_"
        f = tmp_path / "deploy_task.py"
        f.write_text(
            "import functualize\n"
            "__functualize__ = True\n"
            "\n"
            "@job\n"
            "def deploy():\n"
            "    pass\n"
        )

        config = DiscoveryConfig(
            require_file_prefix="job_",
            require_file_postfix="_task",
            require_file_import="functualize",
            require_file_marker="__functualize__",
            require_job_decorators=("job",),
        )
        result = build_pre_filter_from_config(config, tmp_path)
        assert result.should_import(f) is False

    def test_excluded_file_is_rejected_even_if_other_filters_pass(
        self, tmp_path: Path
    ) -> None:
        """GlobExclude short-circuits: excluded file never reaches other filters."""
        f = tmp_path / "test_deploy.py"
        f.write_text("def deploy():\n    pass\n")

        config = DiscoveryConfig(exclude_patterns=("test_*.py",))
        result = build_pre_filter_from_config(config, tmp_path)
        assert result.should_import(f) is False
