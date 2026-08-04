"""Unit tests for ResourceLocator in functualize.primitives.locator.

Tests cover:
- Fluent builder API
- resolve() union/dedup/priority semantics
- resolve_one() first-wins semantics
- writable() directory creation and error handling
- introspect() provenance information
- Read/write asymmetry (standalone vs declared-project mode)
- Platform cache path computation
- search_upward() traversal with markers
"""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize._primitives.locator import (
    LocateResult,
    ResourceLocator,
    ResourceLocatorError,
    compute_project_id,
)


class TestResourceLocatorBuilder:
    """Test fluent builder API returns Self for chaining."""

    def test_builder_methods_return_self(self, tmp_path: Path):
        locator = ResourceLocator()
        result = (
            locator.search_explicit(tmp_path)
            .search_upward()
            .search_platform_cache("abc123")
            .search_platform_user()
            .when_env("MY_VAR")
            .write_to_explicit(tmp_path)
        )
        assert result is locator

    def test_write_to_platform_cache_returns_self(self):
        locator = ResourceLocator()
        result = locator.write_to_platform_cache("test_id")
        assert result is locator


class TestResolve:
    """Test resolve(pattern) — union, dedup, priority ordering."""

    def test_resolve_empty_when_no_sources(self):
        locator = ResourceLocator()
        assert locator.resolve("*.txt") == []

    def test_resolve_empty_when_no_matches(self, tmp_path: Path):
        (tmp_path / "file.py").write_text("x")
        locator = ResourceLocator().search_explicit(tmp_path)
        assert locator.resolve("*.txt") == []

    def test_resolve_finds_matching_files(self, tmp_path: Path):
        (tmp_path / "config.toml").write_text("[x]")
        (tmp_path / "data.toml").write_text("[y]")
        (tmp_path / "readme.md").write_text("# hi")

        locator = ResourceLocator().search_explicit(tmp_path)
        results = locator.resolve("*.toml")

        assert len(results) == 2
        names = [Path(r).name for r in results]
        assert "config.toml" in names
        assert "data.toml" in names

    def test_resolve_deduplicates_by_absolute_path(self, tmp_path: Path):
        """Same file accessible from two sources should appear only once."""
        (tmp_path / "shared.txt").write_text("shared")

        locator = (
            ResourceLocator()
            .search_explicit(tmp_path)
            .search_explicit(tmp_path)  # duplicate source
        )
        results = locator.resolve("*.txt")
        assert len(results) == 1

    def test_resolve_preserves_source_priority_order(self, tmp_path: Path):
        """Files from higher priority source come first."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        (dir_a / "alpha.txt").write_text("a")
        (dir_b / "beta.txt").write_text("b")

        locator = ResourceLocator().search_explicit(dir_a).search_explicit(dir_b)
        results = locator.resolve("*.txt")

        assert len(results) == 2
        assert Path(results[0]).name == "alpha.txt"
        assert Path(results[1]).name == "beta.txt"

    def test_resolve_skips_nonexistent_directories(self, tmp_path: Path):
        existing = tmp_path / "exists"
        existing.mkdir()
        (existing / "file.txt").write_text("hi")

        locator = (
            ResourceLocator()
            .search_explicit(tmp_path / "nonexistent")
            .search_explicit(existing)
        )
        results = locator.resolve("*.txt")
        assert len(results) == 1


class TestResolveOne:
    """Test resolve_one(relative_path) — first source wins."""

    def test_resolve_one_returns_none_when_no_sources(self):
        locator = ResourceLocator()
        assert locator.resolve_one("config.toml") is None

    def test_resolve_one_returns_none_when_not_found(self, tmp_path: Path):
        locator = ResourceLocator().search_explicit(tmp_path)
        assert locator.resolve_one("nonexistent.txt") is None

    def test_resolve_one_returns_first_match(self, tmp_path: Path):
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        (dir_a / "config.toml").write_text("from_a")
        (dir_b / "config.toml").write_text("from_b")

        locator = ResourceLocator().search_explicit(dir_a).search_explicit(dir_b)
        result = locator.resolve_one("config.toml")

        assert result is not None
        assert result == str((dir_a / "config.toml").resolve())

    def test_resolve_one_finds_in_second_source_if_first_lacks_it(self, tmp_path: Path):
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        (dir_b / "only_here.txt").write_text("found")

        locator = ResourceLocator().search_explicit(dir_a).search_explicit(dir_b)
        result = locator.resolve_one("only_here.txt")

        assert result is not None
        assert Path(result).name == "only_here.txt"


class TestWritable:
    """Test writable(relative_path) — write target + directory creation."""

    def test_writable_raises_when_no_write_target(self):
        locator = ResourceLocator()
        with pytest.raises(ResourceLocatorError, match="No write target configured"):
            locator.writable("cache.json")

    def test_writable_creates_parent_directories(self, tmp_path: Path):
        write_dir = tmp_path / "output" / "deep"
        locator = ResourceLocator().write_to_explicit(write_dir)

        result = locator.writable("sub/dir/file.json")

        assert result == write_dir / "sub" / "dir" / "file.json"
        assert result.parent.exists()

    def test_writable_returns_path_within_write_target(self, tmp_path: Path):
        write_dir = tmp_path / "cache"
        locator = ResourceLocator().write_to_explicit(write_dir)

        result = locator.writable("state.db")

        assert str(result).startswith(str(write_dir.resolve()))

    def test_writable_with_platform_cache(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        locator = ResourceLocator().write_to_platform_cache("abc123def456")

        result = locator.writable("cache.json")

        expected_dir = tmp_path / "functualize" / "abc123def456"
        assert str(result).startswith(str(expected_dir))
        assert result.name == "cache.json"

    def test_writable_raises_on_permission_error(self, tmp_path: Path, monkeypatch):
        """Test that permission errors are wrapped in ResourceLocatorError."""
        locator = ResourceLocator().write_to_explicit("/root/no_permission_here")

        # This should raise because /root/no_permission_here is not writable
        # On some systems this might actually succeed if running as root,
        # so we mock the mkdir to simulate permission error
        from unittest.mock import patch

        with (
            patch.object(Path, "mkdir", side_effect=PermissionError("denied")),
            pytest.raises(ResourceLocatorError, match="Failed to create"),
        ):
            locator.writable("test.json")


class TestIntrospect:
    """Test introspect(pattern) — resolve with provenance."""

    def test_introspect_returns_locate_results(self, tmp_path: Path):
        (tmp_path / "config.toml").write_text("[x]")

        locator = ResourceLocator().search_explicit(tmp_path)
        results = locator.introspect("*.toml")

        assert len(results) == 1
        assert isinstance(results[0], LocateResult)
        assert results[0].path == str((tmp_path / "config.toml").resolve())
        assert "explicit" in results[0].source
        assert results[0].priority == 0

    def test_introspect_shows_multiple_sources(self, tmp_path: Path):
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        (dir_a / "file.txt").write_text("a")
        (dir_b / "other.txt").write_text("b")

        locator = ResourceLocator().search_explicit(dir_a).search_explicit(dir_b)
        results = locator.introspect("*.txt")

        assert len(results) == 2
        assert results[0].priority < results[1].priority


class TestSearchUpward:
    """Test search_upward() traversal behavior."""

    def test_search_upward_finds_file_in_ancestor(self, tmp_path: Path):
        # Create nested structure: tmp_path/a/b/c with file in tmp_path
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        (tmp_path / "root.conf").write_text("found")

        locator = ResourceLocator().search_upward(start=nested, stop=tmp_path.parent)
        result = locator.resolve_one("root.conf")

        assert result is not None
        assert Path(result).name == "root.conf"

    def test_search_upward_stops_at_marker(self, tmp_path: Path):
        # Structure: tmp_path/project/sub/deep
        # Marker at tmp_path/project/.functualize
        project = tmp_path / "project"
        marker = project / ".functualize"
        deep = project / "sub" / "deep"
        deep.mkdir(parents=True)
        marker.mkdir()

        # Place a file above the marker (should not be found)
        (tmp_path / "above.txt").write_text("above")
        # Place a file at the marker level
        (project / "at_marker.txt").write_text("here")

        locator = ResourceLocator().search_upward(
            start=deep, stop=tmp_path.parent, marker=".functualize"
        )
        results = locator.resolve("*.txt")

        # Should find at_marker.txt but not above.txt
        names = [Path(r).name for r in results]
        assert "at_marker.txt" in names
        assert "above.txt" not in names

    def test_search_upward_from_cwd_default(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "cwd_file.txt").write_text("here")

        locator = ResourceLocator().search_upward()
        result = locator.resolve_one("cwd_file.txt")

        assert result is not None


class TestReadWriteAsymmetry:
    """Test standalone vs declared-project mode semantics."""

    def test_standalone_mode_writes_to_xdg_cache(self, tmp_path: Path, monkeypatch):
        """Standalone mode: write to XDG cache, not project directory."""
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg_cache"))

        project_id = compute_project_id("/some/project/path")
        locator = (
            ResourceLocator()
            .search_explicit(tmp_path / "project")
            .write_to_platform_cache(project_id)
        )

        writable_path = locator.writable("cache.json")

        # Write target should be in XDG cache, not in project
        assert str(tmp_path / "xdg_cache") in str(writable_path)
        assert "functualize" in str(writable_path)
        assert project_id in str(writable_path)

    def test_declared_project_mode_writes_to_functualize_dir(self, tmp_path: Path):
        """Declared-project mode: write to .functualize/ directory."""
        functualize_dir = tmp_path / ".functualize"
        functualize_dir.mkdir()

        locator = (
            ResourceLocator()
            .search_explicit(functualize_dir)
            .write_to_explicit(functualize_dir)
        )

        writable_path = locator.writable("cache.json")
        assert str(functualize_dir.resolve()) in str(writable_path)


class TestComputeProjectId:
    """Test compute_project_id() deterministic hashing."""

    def test_deterministic_for_same_path(self):
        id1 = compute_project_id("/home/user/project")
        id2 = compute_project_id("/home/user/project")
        assert id1 == id2

    def test_different_for_different_paths(self):
        id1 = compute_project_id("/home/user/project_a")
        id2 = compute_project_id("/home/user/project_b")
        assert id1 != id2

    def test_returns_12_characters(self):
        project_id = compute_project_id("/any/path")
        assert len(project_id) == 12

    def test_is_hex_string(self):
        project_id = compute_project_id("/any/path")
        # Should be valid hex
        int(project_id, 16)


class TestPlatformCachePaths:
    """Test XDG cache directory resolution."""

    def test_xdg_cache_home_respected(self, tmp_path: Path, monkeypatch):
        custom_cache = tmp_path / "my_cache"
        monkeypatch.setenv("XDG_CACHE_HOME", str(custom_cache))

        locator = ResourceLocator().write_to_platform_cache("test_proj")
        result = locator.writable("data.db")

        assert str(custom_cache) in str(result)

    def test_search_platform_cache_uses_xdg(self, tmp_path: Path, monkeypatch):
        cache_dir = tmp_path / "cache" / "functualize" / "proj123"
        cache_dir.mkdir(parents=True)
        (cache_dir / "cached.json").write_text("{}")

        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

        locator = ResourceLocator().search_platform_cache("proj123")
        result = locator.resolve_one("cached.json")

        assert result is not None
        assert "cached.json" in result


class TestWhenEnv:
    """Test when_env() environment variable gating."""

    def test_source_skipped_when_env_not_set(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("MY_GATE_VAR", raising=False)
        (tmp_path / "gated.txt").write_text("hidden")

        locator = ResourceLocator().search_explicit(tmp_path).when_env("MY_GATE_VAR")
        result = locator.resolve_one("gated.txt")

        assert result is None

    def test_source_active_when_env_is_set(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("MY_GATE_VAR", "1")
        (tmp_path / "gated.txt").write_text("visible")

        locator = ResourceLocator().search_explicit(tmp_path).when_env("MY_GATE_VAR")
        result = locator.resolve_one("gated.txt")

        assert result is not None

    def test_when_env_only_gates_previous_source(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("MY_GATE_VAR", raising=False)
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        (dir_a / "from_a.txt").write_text("a")
        (dir_b / "from_b.txt").write_text("b")

        locator = (
            ResourceLocator()
            .search_explicit(dir_a)
            .when_env("MY_GATE_VAR")  # gates dir_a
            .search_explicit(dir_b)  # not gated
        )

        # dir_a is gated (env not set), so from_a.txt should not be found
        assert locator.resolve_one("from_a.txt") is None
        # dir_b is not gated, so from_b.txt should be found
        assert locator.resolve_one("from_b.txt") is not None
