"""Unit tests for Source implementations."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from functualize._config.errors import (
    AnnotationResolutionError,
)
from functualize._config.manifest import SourceAnnotation
from functualize._config.registry import ProviderRegistry
from functualize._config.sources import (
    CliSource,
    DefaultSource,
    EnvSource,
    FileSource,
    RemoteSource,
)
from functualize._primitives.locator import ResourceLocator
from functualize._types.enums import ConfigFileRole

# --- Test helpers ---


class FakeTomlProvider:
    """A fake format provider for testing FileSource."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self._data = data or {}

    def extensions(self) -> list[str]:
        return [".toml"]

    def parse(self, path: str) -> dict[str, Any]:
        return dict(self._data)

    def serialize(self, data: dict[str, Any]) -> str:
        return ""


class FakeRemoteProvider:
    """A fake remote provider for testing RemoteSource."""

    def __init__(
        self,
        *,
        identifier: str = "vault",
        ready: bool = True,
        values: dict[str, str] | None = None,
        delay: float = 0.0,
    ) -> None:
        self._identifier = identifier
        self._ready = ready
        self._values = values or {}
        self._delay = delay

    def identifier(self) -> str:
        return self._identifier

    def is_ready(self) -> bool:
        return self._ready

    def fetch(self, reference: str) -> str:
        if self._delay > 0:
            time.sleep(self._delay)
        if reference not in self._values:
            msg = f"Key not found: {reference}"
            raise KeyError(msg)
        return self._values[reference]


# --- CliSource tests ---


class TestCliSource:
    """Tests for CliSource."""

    def test_source_type_and_id(self) -> None:
        source = CliSource({})
        assert source.source_type == "cli"
        assert source.source_id == "cli"

    def test_get_simple_key(self) -> None:
        source = CliSource({"my_option": "value1"})
        assert source.get("my_option") == "value1"

    def test_get_hyphenated_key_converted(self) -> None:
        source = CliSource({"my-option": "value1"})
        assert source.get("my_option") == "value1"

    def test_get_with_leading_dashes_stripped(self) -> None:
        source = CliSource({"--my-option": "value1"})
        assert source.get("my_option") == "value1"

    def test_get_dot_namespaced_key(self) -> None:
        source = CliSource({"database.port": "5432"})
        assert source.get("port", section="database") == "5432"

    def test_get_dot_namespaced_with_hyphens(self) -> None:
        source = CliSource({"--my-group.my-key": "hello"})
        assert source.get("my_key", section="my_group") == "hello"

    def test_get_returns_none_for_missing_key(self) -> None:
        source = CliSource({"existing": "val"})
        assert source.get("nonexistent") is None

    def test_get_returns_none_for_wrong_section(self) -> None:
        source = CliSource({"database.port": "5432"})
        assert source.get("port", section="server") is None

    def test_has_returns_true_for_present_key(self) -> None:
        source = CliSource({"debug": True})
        assert source.has("debug") is True

    def test_has_returns_false_for_missing_key(self) -> None:
        source = CliSource({"debug": True})
        assert source.has("verbose") is False

    def test_has_with_section(self) -> None:
        source = CliSource({"db.host": "localhost"})
        assert source.has("host", section="db") is True
        assert source.has("host", section="other") is False

    def test_only_explicit_values_exposed(self) -> None:
        """Only values in the constructor dict are exposed."""
        source = CliSource({"port": 8080})
        assert source.get("port") == 8080
        assert source.get("host") is None

    def test_get_no_section_returns_none_for_sectioned_key(self) -> None:
        """A key stored with a section isn't returned when no section is given."""
        source = CliSource({"group.key": "val"})
        assert source.get("key") is None
        assert source.get("key", section="group") == "val"


# --- EnvSource tests ---


class TestEnvSource:
    """Tests for EnvSource."""

    def test_source_type_and_id(self) -> None:
        source = EnvSource(environ={})
        assert source.source_type == "env"
        assert source.source_id == "environ"

    def test_get_simple_key(self) -> None:
        source = EnvSource(environ={"DEBUG": "true"})
        assert source.get("debug") == "true"

    def test_get_with_section(self) -> None:
        source = EnvSource(environ={"DATABASE_PORT": "5432"})
        assert source.get("port", section="database") == "5432"

    def test_get_uppercased(self) -> None:
        source = EnvSource(environ={"MY_APP_SECRET": "s3cret"})
        assert source.get("secret", section="my_app") == "s3cret"

    def test_get_returns_none_for_missing(self) -> None:
        source = EnvSource(environ={})
        assert source.get("missing") is None

    def test_has_returns_true_for_existing(self) -> None:
        source = EnvSource(environ={"HOST": "localhost"})
        assert source.has("host") is True

    def test_has_returns_false_for_missing(self) -> None:
        source = EnvSource(environ={"HOST": "localhost"})
        assert source.has("port") is False

    def test_has_with_section(self) -> None:
        source = EnvSource(environ={"DB_HOST": "localhost"})
        assert source.has("host", section="db") is True
        assert source.has("host", section="cache") is False

    def test_reads_real_os_environ_when_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FUNCTUALIZE_TEST_VAR", "works")
        source = EnvSource()
        assert source.get("test_var", section="functualize") == "works"


# --- RemoteSource tests ---


class TestRemoteSource:
    """Tests for RemoteSource."""

    def test_source_type_and_id(self) -> None:
        registry = ProviderRegistry()
        source = RemoteSource(registry, {}, source_id="vault")
        assert source.source_type == "remote"
        assert source.source_id == "vault"

    def test_get_returns_none_for_unannotated_key(self) -> None:
        registry = ProviderRegistry()
        source = RemoteSource(registry, {})
        assert source.get("unannotated_key") is None

    def test_has_returns_false_for_unannotated_key(self) -> None:
        registry = ProviderRegistry()
        source = RemoteSource(registry, {})
        assert source.has("unannotated_key") is False

    def test_resolves_annotation_from_provider(self) -> None:
        registry = ProviderRegistry()
        provider = FakeRemoteProvider(
            identifier="vault", values={"secrets/db_pass": "s3cret"}
        )
        registry.register_remote_provider(provider)

        annotations = {
            "db_pass": [SourceAnnotation(provider="vault", reference="secrets/db_pass")]
        }
        source = RemoteSource(registry, annotations)

        assert source.get("db_pass") == "s3cret"

    def test_resolves_with_section(self) -> None:
        registry = ProviderRegistry()
        provider = FakeRemoteProvider(
            identifier="vault", values={"secrets/port": "5432"}
        )
        registry.register_remote_provider(provider)

        annotations = {
            "database.port": [
                SourceAnnotation(provider="vault", reference="secrets/port")
            ]
        }
        source = RemoteSource(registry, annotations)

        assert source.get("port", section="database") == "5432"

    def test_caches_resolved_values(self) -> None:
        registry = ProviderRegistry()
        provider = FakeRemoteProvider(identifier="vault", values={"ref": "value"})
        registry.register_remote_provider(provider)

        annotations = {"key": [SourceAnnotation(provider="vault", reference="ref")]}
        source = RemoteSource(registry, annotations)

        # First call resolves
        assert source.get("key") == "value"
        # Second call uses cache (provider could be removed without effect)
        assert source.get("key") == "value"

    def test_fallback_chain_tries_next_on_failure(self) -> None:
        registry = ProviderRegistry()
        failing = FakeRemoteProvider(identifier="vault", values={})
        working = FakeRemoteProvider(
            identifier="aws-sm", values={"prod/pass": "aws-secret"}
        )
        registry.register_remote_provider(failing)
        registry.register_remote_provider(working)

        annotations = {
            "password": [
                SourceAnnotation(provider="vault", reference="missing"),
                SourceAnnotation(provider="aws-sm", reference="prod/pass"),
            ]
        }
        source = RemoteSource(registry, annotations)

        assert source.get("password") == "aws-secret"

    def test_raises_annotation_resolution_error_when_all_fail(self) -> None:
        registry = ProviderRegistry()
        provider = FakeRemoteProvider(identifier="vault", values={})
        registry.register_remote_provider(provider)

        annotations = {
            "secret": [SourceAnnotation(provider="vault", reference="missing")]
        }
        source = RemoteSource(registry, annotations)

        with pytest.raises(AnnotationResolutionError) as exc_info:
            source.get("secret")

        assert exc_info.value.key == "secret"
        assert len(exc_info.value.failures) == 1

    def test_raises_when_provider_not_registered(self) -> None:
        registry = ProviderRegistry()
        annotations = {
            "key": [SourceAnnotation(provider="nonexistent", reference="ref")]
        }
        source = RemoteSource(registry, annotations)

        with pytest.raises(AnnotationResolutionError) as exc_info:
            source.get("key")

        assert exc_info.value.failures[0].error_type == "not_registered"

    def test_reports_not_ready_provider(self) -> None:
        registry = ProviderRegistry()
        provider = FakeRemoteProvider(identifier="vault", ready=False)
        registry.register_remote_provider(provider)

        annotations = {"key": [SourceAnnotation(provider="vault", reference="ref")]}
        source = RemoteSource(registry, annotations)

        with pytest.raises(AnnotationResolutionError) as exc_info:
            source.get("key")

        assert exc_info.value.failures[0].error_type == "not_ready"

    def test_has_returns_true_for_annotated_key(self) -> None:
        registry = ProviderRegistry()
        annotations = {"key": [SourceAnnotation(provider="vault", reference="ref")]}
        source = RemoteSource(registry, annotations)
        assert source.has("key") is True


# --- FileSource tests ---


class TestFileSource:
    """Tests for FileSource."""

    def test_source_type(self) -> None:
        resolver = ResourceLocator()
        registry = ProviderRegistry()
        source = FileSource(resolver, registry)
        assert source.source_type == "file"

    def test_source_id_empty_when_no_files(self) -> None:
        resolver = ResourceLocator()
        registry = ProviderRegistry()
        source = FileSource(resolver, registry)
        assert source.source_id == ""

    def test_discovers_and_parses_files(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text('[database]\nhost = "localhost"\nport = 5432\n')

        # Create a provider that returns the expected data
        class RealishTomlProvider:
            def extensions(self) -> list[str]:
                return [".toml"]

            def parse(self, path: str) -> dict[str, Any]:
                return {"database": {"host": "localhost", "port": 5432}}

            def serialize(self, data: dict[str, Any]) -> str:
                return ""

        registry = ProviderRegistry()
        registry.register_format_provider(RealishTomlProvider())

        resolver = ResourceLocator().search_explicit(str(tmp_path))
        source = FileSource(resolver, registry, pattern="config.*")

        assert source.get("host", section="database") == "localhost"
        assert source.get("port", section="database") == 5432

    def test_source_id_shows_discovered_paths(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text("")

        provider = FakeTomlProvider(data={"key": "val"})
        registry = ProviderRegistry()
        registry.register_format_provider(provider)

        resolver = ResourceLocator().search_explicit(str(tmp_path))
        source = FileSource(resolver, registry, pattern="config.*")

        assert str(config_file) in source.source_id

    def test_deep_merges_multiple_files(self, tmp_path: Path) -> None:
        """Higher-priority file values override lower-priority ones."""
        # Create two directories with config files
        high_priority = tmp_path / "high"
        high_priority.mkdir()
        (high_priority / "config.toml").write_text("")

        low_priority = tmp_path / "low"
        low_priority.mkdir()
        (low_priority / "config.toml").write_text("")

        call_count = 0

        class OrderedTomlProvider:
            def extensions(self) -> list[str]:
                return [".toml"]

            def parse(self, path: str) -> dict[str, Any]:
                nonlocal call_count
                call_count += 1
                if "high" in path:
                    return {"shared": "high-val", "only_high": "yes"}
                return {"shared": "low-val", "only_low": "yes"}

            def serialize(self, data: dict[str, Any]) -> str:
                return ""

        registry = ProviderRegistry()
        registry.register_format_provider(OrderedTomlProvider())

        # High priority first, low priority second
        resolver = (
            ResourceLocator()
            .search_explicit(str(high_priority))
            .search_explicit(str(low_priority))
        )
        source = FileSource(resolver, registry, pattern="config.*")

        # High-priority file's value wins for shared key
        assert source.get("shared") == "high-val"
        # Both unique keys are present
        assert source.get("only_high") == "yes"
        assert source.get("only_low") == "yes"

    def test_per_file_values_empty_when_no_files(self) -> None:
        resolver = ResourceLocator()
        registry = ProviderRegistry()
        source = FileSource(resolver, registry)
        assert source.per_file_values == []

    def test_per_file_values_keeps_each_file_unmerged(self, tmp_path: Path) -> None:
        """Per-file view attributes values to their originating file.

        The merged view can only say "shared == high-val"; this says *which*
        file said so, and that the losing file still said "low-val".
        """
        high_priority = tmp_path / "high"
        high_priority.mkdir()
        (high_priority / "config.toml").write_text("")

        low_priority = tmp_path / "low"
        low_priority.mkdir()
        (low_priority / "config.toml").write_text("")

        class OrderedTomlProvider:
            def extensions(self) -> list[str]:
                return [".toml"]

            def parse(self, path: str) -> dict[str, Any]:
                if "high" in path:
                    return {"shared": "high-val", "only_high": "yes"}
                return {"shared": "low-val", "only_low": "yes"}

            def serialize(self, data: dict[str, Any]) -> str:
                return ""

        registry = ProviderRegistry()
        registry.register_format_provider(OrderedTomlProvider())

        resolver = (
            ResourceLocator()
            .search_explicit(str(high_priority))
            .search_explicit(str(low_priority))
        )
        source = FileSource(resolver, registry, pattern="config.*")

        per_file = source.per_file_values
        assert len(per_file) == 2

        # Discovery order is precedence order: highest priority first.
        high_path, high_config = per_file[0]
        low_path, low_config = per_file[1]
        assert "high" in high_path
        assert "low" in low_path

        # Each file keeps its own value for the shared key — unmerged.
        assert high_config["shared"] == "high-val"
        assert low_config["shared"] == "low-val"
        assert "only_low" not in high_config
        assert "only_high" not in low_config

        # Merge semantics are unchanged by the retention.
        assert source.get("shared") == "high-val"

    def test_per_file_values_skips_files_without_a_provider(
        self, tmp_path: Path
    ) -> None:
        """Unparseable files are absent, so the list is not path-index-aligned."""
        (tmp_path / "config.toml").write_text("")
        (tmp_path / "config.xyz").write_text("")

        provider = FakeTomlProvider(data={"key": "val"})
        registry = ProviderRegistry()
        registry.register_format_provider(provider)

        resolver = ResourceLocator().search_explicit(str(tmp_path))
        source = FileSource(resolver, registry, pattern="config.*")

        per_file = source.per_file_values
        assert [Path(p).suffix for p, _ in per_file] == [".toml"]
        # The .xyz file was still discovered — the two lists differ in length.
        assert len(source._discovered_paths) > len(per_file)

    def test_get_returns_none_for_missing_key(self, tmp_path: Path) -> None:
        (tmp_path / "config.toml").write_text("")
        provider = FakeTomlProvider(data={"existing": "val"})
        registry = ProviderRegistry()
        registry.register_format_provider(provider)

        resolver = ResourceLocator().search_explicit(str(tmp_path))
        source = FileSource(resolver, registry, pattern="config.*")

        assert source.get("missing") is None

    def test_has_returns_correct_values(self, tmp_path: Path) -> None:
        (tmp_path / "config.toml").write_text("")
        provider = FakeTomlProvider(data={"key": "val", "section": {"nested": True}})
        registry = ProviderRegistry()
        registry.register_format_provider(provider)

        resolver = ResourceLocator().search_explicit(str(tmp_path))
        source = FileSource(resolver, registry, pattern="config.*")

        assert source.has("key") is True
        assert source.has("missing") is False
        assert source.has("nested", section="section") is True
        assert source.has("nested", section="other") is False

    def test_no_files_returns_none(self) -> None:
        """When no config files are found, get always returns None."""
        resolver = ResourceLocator()  # No rules, no files found
        registry = ProviderRegistry()
        source = FileSource(resolver, registry)

        assert source.get("anything") is None
        assert source.has("anything") is False

    def test_filename_regex_matches_custom_pattern(self, tmp_path: Path) -> None:
        """filename_regex discovers files the default glob would miss."""
        (tmp_path / "settings.base.toml").write_text("")
        (tmp_path / "config.toml").write_text("")
        (tmp_path / "notes.txt").write_text("")
        provider = FakeTomlProvider(data={"app": {"name": "custom"}})
        registry = ProviderRegistry()
        registry.register_format_provider(provider)

        resolver = ResourceLocator().search_explicit(str(tmp_path))
        source = FileSource(
            resolver,
            registry,
            filename_regex=r"^settings\.(\w+)\.toml$",
        )

        assert source.get("name", section="app") == "custom"
        assert len(source._discovered_paths) == 1
        assert source._discovered_paths[0].endswith("settings.base.toml")

    def test_filename_regex_no_match_yields_empty(self, tmp_path: Path) -> None:
        """filename_regex with no matching files discovers nothing."""
        (tmp_path / "config.toml").write_text("")
        provider = FakeTomlProvider(data={"key": "val"})
        registry = ProviderRegistry()
        registry.register_format_provider(provider)

        resolver = ResourceLocator().search_explicit(str(tmp_path))
        source = FileSource(
            resolver,
            registry,
            filename_regex=r"^settings\.(\w+)\.ini$",
        )

        assert source._discovered_paths == []
        assert source.get("key") is None

    def test_default_glob_unchanged_without_regex(self, tmp_path: Path) -> None:
        """Without filename_regex, the config.* glob path is unchanged."""
        (tmp_path / "settings.base.toml").write_text("")
        (tmp_path / "config.toml").write_text("")
        provider = FakeTomlProvider(data={"key": "val"})
        registry = ProviderRegistry()
        registry.register_format_provider(provider)

        resolver = ResourceLocator().search_explicit(str(tmp_path))
        source = FileSource(resolver, registry, pattern="config.*")

        assert len(source._discovered_paths) == 1
        assert source._discovered_paths[0].endswith("config.toml")


# --- DefaultSource tests ---


class TestDefaultSource:
    """Tests for DefaultSource."""

    def test_source_type_and_id(self) -> None:
        source = DefaultSource({})
        assert source.source_type == "default"
        assert source.source_id == "defaults"

    def test_get_simple_default(self) -> None:
        source = DefaultSource({"timeout": 30, "debug": False})
        assert source.get("timeout") == 30
        assert source.get("debug") is False

    def test_get_sectioned_default(self) -> None:
        source = DefaultSource({"database": {"port": 5432, "host": "localhost"}})
        assert source.get("port", section="database") == 5432
        assert source.get("host", section="database") == "localhost"

    def test_get_returns_none_for_missing(self) -> None:
        source = DefaultSource({"key": "val"})
        assert source.get("missing") is None

    def test_get_returns_none_for_wrong_section(self) -> None:
        source = DefaultSource({"db": {"port": 5432}})
        assert source.get("port", section="cache") is None

    def test_has_returns_true_for_existing(self) -> None:
        source = DefaultSource({"key": "val"})
        assert source.has("key") is True

    def test_has_returns_false_for_missing(self) -> None:
        source = DefaultSource({"key": "val"})
        assert source.has("other") is False

    def test_has_with_section(self) -> None:
        source = DefaultSource({"db": {"host": "localhost"}})
        assert source.has("host", section="db") is True
        assert source.has("host", section="cache") is False

    def test_section_not_a_dict_returns_none(self) -> None:
        """If the section key exists but isn't a dict, return None."""
        source = DefaultSource({"section": "not_a_dict"})
        assert source.get("key", section="section") is None
        assert source.has("key", section="section") is False


class _PerPathProvider:
    """A format provider returning different data per file path."""

    def __init__(self, by_name: dict[str, dict[str, Any]]) -> None:
        self._by_name = by_name

    def extensions(self) -> list[str]:
        return [".toml"]

    def parse(self, path: str) -> dict[str, Any]:
        return dict(self._by_name.get(Path(path).name, {}))

    def serialize(self, data: dict[str, Any]) -> str:
        return ""


class TestFileSourceEnvironmentBands:
    """FileSource(environment=...) — base/overlay banding."""

    @staticmethod
    def _source(directory: Path, environment: str | None) -> FileSource:
        registry = ProviderRegistry()
        registry.register_format_provider(
            _PerPathProvider(
                {
                    "config.base.toml": {"who": "base", "only_base": 1},
                    "config.dev.toml": {"who": "dev"},
                    "config.prod.toml": {"who": "prod"},
                }
            )
        )
        resolver = ResourceLocator().search_explicit(str(directory))
        return FileSource(
            resolver, registry, pattern="config.*", environment=environment
        )

    @staticmethod
    def _write(directory: Path, *names: str) -> None:
        for name in names:
            (directory / name).write_text("")

    def test_overlay_beats_base(self, tmp_path: Path) -> None:
        self._write(tmp_path, "config.base.toml", "config.dev.toml")

        source = self._source(tmp_path, "dev")

        assert source.get("who") == "dev"
        # Base keys the overlay doesn't define still come through.
        assert source.get("only_base") == 1

    def test_lexicographic_order_no_longer_decides(self, tmp_path: Path) -> None:
        """`base` sorts first; that must not make it win.

        This is the exact defect: sorted() yielded [base, dev, prod] and the
        merge walked it reversed, so config.base.* beat every overlay.
        """
        self._write(tmp_path, "config.base.toml", "config.dev.toml")

        assert self._source(tmp_path, "dev").get("who") == "dev"

    def test_inactive_environment_file_is_not_merged(self, tmp_path: Path) -> None:
        self._write(tmp_path, "config.base.toml", "config.prod.toml")

        source = self._source(tmp_path, "dev")

        assert source.get("who") == "base"

    def test_only_the_active_overlay_merges(self, tmp_path: Path) -> None:
        self._write(tmp_path, "config.base.toml", "config.dev.toml", "config.prod.toml")

        assert self._source(tmp_path, "prod").get("who") == "prod"
        assert self._source(tmp_path, "dev").get("who") == "dev"

    def test_no_environment_preserves_discovery_order(self, tmp_path: Path) -> None:
        """environment=None must behave exactly as before this feature."""
        self._write(tmp_path, "config.base.toml", "config.dev.toml")

        # Earlier-discovered (lexicographically first) wins when unbanded.
        assert self._source(tmp_path, None).get("who") == "base"

    def test_file_infos_report_roles_and_ranks(self, tmp_path: Path) -> None:
        self._write(tmp_path, "config.base.toml", "config.dev.toml", "config.prod.toml")

        infos = {Path(i.path).name: i for i in self._source(tmp_path, "dev").file_infos}

        assert infos["config.base.toml"].role is ConfigFileRole.BASE
        assert infos["config.dev.toml"].role is ConfigFileRole.OVERLAY
        assert infos["config.prod.toml"].role is ConfigFileRole.INERT
        assert infos["config.dev.toml"].environment_slot == "dev"
        # The winner ranks first; the inert file has no rank at all.
        assert infos["config.dev.toml"].precedence == 0
        assert infos["config.base.toml"].precedence == 1
        assert infos["config.prod.toml"].precedence is None

    def test_unparsed_files_are_reported_not_dropped(self, tmp_path: Path) -> None:
        """A file with no matching provider is still reported."""
        self._write(tmp_path, "config.base.toml")
        (tmp_path / "config.dev.yaml").write_text("")

        infos = {Path(i.path).name: i for i in self._source(tmp_path, "dev").file_infos}

        assert infos["config.dev.yaml"].parsed is False
        assert infos["config.dev.yaml"].is_active is False
        assert infos["config.base.toml"].parsed is True


class TestFileSourceDirectoryMajorPrecedence:
    """Nearest directory wins overall; within a directory, overlay beats base.

    This preserves the documented project > parents > global ladder: whose
    config it is outranks which environment it names.
    """

    @staticmethod
    def _source(project: Path, parent: Path, environment: str) -> FileSource:
        registry = ProviderRegistry()
        registry.register_format_provider(
            _PerPathProvider(
                {
                    "config.base.toml": {"who": "base"},
                    "config.dev.toml": {"who": "dev"},
                }
            )
        )
        # search_explicit(project) first, then the parent — the priority
        # order ResourceLocator produces for a project/parent ladder.
        resolver = (
            ResourceLocator().search_explicit(str(project)).search_explicit(str(parent))
        )
        return FileSource(
            resolver, registry, pattern="config.*", environment=environment
        )

    def test_project_base_beats_parent_overlay(self, tmp_path: Path) -> None:
        parent = tmp_path / "parent"
        project = parent / "project"
        project.mkdir(parents=True)

        (parent / "config.dev.toml").write_text("")
        (project / "config.base.toml").write_text("")

        source = self._source(project, parent, "dev")

        # The nearer directory wins even though the far file is an overlay.
        assert source.get("who") == "base"

    def test_within_one_directory_overlay_still_beats_base(
        self, tmp_path: Path
    ) -> None:
        parent = tmp_path / "parent"
        project = parent / "project"
        project.mkdir(parents=True)

        (project / "config.base.toml").write_text("")
        (project / "config.dev.toml").write_text("")

        source = self._source(project, parent, "dev")

        assert source.get("who") == "dev"
