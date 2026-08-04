"""Tests for Typer/CLI dependency isolation (Task 10.5).

Verifies:
1. Importing `functualize.app` and `functualize.job` does NOT cause runtime
   import of typer, click, rich, or textual into sys.modules.
2. Internal packages (_discovery/, _config/, _engine/, _events/, _plugins/,
   _primitives/, _types/, _app/) have zero runtime imports of typer, textual,
   rich, or jinja2 (verified via AST static analysis).

Requirements: 4.1, 4.2, 4.6
"""

from __future__ import annotations

import ast
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# Root of the functualize source package
SRC_ROOT = Path(__file__).parent.parent / "src" / "functualize"

# Internal packages that must have zero runtime imports of CLI dependencies
INTERNAL_PACKAGES = [
    "_discovery",
    "_config",
    "_engine",
    "_events",
    "_plugins",
    "_primitives",
    "_types",
    "_app",
]

# Forbidden runtime imports for internal packages
FORBIDDEN_MODULES = {"typer", "textual", "rich", "jinja2"}


class TestTyperIsolationSubprocess:
    """Verify that importing functualize.app and functualize.job does not
    pull in CLI dependencies at runtime (Requirement 4.6)."""

    def test_public_api_import_does_not_load_typer(self, tmp_path: Path):
        """Subprocess test: import functualize.app + functualize.job and
        assert typer/click/rich/textual are NOT in sys.modules."""
        script = textwrap.dedent("""\
            import sys

            # Import the public API modules
            import functualize.app
            import functualize.job

            # Check for forbidden CLI modules in sys.modules
            forbidden = {"typer", "click", "rich", "textual"}
            loaded = forbidden & set(sys.modules.keys())

            if loaded:
                print(f"FAIL: Found forbidden modules in sys.modules: {sorted(loaded)}", file=sys.stderr)
                sys.exit(1)
            else:
                print("PASS: No CLI dependencies loaded by functualize.app/job imports")
                sys.exit(0)
        """)

        script_path = tmp_path / "check_isolation.py"
        script_path.write_text(script)

        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, (
            f"CLI dependencies were imported at runtime:\n"
            f"  stdout: {result.stdout}\n"
            f"  stderr: {result.stderr}"
        )


class TestInternalPackagesNoCliImports:
    """Verify internal packages have zero runtime imports of typer, textual,
    rich, or jinja2 using AST-based static analysis (Requirements 4.1, 4.2)."""

    def _collect_python_files(self, package_dir: Path) -> list[Path]:
        """Recursively collect all .py files in a package directory."""
        return sorted(package_dir.rglob("*.py"))

    def _extract_runtime_imports(self, source_path: Path) -> list[tuple[str, int]]:
        """Extract runtime import module names from a Python source file.

        Excludes imports that are inside `if TYPE_CHECKING:` blocks,
        since those have no runtime effect.

        Returns a list of (module_name, line_number) tuples.
        """
        source = source_path.read_text()
        tree = ast.parse(source, filename=str(source_path))

        # First, identify line ranges that are inside TYPE_CHECKING blocks
        type_checking_ranges: list[tuple[int, int]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                # Check for `if TYPE_CHECKING:` or `if typing.TYPE_CHECKING:`
                test = node.test
                is_type_checking = False
                if (
                    isinstance(test, ast.Name)
                    and test.id == "TYPE_CHECKING"
                    or isinstance(test, ast.Attribute)
                    and test.attr == "TYPE_CHECKING"
                ):
                    is_type_checking = True
                if is_type_checking:
                    # Get the range of lines in the body
                    start_line = node.body[0].lineno if node.body else node.lineno
                    end_line = max(
                        getattr(n, "end_lineno", n.lineno)
                        for n in node.body
                        if hasattr(n, "lineno")
                    )
                    type_checking_ranges.append((start_line, end_line))

        def _in_type_checking_block(lineno: int) -> bool:
            return any(start <= lineno <= end for start, end in type_checking_ranges)

        imports: list[tuple[str, int]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if not _in_type_checking_block(node.lineno):
                    for alias in node.names:
                        imports.append((alias.name, node.lineno))
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and not _in_type_checking_block(node.lineno)
            ):
                imports.append((node.module, node.lineno))

        return imports

    def _is_forbidden_import(self, module_name: str) -> bool:
        """Check if a module name matches one of the forbidden CLI dependencies."""
        # Check top-level module match (e.g., "typer" or "typer.params")
        top_level = module_name.split(".")[0]
        return top_level in FORBIDDEN_MODULES

    @pytest.mark.parametrize("package_name", INTERNAL_PACKAGES)
    def test_no_forbidden_runtime_imports(self, package_name: str):
        """Each internal package has zero runtime imports of forbidden CLI deps."""
        package_dir = SRC_ROOT / package_name
        if not package_dir.exists():
            pytest.skip(f"Package {package_name} does not exist yet")

        violations: list[str] = []
        for source_path in self._collect_python_files(package_dir):
            rel_path = source_path.relative_to(SRC_ROOT)
            imports = self._extract_runtime_imports(source_path)
            for module_name, lineno in imports:
                if self._is_forbidden_import(module_name):
                    violations.append(f"  {rel_path}:{lineno} imports '{module_name}'")

        assert not violations, (
            f"Package '{package_name}' has forbidden runtime imports of "
            f"CLI dependencies ({', '.join(sorted(FORBIDDEN_MODULES))}):\n"
            + "\n".join(violations)
        )

    def test_all_internal_packages_combined(self):
        """Aggregate check: ALL internal packages combined have zero forbidden imports."""
        all_violations: list[str] = []

        for package_name in INTERNAL_PACKAGES:
            package_dir = SRC_ROOT / package_name
            if not package_dir.exists():
                continue

            for source_path in self._collect_python_files(package_dir):
                rel_path = source_path.relative_to(SRC_ROOT)
                imports = self._extract_runtime_imports(source_path)
                for module_name, lineno in imports:
                    if self._is_forbidden_import(module_name):
                        all_violations.append(
                            f"  {rel_path}:{lineno} imports '{module_name}'"
                        )

        assert not all_violations, (
            f"Internal packages have {len(all_violations)} forbidden runtime "
            f"import(s) of CLI dependencies:\n" + "\n".join(all_violations)
        )
