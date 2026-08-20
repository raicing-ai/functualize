"""Property-based tests for the AST dependency extractor.

Tests Properties 9 and 10 from the design document for the
layered-architecture-lazy-boot spec.

Property 9 — Validates: Requirements 10.2, 10.3, 10.4, 10.6
Property 10 — Validates: Requirements 10.6
"""

from __future__ import annotations

import hashlib
import keyword
import tempfile
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from functualize._discovery.ast_extractor import extract_first_level_dependencies

# --- Constants ---

# Standard library modules that should never appear in results
STDLIB_MODULES = ["os", "sys", "pathlib", "json", "hashlib", "ast", "typing", "re"]

# Third-party modules that should never appear in results
THIRD_PARTY_MODULES = ["numpy", "requests", "flask", "pytest", "hypothesis"]

# Python keywords cannot be used as module names in import statements
_PYTHON_KEYWORDS = set(keyword.kwlist) | set(keyword.softkwlist)


# --- Strategies ---

# Valid Python identifier strategy (used as module names)
_module_name = st.from_regex(r"[a-z][a-z0-9_]{0,14}", fullmatch=True).filter(
    lambda n: (
        n not in STDLIB_MODULES
        and n not in THIRD_PARTY_MODULES
        and n not in _PYTHON_KEYWORDS
    )
)


@st.composite
def import_patterns(draw: st.DrawFn) -> tuple[str, list[str]]:
    """Generate Python source code with various import patterns and track which modules are imported.

    Returns (source_code, list_of_imported_module_names) where the module names
    are the first-level in-project imports that should be resolved.
    """
    imported_modules: list[str] = []
    lines: list[str] = []

    # Generate a mix of import types
    num_imports = draw(st.integers(min_value=1, max_value=8))

    for _ in range(num_imports):
        import_type = draw(
            st.sampled_from(["import", "from_import", "stdlib", "third_party"])
        )

        if import_type == "import":
            # import local_module
            mod_name = draw(_module_name)
            lines.append(f"import {mod_name}")
            if mod_name not in imported_modules:
                imported_modules.append(mod_name)

        elif import_type == "from_import":
            # from local_module import something
            mod_name = draw(_module_name)
            attr_name = draw(_module_name)
            lines.append(f"from {mod_name} import {attr_name}")
            if mod_name not in imported_modules:
                imported_modules.append(mod_name)

        elif import_type == "stdlib":
            # import os / from sys import path — should be excluded
            mod = draw(st.sampled_from(STDLIB_MODULES))
            if draw(st.booleans()):
                lines.append(f"import {mod}")
            else:
                lines.append(f"from {mod} import something")

        elif import_type == "third_party":
            # import numpy / from requests import get — should be excluded
            mod = draw(st.sampled_from(THIRD_PARTY_MODULES))
            if draw(st.booleans()):
                lines.append(f"import {mod}")
            else:
                lines.append(f"from {mod} import something")

    # Add some body code
    lines.append("")
    lines.append("def main():")
    lines.append("    pass")

    source = "\n".join(lines)
    return source, imported_modules


@st.composite
def relative_import_patterns(draw: st.DrawFn) -> tuple[str, list[str], int]:
    """Generate source code with relative imports.

    Returns (source_code, list_of_relative_module_names, relative_level).
    """
    lines: list[str] = []
    imported_modules: list[str] = []

    level = draw(st.integers(min_value=1, max_value=2))
    num_imports = draw(st.integers(min_value=1, max_value=4))
    dots = "." * level

    for _ in range(num_imports):
        mod_name = draw(_module_name)
        if draw(st.booleans()):
            # from .mod import something
            lines.append(f"from {dots}{mod_name} import func")
        else:
            # from . import mod
            lines.append(f"from {dots} import {mod_name}")
        if mod_name not in imported_modules:
            imported_modules.append(mod_name)

    lines.append("")
    lines.append("x = 1")

    source = "\n".join(lines)
    return source, imported_modules, level


# --- Property 9: AST extractor identifies in-project imports correctly ---


# Feature: layered-architecture-lazy-boot, Property 9: AST extractor identifies in-project imports correctly
class TestASTExtractorIdentifiesInProjectImports:
    """Property 9: AST extractor identifies in-project imports correctly.

    For any Python source file within a project root, the AST dependency extractor
    SHALL return a dict containing entries only for first-level imports that resolve
    to existing .py files within the project root, and SHALL NOT include stdlib or
    third-party package imports.
    """

    @given(data=import_patterns())
    def test_only_existing_in_project_files_returned(self, data: tuple[str, list[str]]):
        """Only imports that resolve to existing .py files within project_root are returned.

        # Feature: layered-architecture-lazy-boot, Property 9: AST extractor identifies in-project imports correctly
        **Validates: Requirements 10.2, 10.3**
        """
        source_code, imported_modules = data

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Create the source file
            source_file = tmp_path / "my_module.py"
            source_file.write_text(source_code, encoding="utf-8")

            # Create ALL of the imported modules as real files
            for mod_name in imported_modules:
                mod_file = tmp_path / f"{mod_name}.py"
                mod_file.write_text(f"# module {mod_name}\n", encoding="utf-8")

            # Extract dependencies
            result = extract_first_level_dependencies(source_file, tmp_path)

            # All returned paths must be within project_root
            for dep_path in result:
                resolved = Path(dep_path).resolve()
                assert str(resolved).startswith(str(tmp_path.resolve())), (
                    f"Dependency {dep_path} is not within project root"
                )

            # All returned paths must actually exist as files
            for dep_path in result:
                assert Path(dep_path).is_file(), f"Dependency {dep_path} does not exist"

            # All returned values must be valid sha256 hex digests
            for dep_hash in result.values():
                assert len(dep_hash) == 64, f"Hash {dep_hash} is not 64 chars"
                assert all(c in "0123456789abcdef" for c in dep_hash), (
                    f"Hash {dep_hash} is not valid hex"
                )

            # Verify the sha256 hashes are correct
            for dep_path, dep_hash in result.items():
                content = Path(dep_path).read_bytes()
                expected_hash = hashlib.sha256(content).hexdigest()
                assert dep_hash == expected_hash, (
                    f"Hash mismatch for {dep_path}: "
                    f"got {dep_hash}, expected {expected_hash}"
                )

    @given(data=import_patterns())
    def test_stdlib_imports_excluded(self, data: tuple[str, list[str]]):
        """Standard library imports are never included in the results.

        # Feature: layered-architecture-lazy-boot, Property 9: AST extractor identifies in-project imports correctly
        **Validates: Requirements 10.4**
        """
        source_code, _ = data

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Create the source file
            source_file = tmp_path / "my_module.py"
            source_file.write_text(source_code, encoding="utf-8")

            # Do NOT create files for stdlib modules in the project —
            # the extractor resolves module names to file paths,
            # and stdlib modules won't resolve to files in tmp_path
            result = extract_first_level_dependencies(source_file, tmp_path)

            # None of the returned paths should correspond to stdlib modules
            # (since we didn't create those files in the project)
            result_basenames = {Path(p).stem for p in result}
            for stdlib_mod in STDLIB_MODULES:
                assert stdlib_mod not in result_basenames, (
                    f"Stdlib module '{stdlib_mod}' should not appear in results "
                    f"when no matching file exists in project root"
                )

    @given(data=relative_import_patterns())
    def test_relative_imports_resolve_within_project(
        self, data: tuple[str, list[str], int]
    ):
        """Relative imports resolve correctly and only include in-project files.

        # Feature: layered-architecture-lazy-boot, Property 9: AST extractor identifies in-project imports correctly
        **Validates: Requirements 10.2, 10.3**
        """
        source_code, imported_modules, level = data

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Create a package structure deep enough for the relative imports
            pkg_dir = tmp_path / "pkg" / "sub"
            pkg_dir.mkdir(parents=True)
            (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
            (pkg_dir / "__init__.py").write_text("", encoding="utf-8")

            # Create the source file inside the package
            source_file = pkg_dir / "my_module.py"
            source_file.write_text(source_code, encoding="utf-8")

            # Create some of the relative import targets
            base = pkg_dir if level == 1 else pkg_dir.parent

            for mod_name in imported_modules:
                mod_file = base / f"{mod_name}.py"
                mod_file.write_text(f"# relative module {mod_name}\n", encoding="utf-8")

            # Extract dependencies
            result = extract_first_level_dependencies(source_file, tmp_path)

            # All returned paths must be within project_root
            for dep_path in result:
                resolved = Path(dep_path).resolve()
                assert str(resolved).startswith(str(tmp_path.resolve()))

            # All returned paths must exist
            for dep_path in result:
                assert Path(dep_path).is_file()

            # All hashes must be valid sha256
            for dep_hash in result.values():
                assert len(dep_hash) == 64
                assert all(c in "0123456789abcdef" for c in dep_hash)

    @given(data=import_patterns())
    def test_results_contain_sha256_hashes(self, data: tuple[str, list[str]]):
        """All returned values are valid sha256 hex digests matching file content.

        # Feature: layered-architecture-lazy-boot, Property 9: AST extractor identifies in-project imports correctly
        **Validates: Requirements 10.4**
        """
        source_code, imported_modules = data

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Create source file and all imported modules
            source_file = tmp_path / "my_module.py"
            source_file.write_text(source_code, encoding="utf-8")

            for mod_name in imported_modules:
                mod_file = tmp_path / f"{mod_name}.py"
                content = f"# content of {mod_name}\nvalue = 42\n"
                mod_file.write_text(content, encoding="utf-8")

            result = extract_first_level_dependencies(source_file, tmp_path)

            # Every hash must match the actual file content
            for dep_path, dep_hash in result.items():
                content = Path(dep_path).read_bytes()
                expected = hashlib.sha256(content).hexdigest()
                assert dep_hash == expected


# --- Property 10: AST extractor is non-transitive ---


# Feature: layered-architecture-lazy-boot, Property 10: AST extractor is non-transitive
class TestASTExtractorIsNonTransitive:
    """Property 10: AST extractor is non-transitive.

    For any module A that imports module B, and module B imports module C
    (where all are in-project), extracting dependencies of A SHALL include B
    but SHALL NOT include C.
    """

    @given(
        mod_b_name=_module_name,
        mod_c_name=_module_name.filter(lambda n: len(n) > 1),
    )
    def test_transitive_deps_not_included(self, mod_b_name: str, mod_c_name: str):
        """Extracting A's dependencies includes B but NOT C (where A→B→C).

        # Feature: layered-architecture-lazy-boot, Property 10: AST extractor is non-transitive
        **Validates: Requirements 10.6**
        """
        # Ensure B and C have different names
        if mod_b_name == mod_c_name:
            mod_c_name = mod_c_name + "x"

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Module A imports B
            source_a = f"import {mod_b_name}\n\ndef do_a():\n    pass\n"

            # Module B imports C
            source_b = f"import {mod_c_name}\n\ndef do_b():\n    pass\n"

            # Module C has no imports
            source_c = "def do_c():\n    pass\n"

            # Create all files
            file_a = tmp_path / "module_a.py"
            file_b = tmp_path / f"{mod_b_name}.py"
            file_c = tmp_path / f"{mod_c_name}.py"

            file_a.write_text(source_a, encoding="utf-8")
            file_b.write_text(source_b, encoding="utf-8")
            file_c.write_text(source_c, encoding="utf-8")

            # Extract dependencies of A
            result = extract_first_level_dependencies(file_a, tmp_path)

            # B MUST be in A's dependencies
            resolved_b = str(file_b.resolve())
            assert resolved_b in result, (
                f"Module B ({mod_b_name}) should be in A's dependencies"
            )

            # C MUST NOT be in A's dependencies (non-transitive)
            resolved_c = str(file_c.resolve())
            assert resolved_c not in result, (
                f"Module C ({mod_c_name}) should NOT be in A's dependencies "
                f"(transitive)"
            )

    @given(
        chain_length=st.integers(min_value=3, max_value=5),
        data=st.data(),
    )
    def test_longer_transitive_chains_not_included(
        self, chain_length: int, data: st.DataObject
    ):
        """For chains A→B→C→D→..., only B appears in A's deps (not C, D, ...).

        # Feature: layered-architecture-lazy-boot, Property 10: AST extractor is non-transitive
        **Validates: Requirements 10.6**
        """
        # Generate unique module names for the chain
        mod_names: list[str] = []
        for i in range(chain_length):
            name = data.draw(_module_name, label=f"mod_{i}")
            # Ensure uniqueness
            while name in mod_names:
                name = name + str(i)
            mod_names.append(name)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Create module files: each imports the next in the chain
            files: list[Path] = []
            for i, name in enumerate(mod_names):
                file_path = tmp_path / f"{name}.py"
                if i < chain_length - 1:
                    next_name = mod_names[i + 1]
                    source = f"import {next_name}\n\ndef func_{name}():\n    pass\n"
                else:
                    # Last module in chain has no imports
                    source = f"def func_{name}():\n    pass\n"
                file_path.write_text(source, encoding="utf-8")
                files.append(file_path)

            # Extract dependencies of the first module (A)
            result = extract_first_level_dependencies(files[0], tmp_path)

            # Only the direct import (B = mod_names[1]) should be in results
            resolved_b = str(files[1].resolve())
            assert resolved_b in result, (
                f"Direct import {mod_names[1]} should be in dependencies"
            )

            # None of the transitive deps (C, D, ...) should be included
            for i in range(2, chain_length):
                resolved = str(files[i].resolve())
                assert resolved not in result, (
                    f"Transitive dependency {mod_names[i]} (depth {i}) should "
                    f"NOT be in dependencies of {mod_names[0]}"
                )
