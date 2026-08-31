"""`exclude_patterns` against a project with more than one scan root.

Every pre-existing exclusion test uses a single job directory, which is why the
defect below reached 0.1.1. `GlobExcludePreFilter` was handed one `base_dir` —
`jobs_directories[0]` — and *admitted* any file not under it, so an exclusion
governed the first root and silently not the rest.

That is a filtering bug on its own (`docs/cli/discovery.md` documents matching
"relative to the scanned directory", which is what these tests assert). It was also
a cache bug, because `base_dir` is not one of the nine fingerprinted
`DiscoveryConfig` fields: reordering `jobs_directories` changed the correct cache
contents while the digest stayed equal, so a warm cache was replayed under the
wrong answer. Fixing the filter closes both — see ADR-011.

`test_reordering_roots_is_safe_against_a_warm_cache` is the transition, and the one
that matters: the other two run cold, and every filter test that ran cold stayed
green through this whole class of defect.

Listings are asserted on **stdout only**. stderr carries the invalidation warning
and the scanned file paths, both of which contain the job names.
"""

from __future__ import annotations

from pathlib import Path

from tests.conftest import surfaces

# ─── Surface ──────────────────────────────────────────────────────────────
#
# `--exclude` is a pre-command global of the bare `func` CLI only; see the
# note in `test_cache_filter_awareness.py`.
pytestmark = surfaces("func")

_PYPROJECT = """[project]
name = "multi-root-fixture"
version = "0.1.0"
"""


def _toml(first: str, second: str) -> str:
    return (
        f'jobs_directories = ["{first}", "{second}"]\n\n'
        "[discovery]\n"
        'exclude_patterns = ["test_*.py"]\n'
    )


_FILES = {
    "a/keep_a.py": '"""Kept in root a."""\n\n\ndef keep_a() -> str:\n    return "a"\n',
    "a/test_x.py": '"""Excluded in root a."""\n\n\ndef xa() -> str:\n    return "xa"\n',
    "b/keep_b.py": '"""Kept in root b."""\n\n\ndef keep_b() -> str:\n    return "b"\n',
    "b/test_y.py": '"""Excluded in root b."""\n\n\ndef yb() -> str:\n    return "yb"\n',
}


def _tree(project_tree, first: str, second: str) -> Path:
    return project_tree(
        pyproject=_PYPROJECT,
        functualize_toml=_toml(first, second),
        extra_files=_FILES,
    )


def _write_order(root: Path, first: str, second: str) -> None:
    (root / ".functualize.toml").write_text(_toml(first, second), encoding="utf-8")


def _listed(result) -> set[str]:
    """Job names from a bare listing's stdout, ignoring the builtin `mcp` group."""
    names = set()
    for line in result.stdout.splitlines():
        head = line.split("—")[0].strip()
        if head and head != "mcp":
            names.add(head)
    return names


class TestExclusionAppliesToEveryScanRoot:
    def test_both_roots_are_filtered_on_a_cold_cache(self, cli_run, project_tree):
        """The bug: only `a/test_x.py` was excluded; `b/test_y.py` rode through.

        `b/test_y.py` is not under `jobs_directories[0]`, so relativizing against
        that one directory raised ValueError and the file was admitted unjudged.
        """
        root = _tree(project_tree, "a", "b")

        listing = cli_run([], cwd=root)

        assert listing.exit_code == 0
        assert _listed(listing) == {"keep-a", "keep-b"}, (
            "an exclusion must apply to every scan root, not only the first"
        )

    def test_root_order_does_not_change_the_listing(self, cli_run, project_tree):
        """Two cold runs that differ only in root order must agree.

        While they did not, the identical `discovery_hash` for both was a cache
        defect rather than a cache bug: the digest was correct about the nine
        settings and blind to the tenth input.
        """
        ab = _tree(project_tree, "a", "b")
        ba = _tree(project_tree, "b", "a")

        assert _listed(cli_run([], cwd=ab)) == _listed(cli_run([], cwd=ba))


class TestWarmCacheSurvivesARootReorder:
    def test_reordering_roots_is_safe_against_a_warm_cache(self, cli_run, project_tree):
        """The transition. Warm under one order, then invoke under the other.

        Before ADR-011 this served the first order's answer — `yb` where the cold
        run gives `xa` — because the two orders fingerprint identically.
        """
        root = _tree(project_tree, "a", "b")

        warm = cli_run([], cwd=root)
        assert warm.exit_code == 0

        _write_order(root, "b", "a")
        reordered = cli_run([], cwd=root)

        assert reordered.exit_code == 0
        assert _listed(reordered) == {"keep-a", "keep-b"}, (
            "a root reorder must not replay the previous order's cached decisions"
        )
