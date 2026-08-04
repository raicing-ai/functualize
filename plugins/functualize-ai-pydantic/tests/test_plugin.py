"""Unit tests for functualize-ai-pydantic plugin.

Tests Pydantic model integration with the AI capability layer.
"""

from __future__ import annotations


class TestImports:
    """Verify the plugin is importable."""

    def test_import_package(self):
        import functualize_ai_pydantic

        assert dir(functualize_ai_pydantic)
