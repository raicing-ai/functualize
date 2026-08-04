"""Unit tests for AST extractor edge cases.

Tests extract_first_level_dependencies() with real file structures on disk,
covering all import forms, stdlib/third-party exclusion, error handling,
and the non-transitive/top-level-only guarantees.

Validates: Requirements 10.1–10.7
"""

from __future__ import annotations

import re
from pathlib import Path

from functualize._discovery.ast_extractor import extract_first_level_dependencies

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class TestAbsoluteImports:
    """Test `import X` where X is a local module."""

    def test_import_local_module_as_file(self, tmp_path: Path) -> None:
        """import local_module where local_module.py exists → included."""
        # Create the local module
        (tmp_path / "local_module.py").write_text("x = 1\n")

        # Create source file that imports it
        source = tmp_path / "main.py"
        source.write_text("import local_module\n")

        result = extract_first_level_dependencies(source, tmp_path)

        expected_path = str((tmp_path / "local_module.py").resolve())
        assert expected_path in result
        assert SHA256_PATTERN.match(result[expected_path])

    def test_import_local_package(self, tmp_path: Path) -> None:
        """import local_package where local_package/__init__.py exists → included."""
        pkg = tmp_path / "local_package"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("# package\n")

        source = tmp_path / "main.py"
        source.write_text("import local_package\n")

        result = extract_first_level_dependencies(source, tmp_path)

        expected_path = str((pkg / "__init__.py").resolve())
        assert expected_path in result
        assert SHA256_PATTERN.match(result[expected_path])

    def test_import_dotted_local_module(self, tmp_path: Path) -> None:
        """import pkg.sub where pkg/sub.py exists → included."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "sub.py").write_text("y = 2\n")

        source = tmp_path / "main.py"
        source.write_text("import pkg.sub\n")

        result = extract_first_level_dependencies(source, tmp_path)

        expected_path = str((pkg / "sub.py").resolve())
        assert expected_path in result


class TestFromImports:
    """Test `from X import Y` where X is a local package."""

    def test_from_local_package_import_something(self, tmp_path: Path) -> None:
        """from local_package import something where local_package/__init__.py exists → included."""
        pkg = tmp_path / "local_package"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("something = 42\n")

        source = tmp_path / "main.py"
        source.write_text("from local_package import something\n")

        result = extract_first_level_dependencies(source, tmp_path)

        expected_path = str((pkg / "__init__.py").resolve())
        assert expected_path in result
        assert SHA256_PATTERN.match(result[expected_path])

    def test_from_local_module_import_name(self, tmp_path: Path) -> None:
        """from local_module import func where local_module.py exists → included."""
        (tmp_path / "local_module.py").write_text("def func(): pass\n")

        source = tmp_path / "main.py"
        source.write_text("from local_module import func\n")

        result = extract_first_level_dependencies(source, tmp_path)

        expected_path = str((tmp_path / "local_module.py").resolve())
        assert expected_path in result


class TestRelativeImports:
    """Test relative import statements."""

    def test_from_dot_import_sibling(self, tmp_path: Path) -> None:
        """from . import sibling where sibling.py exists in same package → included."""
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "sibling.py").write_text("val = 1\n")

        source = pkg / "main.py"
        source.write_text("from . import sibling\n")

        result = extract_first_level_dependencies(source, tmp_path)

        # from . import sibling resolves to the package's __init__.py
        expected_path = str((pkg / "__init__.py").resolve())
        assert expected_path in result

    def test_from_dot_sub_import_helper(self, tmp_path: Path) -> None:
        """from .sub import helper where sub/helper.py exists → included."""
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        sub = pkg / "sub"
        sub.mkdir()
        (sub / "__init__.py").write_text("")
        (sub / "helper.py").write_text("def help(): pass\n")

        source = pkg / "main.py"
        source.write_text("from .sub import helper\n")

        result = extract_first_level_dependencies(source, tmp_path)

        # from .sub import helper → resolves sub module (sub.py or sub/__init__.py)
        expected_path = str((sub / "__init__.py").resolve())
        assert expected_path in result

    def test_from_dot_module_import_name(self, tmp_path: Path) -> None:
        """from .utils import something where utils.py exists → included."""
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "utils.py").write_text("something = True\n")

        source = pkg / "main.py"
        source.write_text("from .utils import something\n")

        result = extract_first_level_dependencies(source, tmp_path)

        expected_path = str((pkg / "utils.py").resolve())
        assert expected_path in result


class TestStdlibExclusion:
    """Test that stdlib imports are NOT included in results."""

    def test_import_os_excluded(self, tmp_path: Path) -> None:
        source = tmp_path / "main.py"
        source.write_text("import os\n")

        result = extract_first_level_dependencies(source, tmp_path)
        assert result == {}

    def test_import_sys_excluded(self, tmp_path: Path) -> None:
        source = tmp_path / "main.py"
        source.write_text("import sys\n")

        result = extract_first_level_dependencies(source, tmp_path)
        assert result == {}

    def test_from_pathlib_import_path_excluded(self, tmp_path: Path) -> None:
        source = tmp_path / "main.py"
        source.write_text("from pathlib import Path\n")

        result = extract_first_level_dependencies(source, tmp_path)
        assert result == {}

    def test_multiple_stdlib_imports_excluded(self, tmp_path: Path) -> None:
        source = tmp_path / "main.py"
        source.write_text(
            "import os\nimport sys\nimport json\nfrom pathlib import Path\n"
        )

        result = extract_first_level_dependencies(source, tmp_path)
        assert result == {}


class TestThirdPartyExclusion:
    """Test that third-party imports are NOT included in results."""

    def test_import_requests_excluded(self, tmp_path: Path) -> None:
        source = tmp_path / "main.py"
        source.write_text("import requests\n")

        result = extract_first_level_dependencies(source, tmp_path)
        assert result == {}

    def test_from_pydantic_import_excluded(self, tmp_path: Path) -> None:
        source = tmp_path / "main.py"
        source.write_text("from pydantic import BaseModel\n")

        result = extract_first_level_dependencies(source, tmp_path)
        assert result == {}

    def test_mixed_stdlib_and_thirdparty_excluded(self, tmp_path: Path) -> None:
        """Only local imports should be included, not stdlib or third-party."""
        (tmp_path / "local_mod.py").write_text("x = 1\n")

        source = tmp_path / "main.py"
        source.write_text(
            "import os\nimport requests\nimport local_mod\nfrom pathlib import Path\n"
        )

        result = extract_first_level_dependencies(source, tmp_path)

        # Only local_mod should be included
        assert len(result) == 1
        expected_path = str((tmp_path / "local_mod.py").resolve())
        assert expected_path in result


class TestErrorHandling:
    """Test unreadable files and syntax errors return empty dict."""

    def test_unreadable_file_returns_empty_dict(self, tmp_path: Path) -> None:
        """Source file with permission error → returns empty dict."""
        source = tmp_path / "unreadable.py"
        source.write_text("import os\n")
        source.chmod(0o000)

        try:
            result = extract_first_level_dependencies(source, tmp_path)
            assert result == {}
        finally:
            # Restore permissions for cleanup
            source.chmod(0o644)

    def test_syntax_error_returns_empty_dict(self, tmp_path: Path) -> None:
        """Source file with syntax errors → returns empty dict."""
        source = tmp_path / "broken.py"
        source.write_text("def foo(\n  # missing closing paren and colon\n")

        result = extract_first_level_dependencies(source, tmp_path)
        assert result == {}

    def test_nonexistent_file_returns_empty_dict(self, tmp_path: Path) -> None:
        """Source file that doesn't exist → returns empty dict."""
        source = tmp_path / "does_not_exist.py"

        result = extract_first_level_dependencies(source, tmp_path)
        assert result == {}


class TestSha256Hashes:
    """Test that returned dependencies have valid sha256 hex strings."""

    def test_hash_is_valid_sha256_hex(self, tmp_path: Path) -> None:
        """Each returned dependency has a valid sha256 hex string (64 chars)."""
        (tmp_path / "dep_a.py").write_text("a = 1\n")
        (tmp_path / "dep_b.py").write_text("b = 2\n")

        source = tmp_path / "main.py"
        source.write_text("import dep_a\nimport dep_b\n")

        result = extract_first_level_dependencies(source, tmp_path)

        assert len(result) == 2
        for _path, hash_val in result.items():
            assert len(hash_val) == 64
            assert SHA256_PATTERN.match(hash_val), f"Invalid sha256: {hash_val}"

    def test_hash_changes_when_content_changes(self, tmp_path: Path) -> None:
        """Hash should reflect the actual file content."""
        dep = tmp_path / "dep.py"
        dep.write_text("version = 1\n")

        source = tmp_path / "main.py"
        source.write_text("import dep\n")

        result1 = extract_first_level_dependencies(source, tmp_path)
        hash1 = list(result1.values())[0]

        # Change the dependency content
        dep.write_text("version = 2\n")

        result2 = extract_first_level_dependencies(source, tmp_path)
        hash2 = list(result2.values())[0]

        assert hash1 != hash2


class TestTopLevelOnly:
    """Test that only top-level import statements are tracked."""

    def test_imports_inside_function_not_tracked(self, tmp_path: Path) -> None:
        """Imports inside functions are NOT included."""
        (tmp_path / "local_mod.py").write_text("x = 1\n")

        source = tmp_path / "main.py"
        source.write_text(
            "def my_func():\n    import local_mod\n    return local_mod.x\n"
        )

        result = extract_first_level_dependencies(source, tmp_path)
        assert result == {}

    def test_imports_inside_class_not_tracked(self, tmp_path: Path) -> None:
        """Imports inside classes are NOT included."""
        (tmp_path / "local_mod.py").write_text("x = 1\n")

        source = tmp_path / "main.py"
        source.write_text(
            "class MyClass:\n    import local_mod\n    val = local_mod.x\n"
        )

        result = extract_first_level_dependencies(source, tmp_path)
        assert result == {}

    def test_imports_inside_if_block_not_tracked(self, tmp_path: Path) -> None:
        """Imports inside if blocks (not top-level) are NOT included."""
        (tmp_path / "local_mod.py").write_text("x = 1\n")

        source = tmp_path / "main.py"
        source.write_text("if True:\n    import local_mod\n")

        result = extract_first_level_dependencies(source, tmp_path)
        assert result == {}

    def test_top_level_import_is_tracked(self, tmp_path: Path) -> None:
        """Top-level imports ARE included (control test)."""
        (tmp_path / "local_mod.py").write_text("x = 1\n")

        source = tmp_path / "main.py"
        source.write_text("import local_mod\n")

        result = extract_first_level_dependencies(source, tmp_path)

        expected_path = str((tmp_path / "local_mod.py").resolve())
        assert expected_path in result

    def test_mixed_top_level_and_nested_only_tracks_top_level(
        self, tmp_path: Path
    ) -> None:
        """Only top-level imports are tracked; nested ones are ignored."""
        (tmp_path / "top_dep.py").write_text("a = 1\n")
        (tmp_path / "nested_dep.py").write_text("b = 2\n")

        source = tmp_path / "main.py"
        source.write_text(
            "import top_dep\n\ndef func():\n    import nested_dep\n    return nested_dep.b\n"
        )

        result = extract_first_level_dependencies(source, tmp_path)

        top_path = str((tmp_path / "top_dep.py").resolve())
        nested_path = str((tmp_path / "nested_dep.py").resolve())
        assert top_path in result
        assert nested_path not in result
