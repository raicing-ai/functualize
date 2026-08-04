"""Bug condition exploration property test for TUI CLI audit cleanup.

# Feature: tui-cli-audit-cleanup, Property 1: Bug Condition
# Archive and Internal Imports Detected

This test encodes the EXPECTED behavior (no architecture violations).
It is expected to FAIL on unfixed code — failure confirms the bug exists.
When the fix is applied, this test will PASS, confirming violations are resolved.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6**
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from hypothesis import given, note, settings
from hypothesis import strategies as st

# =============================================================================
# Constants
# =============================================================================

_CLI_SRC_DIR = Path(__file__).resolve().parents[2] / "src" / "functualize" / "_cli"

# Collect all Python source files in _cli/ (excluding __pycache__ dirs)
_CLI_PYTHON_FILES: list[Path] = sorted(
    p for p in _CLI_SRC_DIR.rglob("*.py") if "__pycache__" not in str(p)
)

# Forbidden import prefixes (architecture violations)
_FORBIDDEN_ARCHIVE_PREFIX = "functualize._cli.archive."
_FORBIDDEN_EVENTS_PREFIX = "functualize._events."
_FORBIDDEN_CONFIG_PREFIX = "functualize._config."


# =============================================================================
# Helpers
# =============================================================================


def _extract_imports(file_path: Path) -> list[str]:
    """Parse a Python file and extract all import source modules.

    Returns a list of module strings from:
    - `from X import Y` -> X
    - `import X` -> X
    """
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError):
        return []

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
    return imports


def _get_stale_pyc_files() -> list[Path]:
    """Find .pyc files in _cli/__pycache__/ that have no corresponding source file."""
    pycache_dir = _CLI_SRC_DIR / "__pycache__"
    if not pycache_dir.exists():
        return []

    stale: list[Path] = []
    for pyc_file in pycache_dir.glob("*.pyc"):
        # Extract module name from pyc filename like "module.cpython-313.pyc"
        name_parts = pyc_file.stem.split(".")
        if name_parts:
            module_name = name_parts[0]
            source_file = _CLI_SRC_DIR / f"{module_name}.py"
            if not source_file.exists():
                stale.append(pyc_file)
    return stale


# =============================================================================
# Strategies: Generate file indices from the known source tree
# =============================================================================

# Strategy that draws from actual _cli/ Python files
_file_index_strategy = st.integers(
    min_value=0, max_value=max(0, len(_CLI_PYTHON_FILES) - 1)
)


# =============================================================================
# Property 1: Bug Condition — Archive and Internal Imports Detected
# =============================================================================


@pytest.mark.slow
class TestBugConditionArchiveAndInternalImports:
    """Property 1: Bug Condition — Archive and Internal Imports Detected.

    For any Python source file in `_cli/`, the file SHALL NOT import from:
    - functualize._cli.archive.* (archived models that should be relocated)
    - functualize._events.* (internal kernel event system)
    - functualize._config.* (internal kernel config system)

    Additionally:
    - _cli/archive/focus_zone_manager.py SHALL NOT exist (dead code)
    - _cli/__pycache__/ SHALL NOT contain stale .pyc files without source

    **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6**
    """

    @given(file_idx=_file_index_strategy)
    @settings(max_examples=len(_CLI_PYTHON_FILES))
    def test_no_archive_imports(self, file_idx: int) -> None:
        """No file in _cli/ imports from functualize._cli.archive.*.

        **Validates: Requirements 1.2**
        """
        file_path = _CLI_PYTHON_FILES[file_idx]
        rel_path = file_path.relative_to(_CLI_SRC_DIR)
        note(f"Checking file: {rel_path}")

        imports = _extract_imports(file_path)
        archive_imports = [
            imp for imp in imports if imp.startswith(_FORBIDDEN_ARCHIVE_PREFIX)
        ]

        assert not archive_imports, (
            f"File {rel_path} imports from archive:\n"
            + "\n".join(f"  - {imp}" for imp in archive_imports)
        )

    @given(file_idx=_file_index_strategy)
    @settings(max_examples=len(_CLI_PYTHON_FILES))
    def test_no_events_imports(self, file_idx: int) -> None:
        """No file in _cli/ imports from functualize._events.*.

        **Validates: Requirements 1.4**
        """
        file_path = _CLI_PYTHON_FILES[file_idx]
        rel_path = file_path.relative_to(_CLI_SRC_DIR)
        note(f"Checking file: {rel_path}")

        imports = _extract_imports(file_path)
        events_imports = [
            imp for imp in imports if imp.startswith(_FORBIDDEN_EVENTS_PREFIX)
        ]

        assert not events_imports, (
            f"File {rel_path} imports from _events:\n"
            + "\n".join(f"  - {imp}" for imp in events_imports)
        )

    @given(file_idx=_file_index_strategy)
    @settings(max_examples=len(_CLI_PYTHON_FILES))
    def test_no_config_imports(self, file_idx: int) -> None:
        """No file in _cli/ imports from functualize._config.*.

        **Validates: Requirements 1.5, 1.6**
        """
        file_path = _CLI_PYTHON_FILES[file_idx]
        rel_path = file_path.relative_to(_CLI_SRC_DIR)
        note(f"Checking file: {rel_path}")

        imports = _extract_imports(file_path)
        config_imports = [
            imp for imp in imports if imp.startswith(_FORBIDDEN_CONFIG_PREFIX)
        ]

        assert not config_imports, (
            f"File {rel_path} imports from _config:\n"
            + "\n".join(f"  - {imp}" for imp in config_imports)
        )

    def test_dead_code_focus_zone_manager_does_not_exist(self) -> None:
        """_cli/archive/focus_zone_manager.py SHALL NOT exist (dead code).

        **Validates: Requirements 1.3**
        """
        dead_file = _CLI_SRC_DIR / "archive" / "focus_zone_manager.py"
        assert not dead_file.exists(), (
            f"Dead code file exists: {dead_file.relative_to(_CLI_SRC_DIR)}\n"
            "This file has zero importers and should be deleted."
        )

    def test_no_stale_pyc_files(self) -> None:
        """_cli/__pycache__/ SHALL NOT contain .pyc files without corresponding source.

        **Validates: Requirements 1.1**
        """
        stale_files = _get_stale_pyc_files()
        assert not stale_files, (
            f"Found {len(stale_files)} stale .pyc files without corresponding source:\n"
            + "\n".join(f"  - {f.name}" for f in stale_files[:10])
            + (
                f"\n  ... and {len(stale_files) - 10} more"
                if len(stale_files) > 10
                else ""
            )
        )
