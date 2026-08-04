"""Unit tests for functualize.primitives.pre_filter module."""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize._primitives.pre_filter import (
    AllOf,
    AnyOf,
    ASTModulePreFilter,
    DefaultModulePreFilter,
    GlobExcludePreFilter,
    ImportModulePreFilter,
    MarkerModulePreFilter,
    ModulePreFilter,
    NoneOf,
)

# ---------------------------------------------------------------------------
# Protocol structural typing
# ---------------------------------------------------------------------------


class _CustomFilter:
    """A custom filter that satisfies ModulePreFilter via structural typing."""

    def should_import(self, source_file: Path) -> bool:
        return True


class _NotAFilter:
    """Does not satisfy ModulePreFilter — wrong method name."""

    def check_file(self, source_file: Path) -> bool:
        return True


class TestProtocol:
    def test_runtime_checkable_with_builtin(self) -> None:
        assert isinstance(DefaultModulePreFilter(), ModulePreFilter)

    def test_runtime_checkable_with_custom(self) -> None:
        assert isinstance(_CustomFilter(), ModulePreFilter)

    def test_runtime_checkable_rejects_non_conforming(self) -> None:
        assert not isinstance(_NotAFilter(), ModulePreFilter)

    def test_combinators_satisfy_protocol(self) -> None:
        assert isinstance(AllOf(), ModulePreFilter)
        assert isinstance(AnyOf(), ModulePreFilter)
        assert isinstance(NoneOf(), ModulePreFilter)

    def test_ast_filter_satisfies_protocol(self) -> None:
        assert isinstance(ASTModulePreFilter(), ModulePreFilter)

    def test_marker_filter_satisfies_protocol(self) -> None:
        assert isinstance(MarkerModulePreFilter(), ModulePreFilter)


# ---------------------------------------------------------------------------
# DefaultModulePreFilter
# ---------------------------------------------------------------------------


class TestDefaultModulePreFilter:
    def test_allows_normal_file(self, tmp_path: Path) -> None:
        f = tmp_path / "deploy.py"
        f.write_text("x = 1")
        assert DefaultModulePreFilter().should_import(f) is True

    def test_skips_underscore_prefixed(self, tmp_path: Path) -> None:
        f = tmp_path / "_internal.py"
        f.write_text("x = 1")
        assert DefaultModulePreFilter().should_import(f) is False

    def test_skips_dunder_prefixed(self, tmp_path: Path) -> None:
        f = tmp_path / "__main__.py"
        f.write_text("x = 1")
        assert DefaultModulePreFilter().should_import(f) is False


# ---------------------------------------------------------------------------
# ASTModulePreFilter
# ---------------------------------------------------------------------------


class TestASTModulePreFilter:
    def test_allows_file_with_public_function(self, tmp_path: Path) -> None:
        f = tmp_path / "tasks.py"
        f.write_text("def deploy():\n    pass\n")
        assert ASTModulePreFilter().should_import(f) is True

    def test_allows_file_with_async_function(self, tmp_path: Path) -> None:
        f = tmp_path / "tasks.py"
        f.write_text("async def deploy():\n    pass\n")
        assert ASTModulePreFilter().should_import(f) is True

    def test_rejects_file_with_only_private_functions(self, tmp_path: Path) -> None:
        f = tmp_path / "tasks.py"
        f.write_text("def _helper():\n    pass\n")
        assert ASTModulePreFilter().should_import(f) is False

    def test_rejects_file_with_no_functions(self, tmp_path: Path) -> None:
        f = tmp_path / "config.py"
        f.write_text("X = 42\n")
        assert ASTModulePreFilter().should_import(f) is False

    def test_rejects_syntax_error(self, tmp_path: Path) -> None:
        f = tmp_path / "broken.py"
        f.write_text("def (\n")
        assert ASTModulePreFilter().should_import(f) is False

    def test_rejects_nonexistent_file(self, tmp_path: Path) -> None:
        f = tmp_path / "missing.py"
        assert ASTModulePreFilter().should_import(f) is False

    def test_ignores_nested_functions(self, tmp_path: Path) -> None:
        f = tmp_path / "module.py"
        f.write_text("class Foo:\n    def bar(self):\n        pass\n")
        # Only top-level function defs count
        assert ASTModulePreFilter().should_import(f) is False


# ---------------------------------------------------------------------------
# MarkerModulePreFilter
# ---------------------------------------------------------------------------


class TestMarkerModulePreFilter:
    def test_allows_file_with_marker(self, tmp_path: Path) -> None:
        f = tmp_path / "tasks.py"
        f.write_text("__functualize__ = True\n\ndef deploy():\n    pass\n")
        assert MarkerModulePreFilter().should_import(f) is True

    def test_allows_file_with_annotated_marker(self, tmp_path: Path) -> None:
        f = tmp_path / "tasks.py"
        f.write_text("__functualize__: bool = True\n")
        assert MarkerModulePreFilter().should_import(f) is True

    def test_rejects_file_without_marker(self, tmp_path: Path) -> None:
        f = tmp_path / "tasks.py"
        f.write_text("def deploy():\n    pass\n")
        assert MarkerModulePreFilter().should_import(f) is False

    def test_custom_marker_name(self, tmp_path: Path) -> None:
        f = tmp_path / "tasks.py"
        f.write_text("JOBS = True\n")
        assert MarkerModulePreFilter(marker="JOBS").should_import(f) is True

    def test_custom_marker_not_present(self, tmp_path: Path) -> None:
        f = tmp_path / "tasks.py"
        f.write_text("OTHER = True\n")
        assert MarkerModulePreFilter(marker="JOBS").should_import(f) is False

    def test_rejects_syntax_error(self, tmp_path: Path) -> None:
        f = tmp_path / "broken.py"
        f.write_text("def (\n")
        assert MarkerModulePreFilter().should_import(f) is False

    def test_rejects_nonexistent_file(self, tmp_path: Path) -> None:
        f = tmp_path / "missing.py"
        assert MarkerModulePreFilter().should_import(f) is False


# ---------------------------------------------------------------------------
# ImportModulePreFilter
# ---------------------------------------------------------------------------


class TestImportModulePreFilter:
    def test_detects_plain_import(self, tmp_path: Path) -> None:
        f = tmp_path / "tasks.py"
        f.write_text("import functualize\n\ndef deploy():\n    pass\n")
        assert ImportModulePreFilter("functualize").should_import(f) is True

    def test_detects_from_import(self, tmp_path: Path) -> None:
        f = tmp_path / "tasks.py"
        f.write_text("from functualize import job\n\ndef deploy():\n    pass\n")
        assert ImportModulePreFilter("functualize").should_import(f) is True

    def test_detects_submodule_import(self, tmp_path: Path) -> None:
        f = tmp_path / "tasks.py"
        f.write_text("import functualize.job\n\ndef deploy():\n    pass\n")
        assert ImportModulePreFilter("functualize").should_import(f) is True

    def test_detects_from_submodule_import(self, tmp_path: Path) -> None:
        f = tmp_path / "tasks.py"
        f.write_text(
            "from functualize.job import RunContext\n\ndef deploy():\n    pass\n"
        )
        assert ImportModulePreFilter("functualize").should_import(f) is True

    def test_rejects_no_matching_import(self, tmp_path: Path) -> None:
        f = tmp_path / "tasks.py"
        f.write_text("import os\nimport sys\n\ndef deploy():\n    pass\n")
        assert ImportModulePreFilter("functualize").should_import(f) is False

    def test_rejects_partial_name_match(self, tmp_path: Path) -> None:
        """'functualize' filter should NOT match 'functualize_extra'."""
        f = tmp_path / "tasks.py"
        f.write_text("import functualize_extra\n\ndef deploy():\n    pass\n")
        assert ImportModulePreFilter("functualize").should_import(f) is False

    def test_detects_import_in_try_except(self, tmp_path: Path) -> None:
        f = tmp_path / "tasks.py"
        f.write_text("try:\n    import functualize\nexcept ImportError:\n    pass\n")
        assert ImportModulePreFilter("functualize").should_import(f) is True

    def test_detects_import_in_except_handler(self, tmp_path: Path) -> None:
        f = tmp_path / "tasks.py"
        f.write_text(
            "try:\n    import something\nexcept ImportError:\n    import functualize\n"
        )
        assert ImportModulePreFilter("functualize").should_import(f) is True

    def test_detects_import_in_if_block(self, tmp_path: Path) -> None:
        f = tmp_path / "tasks.py"
        f.write_text(
            "import sys\nif sys.version_info >= (3, 11):\n"
            "    from functualize import job\n"
        )
        assert ImportModulePreFilter("functualize").should_import(f) is True

    def test_detects_import_in_if_else(self, tmp_path: Path) -> None:
        f = tmp_path / "tasks.py"
        f.write_text(
            "import sys\nif sys.version_info >= (3, 11):\n"
            "    pass\nelse:\n    from functualize import job\n"
        )
        assert ImportModulePreFilter("functualize").should_import(f) is True

    def test_rejects_syntax_error(self, tmp_path: Path) -> None:
        f = tmp_path / "broken.py"
        f.write_text("def (\n")
        assert ImportModulePreFilter("functualize").should_import(f) is False

    def test_rejects_nonexistent_file(self, tmp_path: Path) -> None:
        f = tmp_path / "missing.py"
        assert ImportModulePreFilter("functualize").should_import(f) is False

    def test_rejects_unreadable_file(self, tmp_path: Path) -> None:
        f = tmp_path / "secret.py"
        f.write_text("import functualize\n")
        f.chmod(0o000)
        result = ImportModulePreFilter("functualize").should_import(f)
        f.chmod(0o644)  # restore for cleanup
        assert result is False

    def test_satisfies_protocol(self) -> None:
        assert isinstance(ImportModulePreFilter("pkg"), ModulePreFilter)

    def test_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.py"
        f.write_text("")
        assert ImportModulePreFilter("functualize").should_import(f) is False


# ---------------------------------------------------------------------------
# Combinators
# ---------------------------------------------------------------------------


class _AlwaysTrue:
    def should_import(self, source_file: Path) -> bool:
        return True


class _AlwaysFalse:
    def should_import(self, source_file: Path) -> bool:
        return False


class TestAllOf:
    def test_empty_returns_true(self, tmp_path: Path) -> None:
        f = tmp_path / "x.py"
        f.write_text("")
        assert AllOf().should_import(f) is True

    def test_all_true(self, tmp_path: Path) -> None:
        f = tmp_path / "x.py"
        f.write_text("")
        assert AllOf(_AlwaysTrue(), _AlwaysTrue()).should_import(f) is True

    def test_one_false(self, tmp_path: Path) -> None:
        f = tmp_path / "x.py"
        f.write_text("")
        assert AllOf(_AlwaysTrue(), _AlwaysFalse()).should_import(f) is False

    def test_all_false(self, tmp_path: Path) -> None:
        f = tmp_path / "x.py"
        f.write_text("")
        assert AllOf(_AlwaysFalse(), _AlwaysFalse()).should_import(f) is False


class TestAnyOf:
    def test_empty_returns_false(self, tmp_path: Path) -> None:
        f = tmp_path / "x.py"
        f.write_text("")
        assert AnyOf().should_import(f) is False

    def test_all_true(self, tmp_path: Path) -> None:
        f = tmp_path / "x.py"
        f.write_text("")
        assert AnyOf(_AlwaysTrue(), _AlwaysTrue()).should_import(f) is True

    def test_one_true(self, tmp_path: Path) -> None:
        f = tmp_path / "x.py"
        f.write_text("")
        assert AnyOf(_AlwaysFalse(), _AlwaysTrue()).should_import(f) is True

    def test_all_false(self, tmp_path: Path) -> None:
        f = tmp_path / "x.py"
        f.write_text("")
        assert AnyOf(_AlwaysFalse(), _AlwaysFalse()).should_import(f) is False


class TestNoneOf:
    def test_empty_returns_true(self, tmp_path: Path) -> None:
        f = tmp_path / "x.py"
        f.write_text("")
        assert NoneOf().should_import(f) is True

    def test_all_true_filters(self, tmp_path: Path) -> None:
        f = tmp_path / "x.py"
        f.write_text("")
        assert NoneOf(_AlwaysTrue(), _AlwaysTrue()).should_import(f) is False

    def test_one_true_filter(self, tmp_path: Path) -> None:
        f = tmp_path / "x.py"
        f.write_text("")
        assert NoneOf(_AlwaysFalse(), _AlwaysTrue()).should_import(f) is False

    def test_all_false_filters(self, tmp_path: Path) -> None:
        f = tmp_path / "x.py"
        f.write_text("")
        assert NoneOf(_AlwaysFalse(), _AlwaysFalse()).should_import(f) is True


# ---------------------------------------------------------------------------
# Combinator composition
# ---------------------------------------------------------------------------


class TestCombinatorComposition:
    def test_nested_combinators(self, tmp_path: Path) -> None:
        """AllOf(AnyOf(...), NoneOf(...)) composes correctly."""
        f = tmp_path / "deploy.py"
        f.write_text("def deploy():\n    pass\n")

        combined = AllOf(
            AnyOf(DefaultModulePreFilter(), ASTModulePreFilter()),
            NoneOf(MarkerModulePreFilter(marker="SKIP")),
        )
        assert combined.should_import(f) is True

    def test_nested_all_blocked(self, tmp_path: Path) -> None:
        """AllOf blocks when inner NoneOf fails."""
        f = tmp_path / "deploy.py"
        f.write_text("SKIP = True\ndef deploy():\n    pass\n")

        combined = AllOf(
            AnyOf(DefaultModulePreFilter(), ASTModulePreFilter()),
            NoneOf(MarkerModulePreFilter(marker="SKIP")),
        )
        assert combined.should_import(f) is False


# ---------------------------------------------------------------------------
# GlobExcludePreFilter
# ---------------------------------------------------------------------------


class TestGlobExcludePreFilter:
    def test_satisfies_protocol(self, tmp_path: Path) -> None:
        f = GlobExcludePreFilter(patterns=("*.py",), base_dir=tmp_path)
        assert isinstance(f, ModulePreFilter)

    def test_excludes_matching_file(self, tmp_path: Path) -> None:
        f = tmp_path / "test_deploy.py"
        f.write_text("")
        filt = GlobExcludePreFilter(patterns=("test_*.py",), base_dir=tmp_path)
        assert filt.should_import(f) is False

    def test_allows_non_matching_file(self, tmp_path: Path) -> None:
        f = tmp_path / "deploy.py"
        f.write_text("")
        filt = GlobExcludePreFilter(patterns=("test_*.py",), base_dir=tmp_path)
        assert filt.should_import(f) is True

    def test_excludes_with_star_wildcard(self, tmp_path: Path) -> None:
        f = tmp_path / "migrations" / "001_init.py"
        f.parent.mkdir()
        f.write_text("")
        filt = GlobExcludePreFilter(patterns=("migrations/*.py",), base_dir=tmp_path)
        assert filt.should_import(f) is False

    def test_excludes_with_question_mark_wildcard(self, tmp_path: Path) -> None:
        f = tmp_path / "a.py"
        f.write_text("")
        filt = GlobExcludePreFilter(patterns=("?.py",), base_dir=tmp_path)
        assert filt.should_import(f) is False

    def test_question_mark_does_not_match_longer(self, tmp_path: Path) -> None:
        f = tmp_path / "ab.py"
        f.write_text("")
        filt = GlobExcludePreFilter(patterns=("?.py",), base_dir=tmp_path)
        assert filt.should_import(f) is True

    def test_multiple_patterns_any_match_excludes(self, tmp_path: Path) -> None:
        f = tmp_path / "conftest.py"
        f.write_text("")
        filt = GlobExcludePreFilter(
            patterns=("test_*.py", "conftest.py"), base_dir=tmp_path
        )
        assert filt.should_import(f) is False

    def test_multiple_patterns_none_match_allows(self, tmp_path: Path) -> None:
        f = tmp_path / "deploy.py"
        f.write_text("")
        filt = GlobExcludePreFilter(
            patterns=("test_*.py", "conftest.py"), base_dir=tmp_path
        )
        assert filt.should_import(f) is True

    def test_relative_path_matching(self, tmp_path: Path) -> None:
        """Pattern matches against relative path, not absolute."""
        subdir = tmp_path / "jobs" / "sub"
        subdir.mkdir(parents=True)
        f = subdir / "task.py"
        f.write_text("")
        filt = GlobExcludePreFilter(patterns=("jobs/sub/*.py",), base_dir=tmp_path)
        assert filt.should_import(f) is False

    def test_file_outside_base_dir_allowed(self, tmp_path: Path) -> None:
        """Files not under base_dir should be allowed (cannot relativize)."""
        other = tmp_path / "other"
        other.mkdir()
        f = other / "task.py"
        f.write_text("")
        base = tmp_path / "project"
        base.mkdir()
        filt = GlobExcludePreFilter(patterns=("*.py",), base_dir=base)
        assert filt.should_import(f) is True

    def test_raises_on_empty_patterns_tuple(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            GlobExcludePreFilter(patterns=(), base_dir=tmp_path)

    def test_raises_on_empty_string_pattern(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            GlobExcludePreFilter(patterns=("valid", ""), base_dir=tmp_path)

    def test_raises_on_non_string_pattern(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            GlobExcludePreFilter(
                patterns=("valid", None),  # type: ignore[arg-type]
                base_dir=tmp_path,
            )
