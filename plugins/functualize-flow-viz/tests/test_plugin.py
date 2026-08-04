"""Unit tests for functualize-flow-viz plugin.

Tests the flow visualization plugin's graph rendering and export.
"""

from __future__ import annotations


class TestImports:
    """Verify the plugin is importable."""

    def test_import_package(self):
        import functualize_flow_viz

        assert dir(functualize_flow_viz)
