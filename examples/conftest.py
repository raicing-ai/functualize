"""Pytest configuration for examples.

Adds every standalone example directory containing tests to sys.path so
that test files can import their sibling modules directly (e.g.,
test_hello.py imports from hello.py). Standalone examples are nested
under grouping parents (discovery/, config/, ai/, tui/), so the walk is
recursive. Quickstart steps and project examples manage sys.path in
their own conftest.py / test files.
"""

import sys
from pathlib import Path

standalone_dir = Path(__file__).parent / "standalone"
_seen: set[str] = set()
for test_file in sorted(standalone_dir.rglob("test_*.py")):
    example_dir = str(test_file.parent)
    if "__pycache__" in example_dir or example_dir in _seen:
        continue
    _seen.add(example_dir)
    sys.path.insert(0, example_dir)
