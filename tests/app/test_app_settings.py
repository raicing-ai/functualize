"""The public application settings seam uses one declared resolver snapshot."""

from __future__ import annotations

from pathlib import Path

from functualize._config import ResolutionChain
from functualize.app import ConfigSources, FunctualizeApp, JobSources, PluginSources
from functualize.plugin import (
    AppSettingsSchema,
    ResolvedSettings,
    Setting,
    SettingsSources,
    resolve_settings,
)


def _app(config_sources: ConfigSources) -> FunctualizeApp:
    return FunctualizeApp(
        "example",
        job_sources=JobSources(directories=[], functions=[], lazy=False),
        config_sources=config_sources,
        plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
    )


def test_public_symbols_resolve_the_same_declared_snapshot(tmp_path: Path) -> None:
    schema = AppSettingsSchema(
        settings=(Setting("cli.output", "str", "Output", default="rich"),),
        env_prefix="EXAMPLE_SETTINGS_TEST",
        sources=SettingsSources(
            project_file_names=(".example.toml",),
            global_file_name="example-test.toml",
        ),
        file_section_prefixes={},
    )
    (tmp_path / ".example.toml").write_text('[cli]\noutput = "json"\n')
    expected = resolve_settings(schema, tmp_path, env={}, global_dir=tmp_path / "none")
    assert expected.get("cli.output") == "json"

    sources = ConfigSources(
        config_resolution_chain=ResolutionChain([]), settings=schema, resolved=expected
    )
    app = _app(sources)
    assert app.settings is expected
    assert app.settings is app.settings


def test_app_resolves_its_declared_schema_on_first_access(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    schema = AppSettingsSchema(
        settings=(Setting("cli.output", "str", "Output", default="rich"),),
        env_prefix="EXAMPLE_SETTINGS_TEST",
        sources=SettingsSources(
            project_file_names=(".example.toml",),
            global_file_name="example-test.toml",
        ),
        file_section_prefixes={},
    )
    (tmp_path / ".example.toml").write_text('[cli]\noutput = "json"\n')
    app = _app(
        ConfigSources(config_resolution_chain=ResolutionChain([]), settings=schema)
    )

    assert app._settings_snapshot is None
    assert app.settings.get("cli.output") == "json"
    assert app.settings.provenance["cli.output"] == str(tmp_path / ".example.toml")
    assert app.settings is app.settings
