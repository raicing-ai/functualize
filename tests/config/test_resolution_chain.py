"""Unit tests for Resolution_Chain orchestrator."""

from __future__ import annotations

from typing import Any

import pytest

from functualize._config.chain import ResolutionChain, ResolvedValue
from functualize._config.errors import MissingKeyError

# --- Test helpers ---


class FakeSource:
    """A simple fake Source for testing the ResolutionChain."""

    def __init__(
        self,
        *,
        source_type: str = "test",
        source_id: str = "test-source",
        data: dict[tuple[str | None, str], Any] | None = None,
    ) -> None:
        self._source_type = source_type
        self._source_id = source_id
        self._data: dict[tuple[str | None, str], Any] = data or {}

    @property
    def source_type(self) -> str:
        return self._source_type

    @property
    def source_id(self) -> str:
        return self._source_id

    def get(self, key: str, section: str | None = None) -> Any | None:
        return self._data.get((section, key))

    def has(self, key: str, section: str | None = None) -> bool:
        return (section, key) in self._data


class DictSource:
    """A source backed by a nested dict with keys() support."""

    def __init__(
        self,
        *,
        source_type: str = "file",
        source_id: str = "file-source",
        data: dict[str, Any] | None = None,
    ) -> None:
        self._source_type = source_type
        self._source_id = source_id
        self._merged_config: dict[str, Any] = data or {}

    @property
    def source_type(self) -> str:
        return self._source_type

    @property
    def source_id(self) -> str:
        return self._source_id

    def get(self, key: str, section: str | None = None) -> Any | None:
        if section:
            section_data = self._merged_config.get(section)
            if isinstance(section_data, dict):
                return section_data.get(key)
            return None
        return self._merged_config.get(key)

    def has(self, key: str, section: str | None = None) -> bool:
        if section:
            section_data = self._merged_config.get(section)
            if isinstance(section_data, dict):
                return key in section_data
            return False
        return key in self._merged_config

    def keys(self, section: str) -> set[str]:
        section_data = self._merged_config.get(section)
        if isinstance(section_data, dict):
            return set(section_data.keys())
        return set()


# --- ResolvedValue tests ---


class TestResolvedValue:
    """Tests for ResolvedValue dataclass."""

    def test_creation_with_defaults(self) -> None:
        rv = ResolvedValue(
            value="hello",
            source_type="cli",
            source_id="cli",
            key="greeting",
        )
        assert rv.value == "hello"
        assert rv.source_type == "cli"
        assert rv.source_id == "cli"
        assert rv.key == "greeting"
        assert rv.alternatives == []

    def test_creation_with_alternatives(self) -> None:
        rv = ResolvedValue(
            value="hello",
            source_type="cli",
            source_id="cli",
            key="greeting",
            alternatives=[("env", "environ", "world"), ("file", "config.toml", "hi")],
        )
        assert len(rv.alternatives) == 2
        assert rv.alternatives[0] == ("env", "environ", "world")
        assert rv.alternatives[1] == ("file", "config.toml", "hi")

    def test_frozen(self) -> None:
        rv = ResolvedValue(value="x", source_type="cli", source_id="cli", key="k")
        with pytest.raises(AttributeError):
            rv.value = "y"  # type: ignore[misc]


# --- ResolutionChain.resolve tests ---


class TestResolutionChainResolve:
    """Tests for ResolutionChain.resolve method."""

    def test_resolve_single_source(self) -> None:
        source = FakeSource(
            source_type="cli",
            source_id="cli",
            data={(None, "port"): 8080},
        )
        chain = ResolutionChain([source])
        result = chain.resolve("port")

        assert result.value == 8080
        assert result.source_type == "cli"
        assert result.source_id == "cli"
        assert result.key == "port"
        assert result.alternatives == []

    def test_resolve_first_source_wins(self) -> None:
        high = FakeSource(
            source_type="cli",
            source_id="cli",
            data={(None, "port"): 9090},
        )
        low = FakeSource(
            source_type="file",
            source_id="config.toml",
            data={(None, "port"): 8080},
        )
        chain = ResolutionChain([high, low])
        result = chain.resolve("port")

        assert result.value == 9090
        assert result.source_type == "cli"
        assert result.alternatives == [("file", "config.toml", 8080)]

    def test_resolve_skips_none_values(self) -> None:
        empty = FakeSource(source_type="cli", source_id="cli", data={})
        provider = FakeSource(
            source_type="env",
            source_id="environ",
            data={(None, "debug"): "true"},
        )
        chain = ResolutionChain([empty, provider])
        result = chain.resolve("debug")

        assert result.value == "true"
        assert result.source_type == "env"

    def test_resolve_with_section(self) -> None:
        source = FakeSource(
            source_type="file",
            source_id="config.toml",
            data={("database", "host"): "localhost"},
        )
        chain = ResolutionChain([source])
        result = chain.resolve("host", section="database")

        assert result.value == "localhost"
        assert result.key == "host"

    def test_resolve_raises_missing_key_error(self) -> None:
        source1 = FakeSource(source_type="cli", source_id="cli", data={})
        source2 = FakeSource(source_type="env", source_id="environ", data={})
        chain = ResolutionChain([source1, source2])

        with pytest.raises(MissingKeyError) as exc_info:
            chain.resolve("missing_key")

        assert exc_info.value.key == "missing_key"
        assert "cli" in exc_info.value.consulted_sources
        assert "environ" in exc_info.value.consulted_sources

    def test_resolve_collects_all_alternatives(self) -> None:
        s1 = FakeSource(source_type="cli", source_id="cli", data={(None, "k"): "a"})
        s2 = FakeSource(source_type="env", source_id="environ", data={(None, "k"): "b"})
        s3 = FakeSource(source_type="file", source_id="f.toml", data={(None, "k"): "c"})
        chain = ResolutionChain([s1, s2, s3])
        result = chain.resolve("k")

        assert result.value == "a"
        assert result.alternatives == [
            ("env", "environ", "b"),
            ("file", "f.toml", "c"),
        ]

    def test_resolve_empty_chain_raises(self) -> None:
        chain = ResolutionChain([])
        with pytest.raises(MissingKeyError):
            chain.resolve("any_key")

    def test_resolve_records_correct_key(self) -> None:
        source = FakeSource(
            source_type="default",
            source_id="defaults",
            data={(None, "timeout"): 30},
        )
        chain = ResolutionChain([source])
        result = chain.resolve("timeout")
        assert result.key == "timeout"


# --- ResolutionChain.resolve_section tests ---


class TestResolutionChainResolveSection:
    """Tests for ResolutionChain.resolve_section method."""

    def test_resolve_section_gathers_all_keys(self) -> None:
        s1 = DictSource(
            source_type="cli",
            source_id="cli",
            data={"database": {"host": "cli-host"}},
        )
        s2 = DictSource(
            source_type="file",
            source_id="config.toml",
            data={"database": {"host": "file-host", "port": 5432}},
        )
        chain = ResolutionChain([s1, s2])
        results = chain.resolve_section("database")

        assert "host" in results
        assert "port" in results
        assert results["host"].value == "cli-host"
        assert results["host"].source_type == "cli"
        assert results["port"].value == 5432
        assert results["port"].source_type == "file"

    def test_resolve_section_returns_empty_for_unknown_section(self) -> None:
        source = DictSource(
            source_type="file",
            source_id="config.toml",
            data={"other": {"key": "val"}},
        )
        chain = ResolutionChain([source])
        results = chain.resolve_section("nonexistent")
        assert results == {}

    def test_resolve_section_returns_sorted_keys(self) -> None:
        source = DictSource(
            source_type="file",
            source_id="config.toml",
            data={"section": {"zebra": 1, "alpha": 2, "middle": 3}},
        )
        chain = ResolutionChain([source])
        results = chain.resolve_section("section")
        assert list(results.keys()) == ["alpha", "middle", "zebra"]

    def test_resolve_section_with_overlapping_sources(self) -> None:
        s1 = DictSource(
            source_type="env",
            source_id="environ",
            data={"app": {"debug": "true"}},
        )
        s2 = DictSource(
            source_type="file",
            source_id="config.toml",
            data={"app": {"debug": "false", "name": "myapp"}},
        )
        chain = ResolutionChain([s1, s2])
        results = chain.resolve_section("app")

        assert results["debug"].value == "true"
        assert results["debug"].source_type == "env"
        assert results["name"].value == "myapp"
        assert results["name"].source_type == "file"


# --- ResolutionChain.introspect tests ---


class TestResolutionChainIntrospect:
    """Tests for ResolutionChain.introspect method."""

    def test_introspect_gathers_all_alternatives(self) -> None:
        s1 = FakeSource(source_type="cli", source_id="cli", data={(None, "port"): 9090})
        s2 = FakeSource(
            source_type="env", source_id="environ", data={(None, "port"): "8080"}
        )
        s3 = FakeSource(
            source_type="file",
            source_id="config.toml",
            data={(None, "port"): 3000},
        )
        s4 = FakeSource(
            source_type="default",
            source_id="defaults",
            data={(None, "port"): 80},
        )
        chain = ResolutionChain([s1, s2, s3, s4])
        result = chain.introspect("port")

        assert result.value == 9090
        assert result.source_type == "cli"
        assert len(result.alternatives) == 3
        assert result.alternatives[0] == ("env", "environ", "8080")
        assert result.alternatives[1] == ("file", "config.toml", 3000)
        assert result.alternatives[2] == ("default", "defaults", 80)

    def test_introspect_raises_missing_key_error(self) -> None:
        source = FakeSource(source_type="cli", source_id="cli", data={})
        chain = ResolutionChain([source])

        with pytest.raises(MissingKeyError):
            chain.introspect("missing")

    def test_introspect_with_section(self) -> None:
        s1 = FakeSource(
            source_type="cli",
            source_id="cli",
            data={("db", "port"): 9090},
        )
        s2 = FakeSource(
            source_type="file",
            source_id="config.toml",
            data={("db", "port"): 5432},
        )
        chain = ResolutionChain([s1, s2])
        result = chain.introspect("port", section="db")

        assert result.value == 9090
        assert result.alternatives == [("file", "config.toml", 5432)]

    def test_introspect_single_source_no_alternatives(self) -> None:
        source = FakeSource(
            source_type="env",
            source_id="environ",
            data={(None, "key"): "value"},
        )
        chain = ResolutionChain([source])
        result = chain.introspect("key")

        assert result.value == "value"
        assert result.alternatives == []


# --- ResolutionChain.sources property ---


class TestResolutionChainSources:
    """Tests for ResolutionChain.sources property."""

    def test_sources_returns_copy(self) -> None:
        s1 = FakeSource(source_type="cli", source_id="cli")
        s2 = FakeSource(source_type="env", source_id="environ")
        chain = ResolutionChain([s1, s2])

        sources = chain.sources
        assert len(sources) == 2
        # Modifying returned list doesn't affect internal state
        sources.append(FakeSource(source_type="extra", source_id="extra"))  # type: ignore[arg-type]
        assert len(chain.sources) == 2

    def test_sources_preserves_order(self) -> None:
        s1 = FakeSource(source_type="cli", source_id="cli")
        s2 = FakeSource(source_type="env", source_id="environ")
        s3 = FakeSource(source_type="file", source_id="config.toml")
        chain = ResolutionChain([s1, s2, s3])

        sources = chain.sources
        assert sources[0].source_type == "cli"
        assert sources[1].source_type == "env"
        assert sources[2].source_type == "file"
