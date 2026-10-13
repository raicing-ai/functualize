"""The plugin's `version` and the package it ships in agree (task 18, S-7).

`SQLiteSubstratePlugin.version` is a literal, as it is in every sibling plugin:
a plugin can be loaded from a directory as well as from an installed
distribution, so reading the version off the package metadata at import time
would fail exactly where directory loading is the point. A literal is therefore
free to drift from `pyproject.toml`, and this is the check that notices.
"""

from __future__ import annotations

import importlib.metadata

from functualize_substrate_sqlite import SQLiteSubstratePlugin

DISTRIBUTION = "functualize-substrate-sqlite"


def test_plugin_version_is_the_package_version() -> None:
    assert SQLiteSubstratePlugin.version == importlib.metadata.version(DISTRIBUTION)
