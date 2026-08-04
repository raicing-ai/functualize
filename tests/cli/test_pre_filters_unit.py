"""Unit tests for individual pre-filter classes.

Tests cover GlobExcludePreFilter, FilePrefixPreFilter, FilePostfixPreFilter,
ImportModulePreFilter, and DecoratorModulePreFilter with valid/invalid patterns,
edge cases, and error handling.

Requirements: 6.1–6.5, 8.1–8.5, 9.2–9.4, 11.1–11.6
"""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize._primitives.pre_filter import (
    DecoratorModulePreFilter,
    FilePostfixPreFilter,
    FilePrefixPreFilter,
    GlobExcludePreFilter,
    ImportModulePreFilter,
)

# ---------------------------------------------------------------------------
# GlobExcludePreFilter
# ---------------------------------------------------------------------------


class TestGlobExcludePreFilter:
    """Unit tests for GlobExcludePreFilter."""

    def test_simple_glob_excludes_py_files_at_root(self, tmp_path: Path) -> None:
        """Simple glob pattern *.py excludes .py files at root."""
        f = tmp_path / "deploy.py"
        f.write_text("")
        filt = GlobExcludePreFilter(patterns=("*.py",), base_dir=tmp_path)
        assert filt.should_import(f) is False

    def test_double_star_recursive_glob_matches_nested(self, tmp_path: Path) -> None:
        """** recursive glob matches nested paths."""
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        f = nested / "deep.py"
        f.write_text("")
        # fnmatch with ** — note fnmatch doesn't do recursive ** like pathlib,
        # but it does match any characters including /
        filt = GlobExcludePreFilter(patterns=("**/deep.py",), base_dir=tmp_path)
        assert filt.should_import(f) is False

    def test_question_mark_single_char_wildcard(self, tmp_path: Path) -> None:
        """? single-char wildcard works."""
        f = tmp_path / "x.py"
        f.write_text("")
        filt = GlobExcludePreFilter(patterns=("?.py",), base_dir=tmp_path)
        assert filt.should_import(f) is False

    def test_question_mark_does_not_match_multi_char(self, tmp_path: Path) -> None:
        """? does not match more than one character."""
        f = tmp_path / "ab.py"
        f.write_text("")
        filt = GlobExcludePreFilter(patterns=("?.py",), base_dir=tmp_path)
        assert filt.should_import(f) is True

    def test_file_not_matching_any_pattern_passes(self, tmp_path: Path) -> None:
        """File not matching any pattern → passes (returns True)."""
        f = tmp_path / "deploy.py"
        f.write_text("")
        filt = GlobExcludePreFilter(patterns=("test_*.py",), base_dir=tmp_path)
        assert filt.should_import(f) is True

    def test_multiple_patterns_file_matches_one_excluded(self, tmp_path: Path) -> None:
        """Multiple patterns, file matches one → excluded."""
        f = tmp_path / "conftest.py"
        f.write_text("")
        filt = GlobExcludePreFilter(
            patterns=("test_*.py", "conftest.py", "*.bak"), base_dir=tmp_path
        )
        assert filt.should_import(f) is False

    def test_empty_pattern_in_list_raises_valueerror(self, tmp_path: Path) -> None:
        """Empty pattern in list → raises ValueError at construction."""
        with pytest.raises(ValueError, match="non-empty"):
            GlobExcludePreFilter(patterns=("valid", ""), base_dir=tmp_path)

    def test_non_string_pattern_raises_valueerror(self, tmp_path: Path) -> None:
        """Non-string pattern → raises ValueError."""
        with pytest.raises(ValueError, match="non-empty"):
            GlobExcludePreFilter(
                patterns=(123,),  # type: ignore[arg-type]
                base_dir=tmp_path,
            )

    def test_empty_tuple_raises_valueerror(self, tmp_path: Path) -> None:
        """Empty patterns tuple → raises ValueError."""
        with pytest.raises(ValueError, match="non-empty"):
            GlobExcludePreFilter(patterns=(), base_dir=tmp_path)


# ---------------------------------------------------------------------------
# FilePrefixPreFilter
# ---------------------------------------------------------------------------


class TestFilePrefixPreFilter:
    """Unit tests for FilePrefixPreFilter."""

    def test_stem_starts_with_prefix_passes(self, tmp_path: Path) -> None:
        """File stem starts with prefix → passes."""
        f = tmp_path / "job_deploy.py"
        f.write_text("")
        filt = FilePrefixPreFilter("job_")
        assert filt.should_import(f) is True

    def test_stem_does_not_start_with_prefix_excluded(self, tmp_path: Path) -> None:
        """File stem doesn't start with prefix → excluded."""
        f = tmp_path / "deploy.py"
        f.write_text("")
        filt = FilePrefixPreFilter("job_")
        assert filt.should_import(f) is False

    def test_prefix_in_directory_path_not_stem_excluded(self, tmp_path: Path) -> None:
        """Prefix in directory path but not stem → excluded (operates on stem only)."""
        subdir = tmp_path / "job_modules"
        subdir.mkdir()
        f = subdir / "deploy.py"
        f.write_text("")
        filt = FilePrefixPreFilter("job_")
        assert filt.should_import(f) is False

    def test_prefix_equals_full_stem_passes(self, tmp_path: Path) -> None:
        """Edge case: prefix equals full stem → passes."""
        f = tmp_path / "job_.py"
        f.write_text("")
        filt = FilePrefixPreFilter("job_")
        assert filt.should_import(f) is True

    def test_prefix_equals_exact_stem(self, tmp_path: Path) -> None:
        """Prefix exactly equals the full stem → passes."""
        f = tmp_path / "deploy.py"
        f.write_text("")
        filt = FilePrefixPreFilter("deploy")
        assert filt.should_import(f) is True

    def test_empty_prefix_always_passes(self, tmp_path: Path) -> None:
        """Empty prefix matches everything (str.startswith('') is always True)."""
        f = tmp_path / "anything.py"
        f.write_text("")
        filt = FilePrefixPreFilter("")
        assert filt.should_import(f) is True


# ---------------------------------------------------------------------------
# FilePostfixPreFilter
# ---------------------------------------------------------------------------


class TestFilePostfixPreFilter:
    """Unit tests for FilePostfixPreFilter."""

    def test_stem_ends_with_postfix_passes(self, tmp_path: Path) -> None:
        """File stem ends with postfix → passes."""
        f = tmp_path / "deploy_task.py"
        f.write_text("")
        filt = FilePostfixPreFilter("_task")
        assert filt.should_import(f) is True

    def test_stem_does_not_end_with_postfix_excluded(self, tmp_path: Path) -> None:
        """File stem doesn't end with postfix → excluded."""
        f = tmp_path / "deploy.py"
        f.write_text("")
        filt = FilePostfixPreFilter("_task")
        assert filt.should_import(f) is False

    def test_postfix_in_directory_path_not_stem_excluded(self, tmp_path: Path) -> None:
        """Postfix in directory path but not stem → excluded (operates on stem only)."""
        subdir = tmp_path / "my_task_dir"
        subdir.mkdir()
        f = subdir / "deploy.py"
        f.write_text("")
        filt = FilePostfixPreFilter("_task")
        assert filt.should_import(f) is False

    def test_postfix_equals_full_stem_passes(self, tmp_path: Path) -> None:
        """Edge case: postfix equals full stem → passes."""
        f = tmp_path / "_task.py"
        f.write_text("")
        filt = FilePostfixPreFilter("_task")
        assert filt.should_import(f) is True

    def test_postfix_equals_exact_stem(self, tmp_path: Path) -> None:
        """Postfix exactly equals the full stem → passes."""
        f = tmp_path / "deploy.py"
        f.write_text("")
        filt = FilePostfixPreFilter("deploy")
        assert filt.should_import(f) is True

    def test_empty_postfix_always_passes(self, tmp_path: Path) -> None:
        """Empty postfix matches everything (str.endswith('') is always True)."""
        f = tmp_path / "anything.py"
        f.write_text("")
        filt = FilePostfixPreFilter("")
        assert filt.should_import(f) is True


# ---------------------------------------------------------------------------
# ImportModulePreFilter
# ---------------------------------------------------------------------------


class TestImportModulePreFilter:
    """Unit tests for ImportModulePreFilter."""

    def test_plain_import_passes(self, tmp_path: Path) -> None:
        """`import functualize` → passes."""
        f = tmp_path / "tasks.py"
        f.write_text("import functualize\n\ndef deploy():\n    pass\n")
        assert ImportModulePreFilter("functualize").should_import(f) is True

    def test_from_import_passes(self, tmp_path: Path) -> None:
        """`from functualize import job` → passes."""
        f = tmp_path / "tasks.py"
        f.write_text("from functualize import job\n\ndef deploy():\n    pass\n")
        assert ImportModulePreFilter("functualize").should_import(f) is True

    def test_from_submodule_import_passes(self, tmp_path: Path) -> None:
        """`from functualize.app import FunctualizeApp` → passes."""
        f = tmp_path / "tasks.py"
        f.write_text(
            "from functualize.app import FunctualizeApp\n\ndef deploy():\n    pass\n"
        )
        assert ImportModulePreFilter("functualize").should_import(f) is True

    def test_no_match_excluded(self, tmp_path: Path) -> None:
        """`import os` (no match) → excluded."""
        f = tmp_path / "tasks.py"
        f.write_text("import os\nimport sys\n\ndef deploy():\n    pass\n")
        assert ImportModulePreFilter("functualize").should_import(f) is False

    def test_import_inside_try_except_detected(self, tmp_path: Path) -> None:
        """Import inside `try/except` → still detected."""
        f = tmp_path / "tasks.py"
        f.write_text(
            "try:\n"
            "    import functualize\n"
            "except ImportError:\n"
            "    functualize = None\n"
        )
        assert ImportModulePreFilter("functualize").should_import(f) is True

    def test_import_inside_type_checking_detected(self, tmp_path: Path) -> None:
        """Import inside `if TYPE_CHECKING` → still detected."""
        f = tmp_path / "tasks.py"
        f.write_text(
            "from __future__ import annotations\n"
            "from typing import TYPE_CHECKING\n"
            "\n"
            "if TYPE_CHECKING:\n"
            "    from functualize.job import RunContext\n"
            "\n"
            "def deploy():\n"
            "    pass\n"
        )
        assert ImportModulePreFilter("functualize").should_import(f) is True

    def test_syntax_error_excluded(self, tmp_path: Path) -> None:
        """File with syntax error → excluded (returns False)."""
        f = tmp_path / "broken.py"
        f.write_text("def (\nimport functualize\n")
        assert ImportModulePreFilter("functualize").should_import(f) is False

    def test_non_existent_file_excluded(self, tmp_path: Path) -> None:
        """Non-existent file → excluded (returns False)."""
        f = tmp_path / "missing.py"
        assert ImportModulePreFilter("functualize").should_import(f) is False

    def test_empty_file_excluded(self, tmp_path: Path) -> None:
        """Empty file → excluded (no imports)."""
        f = tmp_path / "empty.py"
        f.write_text("")
        assert ImportModulePreFilter("functualize").should_import(f) is False

    def test_partial_name_no_match(self, tmp_path: Path) -> None:
        """Package name that starts with target but isn't it → excluded."""
        f = tmp_path / "tasks.py"
        f.write_text("import functualize_extra\n")
        assert ImportModulePreFilter("functualize").should_import(f) is False

    def test_import_in_try_finally(self, tmp_path: Path) -> None:
        """Import in try/finally block → still detected."""
        f = tmp_path / "tasks.py"
        f.write_text("try:\n    pass\nfinally:\n    import functualize\n")
        assert ImportModulePreFilter("functualize").should_import(f) is True


# ---------------------------------------------------------------------------
# DecoratorModulePreFilter
# ---------------------------------------------------------------------------


class TestDecoratorModulePreFilter:
    """Unit tests for DecoratorModulePreFilter."""

    def test_bare_decorator_passes(self, tmp_path: Path) -> None:
        """Bare decorator `@job` → passes."""
        f = tmp_path / "tasks.py"
        f.write_text("@job\ndef deploy():\n    pass\n")
        filt = DecoratorModulePreFilter(decorator_names=("job",))
        assert filt.should_import(f) is True

    def test_parameterized_decorator_passes(self, tmp_path: Path) -> None:
        """Parameterized `@job(name=\"x\")` → passes."""
        f = tmp_path / "tasks.py"
        f.write_text('@job(name="x")\ndef deploy():\n    pass\n')
        filt = DecoratorModulePreFilter(decorator_names=("job",))
        assert filt.should_import(f) is True

    def test_no_decorator_excluded(self, tmp_path: Path) -> None:
        """No decorator at all → excluded."""
        f = tmp_path / "tasks.py"
        f.write_text("def deploy():\n    pass\n")
        filt = DecoratorModulePreFilter(decorator_names=("job",))
        assert filt.should_import(f) is False

    def test_different_decorator_excluded(self, tmp_path: Path) -> None:
        """Decorator with different name → excluded."""
        f = tmp_path / "tasks.py"
        f.write_text("@other_decorator\ndef deploy():\n    pass\n")
        filt = DecoratorModulePreFilter(decorator_names=("job",))
        assert filt.should_import(f) is False

    def test_multiple_decorators_one_matches_passes(self, tmp_path: Path) -> None:
        """Multiple decorators, one matches → passes."""
        f = tmp_path / "tasks.py"
        f.write_text("@logging\n@job\ndef deploy():\n    pass\n")
        filt = DecoratorModulePreFilter(decorator_names=("job",))
        assert filt.should_import(f) is True

    def test_syntax_error_excluded(self, tmp_path: Path) -> None:
        """Syntax error file → excluded (returns False)."""
        f = tmp_path / "broken.py"
        f.write_text("def (\n@job\ndef deploy():\n    pass\n")
        filt = DecoratorModulePreFilter(decorator_names=("job",))
        assert filt.should_import(f) is False

    def test_non_existent_file_excluded(self, tmp_path: Path) -> None:
        """Non-existent file → excluded (returns False)."""
        f = tmp_path / "missing.py"
        filt = DecoratorModulePreFilter(decorator_names=("job",))
        assert filt.should_import(f) is False

    def test_multiple_decorator_names_configured(self, tmp_path: Path) -> None:
        """Multiple decorator names configured, matches one → passes."""
        f = tmp_path / "tasks.py"
        f.write_text("@workflow\ndef build():\n    pass\n")
        filt = DecoratorModulePreFilter(decorator_names=("job", "workflow"))
        assert filt.should_import(f) is True

    def test_dotted_decorator_matches_root(self, tmp_path: Path) -> None:
        """Dotted decorator @functualize.job matches root 'functualize'."""
        f = tmp_path / "tasks.py"
        f.write_text("@functualize.job\ndef deploy():\n    pass\n")
        filt = DecoratorModulePreFilter(decorator_names=("functualize",))
        assert filt.should_import(f) is True

    def test_dotted_decorator_parameterized(self, tmp_path: Path) -> None:
        """Dotted parameterized @functualize.job(...) matches root."""
        f = tmp_path / "tasks.py"
        f.write_text('@functualize.job(name="x")\ndef deploy():\n    pass\n')
        filt = DecoratorModulePreFilter(decorator_names=("functualize",))
        assert filt.should_import(f) is True

    def test_async_function_with_decorator(self, tmp_path: Path) -> None:
        """Async function with matching decorator → passes."""
        f = tmp_path / "tasks.py"
        f.write_text("@job\nasync def deploy():\n    pass\n")
        filt = DecoratorModulePreFilter(decorator_names=("job",))
        assert filt.should_import(f) is True

    def test_class_method_decorator_not_detected(self, tmp_path: Path) -> None:
        """Decorator on class method (not top-level) → excluded."""
        f = tmp_path / "tasks.py"
        f.write_text("class Foo:\n    @job\n    def deploy(self):\n        pass\n")
        filt = DecoratorModulePreFilter(decorator_names=("job",))
        assert filt.should_import(f) is False

    def test_empty_file_excluded(self, tmp_path: Path) -> None:
        """Empty file → excluded."""
        f = tmp_path / "empty.py"
        f.write_text("")
        filt = DecoratorModulePreFilter(decorator_names=("job",))
        assert filt.should_import(f) is False
