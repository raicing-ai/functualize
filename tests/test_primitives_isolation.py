"""Tests for primitives package re-exports and import isolation (Task 1.10).

Validates:
- All public types are exported from functualize._primitives
- `from functualize._primitives import MiddlewareChain, ResourceLocator, ModulePreFilter` works
- No import-time dependencies on other functualize.* subpackages (AST-verified)

Requirements: 1.1, 1.14
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# The primitives package root
PRIMITIVES_DIR = Path(__file__).parent.parent / "src" / "functualize" / "_primitives"

# All public symbols that must be importable from functualize._primitives
EXPECTED_EXPORTS = [
    "AllJobFilters",
    "AllOf",
    "AmbiguousProviderError",
    "AnyOf",
    "ASTModulePreFilter",
    "Candidate",
    "DIRegistry",
    "DIValidationError",
    "DefaultModulePreFilter",
    "DisplayClassPreFilter",
    "GroupOptionsPreFilter",
    "GlobExcludePreFilter",
    "JobDecoratorFilter",
    "JobFilter",
    "JobPostfixFilter",
    "JobPrefixFilter",
    "LocateResult",
    "MarkerModulePreFilter",
    "MiddlewareChain",
    "MissingProviderError",
    "ModulePreFilter",
    "NoneOf",
    "Provide",
    "RegistryFrozenError",
    "ResolutionError",
    "ResourceLocator",
    "ResourceLocatorError",
    "compute_project_id",
    "first_non_none",
    "iter_module_files",
    "lazy_cached",
    "resilient",
]


class TestPrimitivesReExports:
    """Verify all public types are correctly re-exported from _primitives/__init__.py."""

    def test_import_key_types(self):
        """The primary import statement from the task spec works."""
        from functualize._primitives import (
            MiddlewareChain,
            ModulePreFilter,
            ResourceLocator,
        )

        assert MiddlewareChain is not None
        assert ResourceLocator is not None
        assert ModulePreFilter is not None

    @pytest.mark.parametrize("name", EXPECTED_EXPORTS)
    def test_export_available(self, name: str):
        """Each expected public symbol is importable from functualize._primitives."""
        import functualize._primitives as prims

        assert hasattr(prims, name), f"{name} not exported from functualize._primitives"

    def test_all_matches_expected_exports(self):
        """__all__ contains exactly the expected set of exports."""
        import functualize._primitives as prims

        actual = set(prims.__all__)
        expected = set(EXPECTED_EXPORTS)
        assert actual == expected, (
            f"Mismatch in __all__:\n"
            f"  Missing: {expected - actual}\n"
            f"  Extra: {actual - expected}"
        )


class TestPrimitivesIsolation:
    """Verify no primitives module imports from other functualize.* subpackages (Req 1.14).

    Uses AST analysis to statically check all import statements in the primitives
    package, ensuring they only reference:
    - stdlib modules
    - third-party packages
    - other modules within functualize._primitives itself
    - functualize._types (allowed dependency)
    """

    def _get_primitives_modules(self) -> list[Path]:
        """Return all .py files in the _primitives package."""
        return sorted(PRIMITIVES_DIR.glob("*.py"))

    def _extract_imports(self, source_path: Path) -> list[str]:
        """Extract all imported module names from a Python source file using AST."""
        source = source_path.read_text()
        tree = ast.parse(source, filename=str(source_path))

        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        return imports

    def _is_allowed_import(self, module_name: str) -> bool:
        """Check if an import is allowed for primitives modules.

        Allowed:
        - stdlib (anything not starting with 'functualize')
        - third-party (anything not starting with 'functualize')
        - within _primitives itself ('functualize._primitives' or 'functualize._primitives.*')
        - from _types ('functualize._types' or 'functualize._types.*')

        Disallowed:
        - Any other functualize.* subpackage
        """
        if not module_name.startswith("functualize"):
            # stdlib or third-party
            return True
        # Within functualize namespace — only _primitives and _types are allowed
        return bool(
            module_name == "functualize._primitives"
            or module_name.startswith("functualize._primitives.")
            or module_name == "functualize._types"
            or module_name.startswith("functualize._types.")
        )

    def test_no_internal_dependencies(self):
        """No primitives module imports from disallowed functualize.* subpackages."""
        violations: list[str] = []

        for source_path in self._get_primitives_modules():
            imports = self._extract_imports(source_path)
            for imp in imports:
                if not self._is_allowed_import(imp):
                    violations.append(f"  {source_path.name}: imports '{imp}'")

        assert not violations, (
            "Primitives modules have disallowed imports from other functualize.* "
            "subpackages:\n" + "\n".join(violations)
        )

    @pytest.mark.parametrize(
        "source_file", sorted(PRIMITIVES_DIR.glob("*.py")), ids=lambda p: p.name
    )
    def test_individual_module_isolation(self, source_file: Path):
        """Each primitives module individually has no disallowed imports."""
        imports = self._extract_imports(source_file)
        bad_imports = [imp for imp in imports if not self._is_allowed_import(imp)]
        assert not bad_imports, (
            f"{source_file.name} imports from disallowed functualize.* subpackages: "
            f"{bad_imports}"
        )
