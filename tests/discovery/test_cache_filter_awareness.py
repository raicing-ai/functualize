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

X4 is asserted through the real CLI (`cli_run`), not through the provider, because
the defect was user-visible as `Unknown command 'beta'` and only an end-to-end
assertion sees that. Routing does resolve job names from the cache before the app
boots — but a routing miss falls through to a handler that boots anyway, so the
booted provider's invalidation repairs the cache on every surface. That is why
`b5f918e` reverted the pre-boot fingerprint wiring rather than shipping it.
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


class TestBareListingReflectsTheCurrentFilterConfig:
    """The plain `func` listing, in both filter directions.

    This class once claimed to pin the pre-boot routing read's fingerprint. Both
    halves of that claim were measured false and the class was renamed:

    - The routing wiring it named was reverted in `b5f918e` precisely *because*
      removing it left these assertions green.
    - Bare `func` does **not** render without booting. Against a cache poisoned
      by `--exclude`, a bare `func` rewrites the header from the filtered digest
      to the all-defaults one, restores the excluded entry, clears
      `pre_filter_decisions`, and logs one invalidation line to stderr. It is
      `_handle_bare` booting the app, exactly like every other surface.

    What they do prove is worth keeping: the listing a user sees with no flags
    tracks the *current* filter configuration, in both directions, against a warm
    cache written under the other one.

    Asserts on **stdout only**. stderr carries the invalidation warning and the
    scanned file paths, both of which contain the substring "beta" — an
    assertion over the combined streams passes while the listing is wrong.
    """

    def test_bare_listing_shows_the_job_again_after_the_flag_is_dropped(
        self, cli_run, project_tree
    ) -> None:
        root = _tree(project_tree)

        cli_run(["--exclude", "test_*.py", "builtin", "info"], cwd=root)
        listing = cli_run([], cwd=root)

        assert listing.exit_code == 0
        assert "alpha" in listing.stdout
        assert "beta" in listing.stdout, (
            "the bare listing is served from the pre-boot routing read; if beta "
            "is missing, that read replayed a cache written under --exclude"
        )

    def test_bare_listing_hides_the_job_when_the_filter_is_added(
        self, cli_run, project_tree
    ) -> None:
        """The same read, in the other direction."""
        root = _tree(project_tree)

        cli_run(["builtin", "info"], cwd=root)
        (root / ".functualize.toml").write_text(
            '[discovery]\nexclude_patterns = ["test_*.py"]\n', encoding="utf-8"
        )
        listing = cli_run([], cwd=root)

        assert listing.exit_code == 0
        assert "alpha" in listing.stdout
        assert "beta" not in listing.stdout


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


class TestCacheRebuildLeavesAUsableCache:
    """`func builtin cache rebuild` must leave a cache the next command reuses.

    It unlinked the file and *then* built a bare provider, so there was nothing
    left to carry a fingerprint and it persisted `discovery_hash: null`. The next
    command read that as a mismatch and rescanned -- discarding the rebuild it had
    just been asked for, with a warning, in every project including one with no
    filters configured. See ADR-011.

    Asserts on **stderr** here on purpose: the invalidation line is the symptom,
    and it is the stream it is logged to.
    """

    def test_a_rebuilt_cache_is_not_invalidated_by_the_next_command(
        self, cli_run, project_tree
    ) -> None:
        root = _tree(project_tree)
        cli_run(["builtin", "info"], cwd=root)

        rebuilt = cli_run(["builtin", "cache", "rebuild"], cwd=root)
        assert rebuilt.exit_code == 0

        following = cli_run(["builtin", "info"], cwd=root)

        assert following.exit_code == 0
        assert "Cache invalidated" not in following.stderr, (
            "the rebuild wrote a fingerprint the very next boot disagreed with"
        )

    def test_rebuild_writes_a_fingerprint(self, cli_run, project_tree) -> None:
        root = _tree(project_tree)
        cli_run(["builtin", "info"], cwd=root)
        cli_run(["builtin", "cache", "rebuild"], cwd=root)

        data = json.loads(resolve_cache_path(root).read_text(encoding="utf-8"))

        assert isinstance(data.get("discovery_hash"), str)

    def test_rebuild_honours_a_flag_on_its_own_invocation(
        self, cli_run, project_tree
    ) -> None:
        """It rebuilt unfiltered, so it re-admitted what the caller excluded."""
        root = _tree(project_tree)

        rebuilt = cli_run(
            ["--exclude", "test_*.py", "builtin", "cache", "rebuild"], cwd=root
        )

        assert rebuilt.exit_code == 0
        assert "1 entries" in rebuilt.stdout, (
            f"expected the filtered count, got {rebuilt.stdout!r}"
        )

    def test_rebuild_honours_a_configured_filter(self, cli_run, project_tree) -> None:
        root = _tree(project_tree, '[discovery]\nexclude_patterns = ["test_*.py"]\n')

        rebuilt = cli_run(["builtin", "cache", "rebuild"], cwd=root)

        assert rebuilt.exit_code == 0
        assert "1 entries" in rebuilt.stdout, (
            f"expected the filtered count, got {rebuilt.stdout!r}"
        )
