"""Module file discovery utilities.

Only imports from _types/ and stdlib — zero third-party runtime dependencies.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path


def iter_module_files(directory: str | Path) -> Generator[Path, None, None]:
    """Yield Path objects for each .py file in the given directory.

    Non-recursive scan that excludes ``__init__.py`` and any files
    within ``__pycache__/`` directories.

    Args:
        directory: The directory to scan for Python module files.

    Yields:
        Path objects for each qualifying .py file.
    """
    dir_path = Path(directory)
    if not dir_path.is_dir():
        return

    for entry in sorted(dir_path.iterdir()):
        if not entry.is_file():
            continue
        if entry.suffix != ".py":
            continue
        if entry.name == "__init__.py":
            continue
        # Skip files inside __pycache__ (shouldn't happen with iterdir on
        # the parent, but guard against symlinks or unusual layouts)
        if "__pycache__" in entry.parts:
            continue
        yield entry
