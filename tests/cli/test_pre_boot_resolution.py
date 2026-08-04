"""Unit tests for pre-boot name resolution utilities.

Tests read_routing_names_from_cache() and enumerate_group_names() from
functualize.app.utils — the warm and cold paths for pre-boot CLI routing.

Validates: Requirements 7
"""

from __future__ import annotations

import json
from pathlib import Path

from functualize._primitives.cache_format import CACHE_VERSION
from functualize.app.utils import enumerate_group_names, read_routing_names_from_cache


class TestReadRoutingNamesFromCache:
    """Tests for read_routing_names_from_cache (warm boot path)."""

    def test_valid_cache_with_groups_returns_names_and_ancestor_prefixes(
        self, tmp_path: Path
    ) -> None:
        """Valid cache with groups returns (job_names, group_names) including ancestors."""
        cache = tmp_path / "cache.json"
        cache.write_text(
            json.dumps(
                {
                    "version": CACHE_VERSION,
                    "entries": {
                        "infra.provision": {
                            "name": "infra.provision",
                            "group": "infra",
                        },
                        "infra.teardown": {
                            "name": "infra.teardown",
                            "group": "infra",
                        },
                        "deploy": {
                            "name": "deploy",
                            "group": None,
                        },
                    },
                }
            )
        )

        result = read_routing_names_from_cache(cache)
        assert result is not None
        job_names, group_names = result
        assert job_names == {"infra.provision", "infra.teardown", "deploy"}
        assert group_names == {"infra"}

    def test_nested_group_emits_ancestor_prefixes(self, tmp_path: Path) -> None:
        """Cache with nested group 'infra.aws' emits both 'infra.aws' and 'infra'."""
        cache = tmp_path / "cache.json"
        cache.write_text(
            json.dumps(
                {
                    "version": CACHE_VERSION,
                    "entries": {
                        "infra.aws.provision": {
                            "name": "infra.aws.provision",
                            "group": "infra.aws",
                        },
                    },
                }
            )
        )

        result = read_routing_names_from_cache(cache)
        assert result is not None
        job_names, group_names = result
        assert job_names == {"infra.aws.provision"}
        assert "infra.aws" in group_names
        assert "infra" in group_names

    def test_missing_cache_returns_none(self, tmp_path: Path) -> None:
        """Non-existent cache file returns None."""
        cache = tmp_path / "nonexistent.json"
        result = read_routing_names_from_cache(cache)
        assert result is None

    def test_malformed_json_returns_none(self, tmp_path: Path) -> None:
        """Malformed JSON content returns None."""
        cache = tmp_path / "cache.json"
        cache.write_text("not valid json {{{")

        result = read_routing_names_from_cache(cache)
        assert result is None

    def test_wrong_version_returns_none(self, tmp_path: Path) -> None:
        """Cache with wrong version number returns None."""
        cache = tmp_path / "cache.json"
        cache.write_text(
            json.dumps(
                {
                    "version": 999,
                    "entries": {
                        "deploy": {"name": "deploy", "group": None},
                    },
                }
            )
        )

        result = read_routing_names_from_cache(cache)
        assert result is None

    def test_ungrouped_jobs_populate_job_names_only(self, tmp_path: Path) -> None:
        """Cache with only ungrouped jobs: job_names populated, group_names empty."""
        cache = tmp_path / "cache.json"
        cache.write_text(
            json.dumps(
                {
                    "version": CACHE_VERSION,
                    "entries": {
                        "deploy": {"name": "deploy", "group": None},
                        "migrate": {"name": "migrate", "group": None},
                    },
                }
            )
        )

        result = read_routing_names_from_cache(cache)
        assert result is not None
        job_names, group_names = result
        assert job_names == {"deploy", "migrate"}
        assert group_names == set()


class TestOldCacheAutoInvalidation:
    """Tests that old cache files (with bare names) auto-invalidate on boot.

    Validates: Requirement 15.2 — Old cache files with bare names for grouped
    jobs SHALL be auto-invalidated on first boot.

    The mechanism is version-check based:
    - read_routing_names_from_cache() checks the shared CACHE_VERSION
    - Old cache with version=1 or missing version → returns None
    - This triggers cold boot fallback (AST scan / full import) which produces
      correct qualified names for JOB_GROUP modules.
    """

    def test_version_1_cache_with_bare_names_returns_none(self, tmp_path: Path) -> None:
        """Old cache (version 1) with bare names for grouped jobs returns None.

        Simulates a pre-JOB_GROUP cache where grouped jobs were stored with bare
        names like 'provision' instead of 'infra.provision'. The version check
        rejects this cache entirely, triggering a cold boot re-scan.
        """
        cache = tmp_path / "cache.json"
        cache.write_text(
            json.dumps(
                {
                    "version": 1,
                    "entries": {
                        "provision": {
                            "name": "provision",
                            "group": None,
                        },
                        "teardown": {
                            "name": "teardown",
                            "group": None,
                        },
                    },
                }
            )
        )

        result = read_routing_names_from_cache(cache)
        assert result is None

    def test_no_version_field_cache_returns_none(self, tmp_path: Path) -> None:
        """Cache without a version field (very old format) returns None."""
        cache = tmp_path / "cache.json"
        cache.write_text(
            json.dumps(
                {
                    "entries": {
                        "deploy": {"name": "deploy", "group": None},
                    },
                }
            )
        )

        result = read_routing_names_from_cache(cache)
        assert result is None

    def test_cold_boot_fallback_produces_qualified_names(self, tmp_path: Path) -> None:
        """After old cache is rejected, cold boot AST scan yields qualified names.

        The full flow: old cache → None → enumerate_group_names() → correct groups.
        """
        # Old cache with bare names (version 1 → rejected)
        cache = tmp_path / "cache.json"
        cache.write_text(
            json.dumps(
                {
                    "version": 1,
                    "entries": {
                        "provision": {"name": "provision", "group": None},
                    },
                }
            )
        )

        # Verify cache is rejected
        result = read_routing_names_from_cache(cache)
        assert result is None

        # Create a jobs directory with a JOB_GROUP module
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / "infra.py").write_text(
            'JOB_GROUP = "infra"\n\ndef provision(): pass\ndef teardown(): pass\n'
        )

        # Cold boot fallback: AST scan finds the correct group names
        group_names = enumerate_group_names([str(jobs_dir)])
        assert "infra" in group_names


class TestEnumerateGroupNames:
    """Tests for enumerate_group_names (cold boot AST scan path)."""

    def test_directory_with_single_group(self, tmp_path: Path) -> None:
        """File with JOB_GROUP = 'infra' returns {'infra'}."""
        (tmp_path / "infra_jobs.py").write_text(
            'JOB_GROUP = "infra"\n\ndef provision(): pass\n'
        )

        result = enumerate_group_names([str(tmp_path)])
        assert result == {"infra"}

    def test_nested_group_emits_ancestors(self, tmp_path: Path) -> None:
        """File with JOB_GROUP = 'infra.aws' returns {'infra.aws', 'infra'}."""
        (tmp_path / "aws_jobs.py").write_text(
            'JOB_GROUP = "infra.aws"\n\ndef provision(): pass\n'
        )

        result = enumerate_group_names([str(tmp_path)])
        assert "infra.aws" in result
        assert "infra" in result

    def test_empty_directory_returns_empty_set(self, tmp_path: Path) -> None:
        """Empty directory yields no group names."""
        result = enumerate_group_names([str(tmp_path)])
        assert result == set()

    def test_file_with_syntax_error_is_skipped(self, tmp_path: Path) -> None:
        """Files that fail to parse are skipped gracefully."""
        (tmp_path / "broken.py").write_text("def oops(\n")  # syntax error
        (tmp_path / "good.py").write_text('JOB_GROUP = "infra"\n\ndef run(): pass\n')

        result = enumerate_group_names([str(tmp_path)])
        assert result == {"infra"}

    def test_non_string_job_group_value_is_ignored(self, tmp_path: Path) -> None:
        """Non-string JOB_GROUP values (e.g., int) are ignored."""
        (tmp_path / "bad_group.py").write_text("JOB_GROUP = 42\n\ndef run(): pass\n")

        result = enumerate_group_names([str(tmp_path)])
        assert result == set()
