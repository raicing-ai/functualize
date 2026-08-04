"""Group-trie ingestion over a REAL discovery cache (convergence A3.2).

`test_group_trie.py` builds from hand-written rows. This builds from a cache
file that a real scan produced, which is what pre-boot dispatch will do — so it
catches the class of bug where the row shape the trie expects and the shape the
cache actually holds drift apart (`JobDescriptor.name` is the *full dotted*
name, not the leaf; getting that wrong yields `infra/aws/infra.aws.provision-it`).

The zero-imports test is the load-bearing one: pre-boot routing has a ~3ms
budget, so building the trie must not import a single job module.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from functualize.app.utils import (
    BUILTIN_SEGMENT,
    NodeKind,
    build_group_trie,
    read_routing_rows_from_cache,
    resolve_cache_path,
)

JOB_FILES = {
    "top.py": "def top_level():\n    '''Ungrouped.'''\n",
    "grouped.py": (
        "JOB_GROUP = 'infra.aws'\n\n\n"
        "def provision_it():\n    '''Nested group.'''\n\n\n"
        "def tear_down():\n    '''Also nested.'''\n"
    ),
    "single.py": (
        "from functualize.job import job\n\n\n"
        "@job(group='deploy')\n"
        "def web():\n    '''Single-level group.'''\n"
    ),
}


@pytest.fixture
def cached_project(cli_run, project_tree) -> Path:
    """A project whose cache has been written by a real scan."""
    root = project_tree(jobs=JOB_FILES)
    result = cli_run(["top-level"], cwd=root)
    assert result.exit_code == 0, result.stderr
    return Path(root)


def _rows(root: Path):
    rows = read_routing_rows_from_cache(resolve_cache_path(root))
    assert rows is not None, "expected a readable cache"
    return rows


class TestIngestionFromRealCache:
    def test_rows_carry_the_group_name_pairing(self, cached_project: Path) -> None:
        by_name = {name: group for group, name, _ in _rows(cached_project)}
        assert by_name["top-level"] is None
        assert by_name["infra.aws.provision-it"] == "infra.aws"
        assert by_name["deploy.web"] == "deploy"

    def test_nested_group_lands_at_the_right_path(self, cached_project: Path) -> None:
        trie = build_group_trie(_rows(cached_project))
        aws = trie.root.children["infra"].children["aws"]
        assert sorted(aws.children) == ["provision-it", "tear-down"]
        assert aws.children["provision-it"].payload == "infra.aws.provision-it"
        # The failure mode this guards: a node literally named "infra.aws".
        assert "infra.aws" not in trie.root.children

    def test_resolution_reaches_every_cached_job(self, cached_project: Path) -> None:
        rows = _rows(cached_project)
        trie = build_group_trie(rows)
        for _group, name, _kind in rows:
            resolution = trie.resolve(name.split("."))
            assert resolution.node.payload == name, name
            assert resolution.remaining == ()

    def test_builtin_node_coexists_with_scanned_jobs(
        self, cached_project: Path
    ) -> None:
        trie = build_group_trie(_rows(cached_project))
        assert trie.root.children[BUILTIN_SEGMENT].kind is NodeKind.BUILTIN

    def test_plugin_namespaces_are_layered_over_the_cached_rows(
        self, cached_project: Path
    ) -> None:
        """Plugin commands are never cached, so they arrive as a second input.

        This is the two-population shape: cached job rows pre-boot, plugin
        namespace rows added once the app has booted.
        """
        trie = build_group_trie(
            _rows(cached_project), [("mcp", "serve"), ("mcp", "tools")]
        )
        assert sorted(trie.root.children["mcp"].children) == ["serve", "tools"]
        assert trie.root.children["mcp"].children["serve"].kind is NodeKind.PLUGIN
        # ...and the cached jobs are still where they were.
        assert trie.resolve(["deploy", "web"]).node.payload == "deploy.web"


class TestBuildImportsNothing:
    def test_reading_rows_and_building_imports_no_job_module(
        self, cached_project: Path
    ) -> None:
        """Pre-boot routing has a ~3ms budget — a job import blows it."""
        job_modules = {"top", "grouped", "single"}
        for name in job_modules:
            sys.modules.pop(name, None)

        with patch("importlib.import_module") as mock_import:
            rows = read_routing_rows_from_cache(resolve_cache_path(cached_project))
            trie = build_group_trie(rows or [])
            trie.resolve(["infra", "aws", "provision-it"])
            trie.children(["infra"])

        assert not mock_import.called, (
            f"importlib.import_module called while building/querying the trie: "
            f"{mock_import.call_args_list}"
        )
        assert not (job_modules & set(sys.modules)), (
            f"job modules entered sys.modules: {job_modules & set(sys.modules)}"
        )

    def test_trie_holds_no_callables(self, cached_project: Path) -> None:
        """Payloads are name strings. A callable here would mean an import."""
        trie = build_group_trie(_rows(cached_project))

        def walk(node):
            assert node.payload is None or isinstance(node.payload, str)
            for child in node.children.values():
                walk(child)

        walk(trie.root)


class TestMissingOrStaleCache:
    def test_absent_cache_returns_none(self, tmp_path: Path) -> None:
        assert read_routing_rows_from_cache(tmp_path / "nope.json") is None

    def test_wrong_version_returns_none(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache.json"
        cache.write_text('{"version": 0, "entries": {}}', encoding="utf-8")
        assert read_routing_rows_from_cache(cache) is None

    def test_malformed_cache_returns_none(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache.json"
        cache.write_text("not json{", encoding="utf-8")
        assert read_routing_rows_from_cache(cache) is None
