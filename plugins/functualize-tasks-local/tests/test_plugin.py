"""Unit tests for functualize-tasks-local plugin.

Tests the local task runner implementation.
"""

from __future__ import annotations


class TestImports:
    """Verify the plugin is importable."""

    def test_import_package(self):
        import functualize_tasks_local

        assert dir(functualize_tasks_local)
