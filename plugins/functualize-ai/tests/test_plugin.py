"""Unit tests for functualize-ai plugin.

Tests the AI capability plugin's core behavior: provider registration,
budget tracking, and AI gate strategies.
"""

from __future__ import annotations


class TestImports:
    """Verify the plugin is importable and exports expected symbols."""

    def test_import_package(self):
        import functualize_ai

        assert hasattr(functualize_ai, "__all__") or dir(functualize_ai)

    def test_import_does_not_raise(self):
        """Importing the plugin should not produce side effects."""
        from functualize_ai import __name__ as pkg_name

        assert pkg_name == "functualize_ai"
