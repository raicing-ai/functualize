"""Unit tests for the import_job utility function.

Tests cover:
- Requirement 8.4: Returns single callable for function_name, or list of all public functions when None
- Requirement 8.5: Raises ImportError for non-existent paths
- Requirement 8.6: Raises LookupError for missing function names
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from functualize.app.utils import import_job


@pytest.fixture()
def job_file(tmp_path: Path) -> Path:
    """Create a temporary Python file with multiple job functions."""
    content = textwrap.dedent("""\
        def deploy():
            return "deployed"

        def rollback():
            return "rolled back"

        def _private_helper():
            return "private"

        MY_CONSTANT = 42

        class MyClass:
            pass
    """)
    file = tmp_path / "jobs.py"
    file.write_text(content)
    return file


@pytest.fixture()
def single_job_file(tmp_path: Path) -> Path:
    """Create a temporary Python file with a single job function."""
    content = textwrap.dedent("""\
        def build():
            return "built"
    """)
    file = tmp_path / "single.py"
    file.write_text(content)
    return file


@pytest.fixture()
def empty_job_file(tmp_path: Path) -> Path:
    """Create a temporary Python file with no public functions."""
    content = textwrap.dedent("""\
        _INTERNAL = "value"

        def _helper():
            pass
    """)
    file = tmp_path / "empty_jobs.py"
    file.write_text(content)
    return file


class TestImportJobSingleFunction:
    """Tests for importing a specific function by name (Requirement 8.4)."""

    def test_returns_callable_for_valid_function_name(self, job_file: Path) -> None:
        result = import_job(job_file, "deploy")
        assert callable(result)
        assert result() == "deployed"

    def test_returns_correct_function_among_multiple(self, job_file: Path) -> None:
        result = import_job(job_file, "rollback")
        assert callable(result)
        assert result() == "rolled back"

    def test_accepts_string_path(self, job_file: Path) -> None:
        result = import_job(str(job_file), "deploy")
        assert callable(result)
        assert result() == "deployed"

    def test_accepts_path_object(self, job_file: Path) -> None:
        result = import_job(job_file, "deploy")
        assert callable(result)


class TestImportJobAllFunctions:
    """Tests for importing all public functions (Requirement 8.4)."""

    def test_returns_list_of_callables_when_no_function_name(
        self, job_file: Path
    ) -> None:
        result = import_job(job_file)
        assert isinstance(result, list)
        assert all(callable(f) for f in result)

    def test_returns_only_public_functions(self, job_file: Path) -> None:
        result = import_job(job_file)
        names = [f.__name__ for f in result]
        # Should include public functions
        assert "deploy" in names
        assert "rollback" in names
        # Should exclude private functions
        assert "_private_helper" not in names

    def test_excludes_classes_and_constants(self, job_file: Path) -> None:
        result = import_job(job_file)
        names = [f.__name__ for f in result]
        assert "MyClass" not in names

    def test_returns_empty_list_for_no_public_functions(
        self, empty_job_file: Path
    ) -> None:
        result = import_job(empty_job_file)
        assert isinstance(result, list)
        assert result == []

    def test_returns_single_item_list_for_one_function(
        self, single_job_file: Path
    ) -> None:
        result = import_job(single_job_file)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]() == "built"


class TestImportJobNonExistentPath:
    """Tests for ImportError on non-existent paths (Requirement 8.5)."""

    def test_raises_import_error_for_missing_file(self, tmp_path: Path) -> None:
        bad_path = tmp_path / "nonexistent.py"
        with pytest.raises(ImportError, match="Cannot import job from"):
            import_job(bad_path)

    def test_error_message_includes_path(self, tmp_path: Path) -> None:
        bad_path = tmp_path / "ghost.py"
        with pytest.raises(ImportError, match="ghost.py"):
            import_job(bad_path)

    def test_error_message_includes_file_not_found(self, tmp_path: Path) -> None:
        bad_path = tmp_path / "missing.py"
        with pytest.raises(ImportError, match="file not found"):
            import_job(bad_path)

    def test_raises_import_error_for_string_path(self, tmp_path: Path) -> None:
        bad_path = str(tmp_path / "nope.py")
        with pytest.raises(ImportError):
            import_job(bad_path)


class TestImportJobMissingFunctionName:
    """Tests for LookupError on missing function names (Requirement 8.6)."""

    def test_raises_lookup_error_for_nonexistent_function(self, job_file: Path) -> None:
        with pytest.raises(LookupError):
            import_job(job_file, "nonexistent_function")

    def test_error_message_includes_function_name(self, job_file: Path) -> None:
        with pytest.raises(LookupError, match="no_such_func"):
            import_job(job_file, "no_such_func")

    def test_error_message_includes_module_path(self, job_file: Path) -> None:
        with pytest.raises(LookupError, match="not found in module"):
            import_job(job_file, "missing_fn")

    def test_private_function_accessible_by_explicit_name(self, job_file: Path) -> None:
        """Private functions are accessible when explicitly named (filtering only applies to None case)."""
        result = import_job(job_file, "_private_helper")
        assert callable(result)
        assert result() == "private"


class TestImportJobEdgeCases:
    """Edge case tests for import_job."""

    def test_directory_path_raises_import_error(self, tmp_path: Path) -> None:
        with pytest.raises(ImportError, match="not a file"):
            import_job(tmp_path)

    def test_file_with_syntax_error_raises_import_error(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad_syntax.py"
        bad_file.write_text("def broken(\n")
        with pytest.raises(ImportError, match="Cannot import job from"):
            import_job(bad_file)

    def test_non_callable_attribute_raises_lookup_error(self, job_file: Path) -> None:
        """A non-callable attribute (like MY_CONSTANT) should raise LookupError."""
        with pytest.raises(LookupError):
            import_job(job_file, "MY_CONSTANT")
