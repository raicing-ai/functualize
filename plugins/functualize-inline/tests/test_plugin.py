"""Unit tests for functualize-inline plugin.

Tests the inline prompt plugin's availability detection and response collection.
"""

from __future__ import annotations


class TestImports:
    """Verify the plugin is importable."""

    def test_import_package(self):
        import functualize_inline

        assert dir(functualize_inline)
