"""Warm-cache regression tests for discovery-filter awareness.

Every pre-existing filter test runs against a *cold* cache, which is exactly why
this class of bug survived to 0.1.0. These run the transitions instead: warm the
cache under one filter configuration, then invoke under another, and assert the
second invocation is judged on its own configuration rather than on the cached
decisions of the first.

The reproductions are named X2/X3/X4 after `.spec/STATUS.md`:

- **X2** warm-then-filter: a plain run, then `--exclude`.
- **X3** config-added-after-warm: a plain run, then `[discovery] exclude_patterns`
  in `.functualize.toml`. The likeliest of the three to be hit, because it is the
  ordinary path — use the tool, then add a filter to the config.
- **X4** filtered-then-unfiltered: `--exclude` once, then no flag at all. The one
  that matters: it removed a job from the CLI *permanently*.

X4 is asserted through the real CLI (`cli_run`), not through the provider. It has
to be: routing resolves job names from the cache *before* the app boots, so a
provider-level test passes while `func <job>` still answers "Unknown command".
"""

from __future__ import annotations

import json
from pathlib import Path

from functualize._primitives.cache_format import resolve_cache_path

_ALPHA = """\"\"\"A job that must survive every filter transition.\"\"\"


def alpha() -> str:
    return "alpha-ran"
"""

_TEST_BETA = """\"\"\"A job in a file the `test_*.py` exclusion pattern matches.\"\"\"


def beta() -> str:
    return "beta-ran"
"""

_PYPROJECT = """[project]
name = "filter-awareness-fixture"
version = "0.1.0"
"""


def _tree(project_tree, functualize_toml: str | None = None) -> Path:
    return project_tree(
        pyproject=_PYPROJECT,
        functualize_toml=functualize_toml,
        jobs={"alpha.py": _ALPHA, "test_beta.py": _TEST_BETA},
        convention_dirs=True,
    )


def _listed(result) -> str:
    return result.stdout + result.stderr


class TestWarmCacheHonoursFilterChanges:
    """The three transitions from the STATUS.md reproduction table."""

    def test_x1_cold_cache_with_exclude_hides_the_excluded_job(
        self, cli_run, project_tree
    ) -> None:
        """The control. This one already worked — it is here so a regression in
        the cold path is not mistaken for a warm-path fix."""
        root = _tree(project_tree)

        result = cli_run(["--exclude", "test_*.py", "builtin", "info"], cwd=root)

        assert result.exit_code == 0
        assert "alpha" in _listed(result)
        assert "beta" not in _listed(result)

    def test_x2_exclude_applies_against_a_warm_cache(
        self, cli_run, project_tree
    ) -> None:
        """A plain run first, then --exclude. The exclusion must still apply."""
        root = _tree(project_tree)

        warm = cli_run(["builtin", "info"], cwd=root)
        assert warm.exit_code == 0
        assert "beta" in _listed(warm), "fixture must register beta on a cold run"

        result = cli_run(["--exclude", "test_*.py", "builtin", "info"], cwd=root)

        assert result.exit_code == 0
        assert "alpha" in _listed(result)
        assert "beta" not in _listed(result)

    def test_x3_config_added_after_warm_cache_applies(
        self, cli_run, project_tree
    ) -> None:
        """Use the tool, then add a filter to the config. No `cache clear`."""
        root = _tree(project_tree)

        warm = cli_run(["builtin", "info"], cwd=root)
        assert warm.exit_code == 0
        assert "beta" in _listed(warm)

        (root / ".functualize.toml").write_text(
            '[discovery]\nexclude_patterns = ["test_*.py"]\n', encoding="utf-8"
        )

        result = cli_run(["builtin", "info"], cwd=root)

        assert result.exit_code == 0
        assert "alpha" in _listed(result)
        assert "beta" not in _listed(result)

    def test_x4_dropping_the_flag_restores_the_job(self, cli_run, project_tree) -> None:
        """The headline defect: one --exclude run removed a job permanently."""
        root = _tree(project_tree)

        filtered = cli_run(["--exclude", "test_*.py", "builtin", "info"], cwd=root)
        assert filtered.exit_code == 0
        assert "beta" not in _listed(filtered)

        result = cli_run(["builtin", "info"], cwd=root)

        assert result.exit_code == 0
        assert "alpha" in _listed(result)
        assert "beta" in _listed(result), (
            "beta must come back once the flag is dropped; if this fails the "
            "pre-boot routing read is replaying the filtered cache"
        )

    def test_x4_the_job_is_invocable_again_not_merely_listed(
        self, cli_run, project_tree
    ) -> None:
        """`func beta` answered "Unknown command 'beta'", so listing is not enough.

        This is the assertion that fails when only the booted provider is taught
        the fingerprint and the pre-boot routing read is not.
        """
        root = _tree(project_tree)

        cli_run(["--exclude", "test_*.py", "builtin", "info"], cwd=root)
        result = cli_run(["beta"], cwd=root)

        assert result.exit_code == 0, (
            f"beta must run after the flag is dropped; got {result.exit_code}: "
            f"{_listed(result)!r}"
        )
        assert "Unknown command" not in _listed(result)


class TestCacheInspectionIsNonDestructive:
    """Inspecting a cache under the config that wrote it must not disturb it.

    `func builtin cache show` builds a bare provider over the CWD with no
    discovery config. If "no config" were treated as "the empty config", that
    provider would fail the fingerprint check against any cache written under an
    active filter and delete it — an inspection command mutating what it
    inspects. "No config" therefore means "skip the check".

    Note the scope of the claim. Under a *different* effective config the cache
    genuinely is stale and discarding it is the correct repair, not a defect;
    that path is `test_x4_*`. What must never happen is a *matching* config
    losing its cache to a read-only command.
    """

    def test_cache_show_leaves_a_matching_cache_byte_identical(
        self, cli_run, project_tree
    ) -> None:
        root = _tree(project_tree)
        cli_run(["builtin", "info"], cwd=root)

        cache_path = resolve_cache_path(root)
        assert cache_path.exists(), "fixture must have produced a cache"
        before = cache_path.read_bytes()

        result = cli_run(["builtin", "cache", "show"], cwd=root)

        assert result.exit_code == 0
        assert cache_path.exists(), "cache show must not delete a matching cache"
        assert cache_path.read_bytes() == before


class TestCacheHeaderCarriesTheFingerprint:
    def test_a_filtered_run_writes_a_discovery_hash(
        self, cli_run, project_tree
    ) -> None:
        root = _tree(project_tree)
        cli_run(["--exclude", "test_*.py", "builtin", "info"], cwd=root)

        data = json.loads(resolve_cache_path(root).read_text(encoding="utf-8"))

        assert isinstance(data.get("discovery_hash"), str)
        assert data["discovery_hash"].startswith("sha256:")

    def test_the_fingerprint_differs_between_filtered_and_unfiltered_runs(
        self, cli_run, project_tree
    ) -> None:
        root = _tree(project_tree)

        cli_run(["--exclude", "test_*.py", "builtin", "info"], cwd=root)
        filtered = json.loads(resolve_cache_path(root).read_text(encoding="utf-8"))[
            "discovery_hash"
        ]

        cli_run(["builtin", "info"], cwd=root)
        plain = json.loads(resolve_cache_path(root).read_text(encoding="utf-8"))[
            "discovery_hash"
        ]

        assert filtered != plain
