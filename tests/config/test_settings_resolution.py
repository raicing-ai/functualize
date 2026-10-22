from __future__ import annotations

from pathlib import Path

from functualize._config.settings_resolution import resolve_settings
from functualize._config.sources import EnvSource
from functualize._types.functualize_settings import FUNCTUALIZE_SETTINGS


def test_pinned_precedence_matrix_and_f3a(tmp_path: Path) -> None:
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "config.toml").write_text('[cli]\noutput = "plain"\n')
    project = tmp_path / "project"
    project.mkdir()

    def output(cwd: Path, **kwargs: object) -> str:
        return resolve_settings(
            FUNCTUALIZE_SETTINGS, cwd, global_dir=global_dir, **kwargs
        ).get("cli.output")

    assert output(project) == "plain"  # global only
    (project / ".functualize.toml").write_text('[cli]\noutput = "json"\n')
    assert output(project) == "json"  # single directory
    nested = project / "nested"
    nested.mkdir()
    (nested / ".functualize.toml").write_text("[cli]\nshow_timing = true\n")
    assert output(nested) == "json"  # parent project
    (nested / ".functualize.toml").write_text(
        "root = true\n[cli]\nshow_timing = true\n"
    )
    assert output(nested) == "plain"  # root stops parent
    assert (
        resolve_settings(FUNCTUALIZE_SETTINGS, nested, global_dir=global_dir).get(
            "cli.show_timing"
        )
        is True
    )
    assert output(nested, env={"FUNCTUALIZE_CLI_OUTPUT": "json"}) == "json"
    assert (
        output(
            nested,
            env={"FUNCTUALIZE_CLI_OUTPUT": "json"},
            flags={"output": "rich"},
        )
        == "rich"
    )

    # F3a: the old store crossed the root marker and returned the parent.
    (project / ".functualize.toml").write_text('[cli]\noutput = "rich"\n')
    (global_dir / "config.toml").write_text('[cli]\noutput = "json"\n')
    assert output(nested) == "json"
    (nested / ".functualize.toml").write_text('[cli]\noutput = "rich"\n')
    assert output(nested) == "rich"


def test_only_canonical_extra_directories_env_name(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".functualize.toml").write_text(
        'extra_directories = ["legacy-file"]\n'
        '[discovery]\nextra_directories = ["canonical-file"]\n'
    )
    resolved = resolve_settings(
        FUNCTUALIZE_SETTINGS,
        project,
        global_dir=tmp_path / "global",
        env={
            "FUNCTUALIZE_EXTRA_DIRECTORIES": "legacy-env",
            "FUNCTUALIZE_DISCOVERY_EXTRA_DIRECTORIES": "canonical-env",
        },
    )
    assert resolved.get("discovery.extra_directories") == (
        "canonical-env",
        "canonical-file",
    )
    assert resolved.provenance["discovery.extra_directories"] == "env"
    without_canonical = resolve_settings(
        FUNCTUALIZE_SETTINGS,
        project,
        global_dir=tmp_path / "global",
        env={"FUNCTUALIZE_EXTRA_DIRECTORIES": "legacy-env"},
    )
    assert without_canonical.get("discovery.extra_directories") == ("canonical-file",)


def test_lists_deduplicate_first_occurrence_and_record_contributors(
    tmp_path: Path,
) -> None:
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "config.toml").write_text('import_libs = ["same", "global"]\n')
    project = tmp_path / "project"
    project.mkdir()
    project_path = project / ".functualize.toml"
    project_path.write_text('import_libs = ["project", "same"]\n')
    resolved = resolve_settings(
        FUNCTUALIZE_SETTINGS,
        project,
        global_dir=global_dir,
        flags={"import_libs": ["flag", "same"]},
        env={},
    )
    assert resolved.get("import_libs") == ("flag", "same", "project", "global")
    assert resolved.contributes[project_path] == frozenset({"import_libs"})
    assert resolved.contributes[global_dir / "config.toml"] == frozenset(
        {"import_libs"}
    )


def test_env_source_prefix_is_opt_in() -> None:
    environ = {
        "SHELL_PROGRAM": "/legacy",
        "FUNCTUALIZE_SHELL_PROGRAM": "/catalog",
    }
    assert EnvSource(environ).get("program", "shell") == "/legacy"
    source = EnvSource(environ, prefix="FUNCTUALIZE")
    assert source.get("program", "shell") == "/catalog"
    assert source.has("program", "shell")
    assert source.keys("shell") == {"program"}
