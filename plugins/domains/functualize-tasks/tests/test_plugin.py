"""Unit tests for functualize-tasks domain SDK.

Tests the task capability protocols and domain metadata.
"""

from __future__ import annotations


class TestImports:
    """Verify the plugin is importable."""

    def test_import_package(self):
        import functualize_tasks

        assert dir(functualize_tasks)
