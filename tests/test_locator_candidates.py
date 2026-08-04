"""Tests for ResourceLocator candidate-based resolution methods."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from functualize._primitives.locator import Candidate, ResourceLocator


def _write_toml(path: Path, content: str) -> None:
    """Helper to write TOML content to a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _extract_functualize_section(path: Path) -> dict[str, Any] | None:
    """Example extractor: returns [tool.functualize] from a pyproject.toml."""
    import tomllib

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        tool = data.get("tool", {})
        if isinstance(tool, dict):
            section = tool.get("functualize")
            if isinstance(section, dict):
                return section
    except Exception:
        pass
    return None


class TestResolveFirstCandidate:
    """Tests for resolve_first_candidate."""

    def test_finds_plain_toml_in_cwd(self, tmp_path: Path) -> None:
        _write_toml(tmp_path / ".functualize.toml", 'a = 1\nb = "hello"')

        locator = ResourceLocator().search_explicit(tmp_path)
        candidates: list[Candidate] = [".functualize.toml"]

        result = locator.resolve_first_candidate(candidates)
        assert result is not None
        directory, config = result
        assert directory == tmp_path
        assert config == {"a": 1, "b": "hello"}

    def test_finds_config_in_ancestor_via_upward_walk(self, tmp_path: Path) -> None:
        # Config at root
        _write_toml(tmp_path / ".functualize.toml", "scan_depth = 3")
        # Subdirectory with no config
        subdir = tmp_path / "sub" / "deep"
        subdir.mkdir(parents=True)

        locator = ResourceLocator().search_upward(start=subdir, stop=tmp_path.parent)
        candidates: list[Candidate] = [".functualize.toml"]

        result = locator.resolve_first_candidate(candidates)
        assert result is not None
        directory, config = result
        assert directory == tmp_path
        assert config == {"scan_depth": 3}

    def test_candidate_priority_within_directory(self, tmp_path: Path) -> None:
        """First candidate in list wins when multiple exist in same dir."""
        _write_toml(tmp_path / ".functualize.toml", "source = 'plain'")
        _write_toml(
            tmp_path / "pyproject.toml",
            '[tool.functualize]\nsource = "pyproject"',
        )

        locator = ResourceLocator().search_explicit(tmp_path)
        candidates: list[Candidate] = [
            ".functualize.toml",
            ("pyproject.toml", _extract_functualize_section),
        ]

        result = locator.resolve_first_candidate(candidates)
        assert result is not None
        _, config = result
        assert config["source"] == "plain"

    def test_falls_through_to_second_candidate(self, tmp_path: Path) -> None:
        """If first candidate doesn't exist, tries second."""
        _write_toml(
            tmp_path / "pyproject.toml",
            "[tool.functualize]\nfound = true",
        )

        locator = ResourceLocator().search_explicit(tmp_path)
        candidates: list[Candidate] = [
            ".functualize.toml",  # Doesn't exist
            ("pyproject.toml", _extract_functualize_section),
        ]

        result = locator.resolve_first_candidate(candidates)
        assert result is not None
        _, config = result
        assert config == {"found": True}

    def test_callback_returning_none_skips_candidate(self, tmp_path: Path) -> None:
        """Callback extractor returning None means candidate doesn't match."""
        # pyproject.toml without [tool.functualize] section
        _write_toml(tmp_path / "pyproject.toml", "[tool.other]\nx = 1")

        locator = ResourceLocator().search_explicit(tmp_path)
        candidates: list[Candidate] = [
            ("pyproject.toml", _extract_functualize_section),
        ]

        result = locator.resolve_first_candidate(candidates)
        assert result is None

    def test_returns_none_when_nothing_found(self, tmp_path: Path) -> None:
        locator = ResourceLocator().search_explicit(tmp_path)
        candidates: list[Candidate] = [".functualize.toml"]

        result = locator.resolve_first_candidate(candidates)
        assert result is None

    def test_invalid_toml_skipped(self, tmp_path: Path) -> None:
        """Malformed TOML files are skipped (not raised)."""
        (tmp_path / ".functualize.toml").write_text(
            "this is not valid [[[toml", encoding="utf-8"
        )

        locator = ResourceLocator().search_explicit(tmp_path)
        candidates: list[Candidate] = [".functualize.toml"]

        result = locator.resolve_first_candidate(candidates)
        assert result is None

    def test_convention_subdir_config(self, tmp_path: Path) -> None:
        """Config inside .functualize/ subdir is found."""
        conv_dir = tmp_path / ".functualize"
        conv_dir.mkdir()
        _write_toml(conv_dir / ".functualize.toml", "convention = true")

        locator = ResourceLocator().search_explicit(tmp_path)
        candidates: list[Candidate] = [
            ".functualize.toml",
            ".functualize/.functualize.toml",
        ]

        # First candidate doesn't exist at tmp_path directly, second does
        result = locator.resolve_first_candidate(candidates)
        assert result is not None
        _, config = result
        assert config == {"convention": True}


class TestResolveAllCandidates:
    """Tests for resolve_all_candidates."""

    def test_collects_from_multiple_directories(self, tmp_path: Path) -> None:
        """Finds config in multiple ancestor directories."""
        # Root config
        _write_toml(tmp_path / ".functualize.toml", "level = 'root'")
        # Intermediate config
        mid = tmp_path / "project"
        mid.mkdir()
        _write_toml(mid / ".functualize.toml", "level = 'project'")
        # Deep subdirectory (no config)
        deep = mid / "sub" / "work"
        deep.mkdir(parents=True)

        locator = ResourceLocator().search_upward(start=deep, stop=tmp_path.parent)
        candidates: list[Candidate] = [".functualize.toml"]

        results = locator.resolve_all_candidates(candidates)
        assert len(results) == 2
        # First result is nearest (project/)
        assert results[0][0] == mid
        assert results[0][1]["level"] == "project"
        # Second result is further (root)
        assert results[1][0] == tmp_path
        assert results[1][1]["level"] == "root"

    def test_one_result_per_directory(self, tmp_path: Path) -> None:
        """Even with multiple candidates matching, only first wins per dir."""
        _write_toml(tmp_path / ".functualize.toml", "source = 'plain'")
        _write_toml(
            tmp_path / "pyproject.toml",
            '[tool.functualize]\nsource = "pyproject"',
        )

        locator = ResourceLocator().search_explicit(tmp_path)
        candidates: list[Candidate] = [
            ".functualize.toml",
            ("pyproject.toml", _extract_functualize_section),
        ]

        results = locator.resolve_all_candidates(candidates)
        assert len(results) == 1
        assert results[0][1]["source"] == "plain"

    def test_empty_when_no_configs_exist(self, tmp_path: Path) -> None:
        subdir = tmp_path / "empty"
        subdir.mkdir()

        locator = ResourceLocator().search_upward(start=subdir, stop=tmp_path)
        candidates: list[Candidate] = [".functualize.toml"]

        results = locator.resolve_all_candidates(candidates)
        assert results == []

    def test_deduplicates_directories(self, tmp_path: Path) -> None:
        """Same directory reached via multiple sources is only counted once."""
        _write_toml(tmp_path / ".functualize.toml", "x = 1")

        locator = (
            ResourceLocator()
            .search_explicit(tmp_path)
            .search_upward(start=tmp_path, stop=tmp_path.parent)
        )
        candidates: list[Candidate] = [".functualize.toml"]

        results = locator.resolve_all_candidates(candidates)
        # Should only appear once even though two sources find it
        assert len(results) == 1


class TestParseToml:
    """Tests for ResourceLocator._parse_toml static method."""

    def test_valid_toml(self, tmp_path: Path) -> None:
        f = tmp_path / "test.toml"
        f.write_text('key = "value"\nnum = 42', encoding="utf-8")
        result = ResourceLocator._parse_toml(f)
        assert result == {"key": "value", "num": 42}

    def test_invalid_toml_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.toml"
        f.write_text("not valid [[[", encoding="utf-8")
        result = ResourceLocator._parse_toml(f)
        assert result is None

    def test_nonexistent_file_returns_none(self, tmp_path: Path) -> None:
        result = ResourceLocator._parse_toml(tmp_path / "missing.toml")
        assert result is None
