"""Tests for the deploy_tool example.

The job bodies are trivial; what is worth asserting is the part the example
exists to demonstrate — that this app has a settings identity of its own, that
its two flags are generated from declarations rather than hand-written, and
that the early one is in the app's *first* snapshot. Everything here goes
through public API, as the example itself does.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from functualize.app.adapters import early_setting_flags
from functualize.app.adapters.settings_flags import (
    generated_setting_options,
    passed_setting_flags,
)
from functualize.plugin import FUNCTUALIZE_SETTINGS, resolve_settings

_ROOT = Path(__file__).parent.parent


def _load(name: str, relpath: str):
    """Load a module from a file path under the example directory."""
    spec = importlib.util.spec_from_file_location(name, _ROOT / relpath)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_deploy = _load("dt_deploy", "jobs/deploy.py")
_status = _load("dt_status", "jobs/status.py")
_main = _load("dt_main", "deploy_tool/main.py")


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty project with no global file and no settings in the environment."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    for name in list(os.environ):
        if name.startswith(("DEPLOY_TOOL_", "FUNCTUALIZE_")):
            monkeypatch.delenv(name)
    project = tmp_path / "project"
    project.mkdir()
    return project


class TestJobs:
    def test_web_reports_its_target(self) -> None:
        assert _deploy.web(environment="prod") == "Deploying web to prod"

    def test_web_dry_run_does_not_claim_to_deploy(self) -> None:
        assert _deploy.web(dry_run=True).startswith("Would deploy")

    def test_api_reports_replicas(self) -> None:
        assert "2 replica(s)" in _deploy.api()

    def test_jobs_are_grouped(self) -> None:
        """`deploy.web` / `deploy.api` — the nested group the shell drills into."""
        assert _deploy.JOB_GROUP == "deploy"

    def test_status_is_top_level(self) -> None:
        assert not hasattr(_status, "JOB_GROUP")


class TestDeclaration:
    def test_the_app_declares_its_two_settings(self) -> None:
        schema = _main.settings_schema()
        assert schema.setting("deploy.environment") is not None
        assert schema.setting("deploy.config_profile") is not None

    def test_it_keeps_every_built_in_setting(self) -> None:
        """`extend`, not a two-setting tuple: the base catalog is not dropped."""
        names = [setting.name for setting in _main.settings_schema().settings]
        base = [setting.name for setting in FUNCTUALIZE_SETTINGS.settings]
        assert names == [*base, "deploy.environment", "deploy.config_profile"]

    def test_importing_the_example_registers_nothing(self) -> None:
        """The declaration is data; the base catalog is not mutated by import."""
        assert FUNCTUALIZE_SETTINGS.setting("deploy.environment") is None
        assert FUNCTUALIZE_SETTINGS.setting("deploy.config_profile") is None

    def test_redeclaring_a_built_in_name_is_refused(self) -> None:
        clash = FUNCTUALIZE_SETTINGS.settings[0]
        with pytest.raises(ValueError, match="already declared"):
            FUNCTUALIZE_SETTINGS.extend(*_main.DEPLOY_SETTINGS, clash)

    def test_the_app_resolves_the_declaration_it_was_given(
        self, isolated: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(_ROOT)
        app = _main.build_app()
        assert app.settings_schema.setting("deploy.environment") is not None
        assert app.settings.get("deploy.environment") == "dev"


class TestSettingsIdentity:
    def test_the_app_has_its_own_name(self) -> None:
        assert _main.APP_NAME == "deploy-tool"

    def test_it_reads_its_own_env_prefix_not_funcs(self, isolated: Path) -> None:
        """The point of C2.2: two apps, one machine, no bleed.

        The env prefix comes from the app's own `AppSettingsSchema`, which is
        why the example declares one.
        """
        resolved = resolve_settings(
            _main.settings_schema(),
            isolated,
            env={
                "FUNCTUALIZE_DEPLOY_ENVIRONMENT": "func-said-so",
                "DEPLOY_TOOL_DEPLOY_ENVIRONMENT": "prod",
            },
        )
        assert resolved.get("deploy.environment") == "prod"

    def test_it_nests_under_its_own_pyproject_table(self, isolated: Path) -> None:
        """`[tool.deploy-tool]`, not `[tool.functualize]`."""
        schema = _main.settings_schema()
        assert schema.section_prefix_for("pyproject.toml") == "tool.deploy-tool"
        (isolated / "pyproject.toml").write_text(
            '[tool.functualize.deploy]\nenvironment = "prod"\n'
            '[tool.deploy-tool.deploy]\nenvironment = "staging"\n'
        )
        resolved = resolve_settings(schema, isolated, env={})
        assert resolved.get("deploy.environment") == "staging"


class TestGeneratedFlags:
    def test_environment_generates_a_root_flag(self) -> None:
        options = generated_setting_options(_main.settings_schema())
        flags = {option.opts[0] for option in options}
        assert "--environment" in flags
        assert "--config-profile" in flags

    def test_only_config_profile_is_early(self) -> None:
        """`--environment` is an ordinary flag; the profile must be pre-boot."""
        early = [s.name for s in _main.DEPLOY_SETTINGS if s.phase == "early"]
        assert early == ["deploy.config_profile"]
        schema = _main.settings_schema()
        assert early_setting_flags(schema, ["--environment", "prod", "status"]) == {}

    @pytest.mark.parametrize(
        "argv",
        [
            ["--config-profile", "staging", "status"],
            ["--config-profile=staging", "status"],
        ],
    )
    def test_both_spellings_are_read_pre_boot(self, argv: list[str]) -> None:
        schema = _main.settings_schema()
        assert early_setting_flags(schema, argv) == {"deploy.config_profile": "staging"}

    def test_a_missing_value_is_left_for_click(self) -> None:
        schema = _main.settings_schema()
        assert early_setting_flags(schema, ["status", "--config-profile"]) == {}

    def test_the_early_flag_is_in_the_first_snapshot(self, isolated: Path) -> None:
        resolved = _main.boot_settings(
            ["--config-profile", "staging", "status"], cwd=isolated
        )
        assert resolved.get("deploy.config_profile") == "staging"
        assert resolved.provenance["deploy.config_profile"] == "cli"

    def test_the_early_flag_outranks_env(
        self, isolated: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEPLOY_TOOL_DEPLOY_CONFIG_PROFILE", "from-env")
        assert (
            _main.boot_settings([], cwd=isolated).get("deploy.config_profile")
            == "from-env"
        )
        resolved = _main.boot_settings(["--config-profile=flag"], cwd=isolated)
        assert resolved.get("deploy.config_profile") == "flag"

    def test_main_constructs_the_app_with_the_early_snapshot(
        self, isolated: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The entry path itself: argv → snapshot → `ConfigSources(resolved=…)`."""
        built: list[object] = []

        class _Adapter:
            def __call__(self, app: object) -> None:
                built.append(app)

            def run(self) -> None:
                pass

        monkeypatch.chdir(_ROOT)
        monkeypatch.setattr(_main, "CliAdapter", _Adapter)
        monkeypatch.setattr(
            sys, "argv", ["deploy-tool", "--config-profile", "staging", "status"]
        )
        _main.main()

        (app,) = built
        assert app.settings.get("deploy.config_profile") == "staging"  # type: ignore[attr-defined]
        assert app.settings.provenance["deploy.config_profile"] == "cli"  # type: ignore[attr-defined]

    def test_the_pre_boot_read_imports_no_job_module(self, tmp_path: Path) -> None:
        """Pre-boot work must not import user code.

        A subprocess with a job module that would announce itself on import:
        what is *not* loaded cannot be shown once anything has imported it.
        """
        (tmp_path / "jobs").mkdir()
        (tmp_path / "jobs" / "loud.py").write_text(
            "raise SystemExit('JOB MODULE IMPORTED')\n"
        )
        script = (
            "import importlib.util, sys;"
            f"spec = importlib.util.spec_from_file_location('m', {str(_ROOT / 'deploy_tool' / 'main.py')!r});"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m);"
            "r = m.boot_settings(['--config-profile', 'staging', 'status']);"
            "assert r.get('deploy.config_profile') == 'staging', r.values;"
            "mods = [n for n in sys.modules if 'loud' in n];"
            "assert mods == [], mods;"
            "print('ok')"
        )
        env = {
            **os.environ,
            "HOME": str(tmp_path),
            "XDG_CONFIG_HOME": str(tmp_path / "xdg-config"),
            "XDG_DATA_HOME": str(tmp_path / "xdg-data"),
            "XDG_CACHE_HOME": str(tmp_path / "xdg-cache"),
        }
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env=env,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "ok" in result.stdout

    def test_a_generated_flag_outranks_env(self, isolated: Path) -> None:
        schema = _main.settings_schema()
        env = {"DEPLOY_TOOL_DEPLOY_ENVIRONMENT": "staging"}
        unflagged = resolve_settings(schema, isolated, env=env)
        assert unflagged.get("deploy.environment") == "staging"

        flags = passed_setting_flags(schema, {"environment": "prod"})
        resolved = resolve_settings(schema, isolated, flags=flags, env=env)
        assert resolved.get("deploy.environment") == "prod"
