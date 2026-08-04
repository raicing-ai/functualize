"""Tests for the deploy_tool example.

The job bodies are trivial; what is worth asserting is the part the example
exists to demonstrate — that this app has a settings identity of its own, and
that its two flags are generated from declarations rather than hand-written.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

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
def registered():
    """Register the example's settings, then restore the catalog."""
    from functualize._cli.data.func_settings import (
        clear_preboot_overrides,
        clear_registered_settings,
        register_settings,
        registered_settings,
    )

    saved = registered_settings()
    clear_registered_settings()
    clear_preboot_overrides()
    _main.register_settings()
    yield
    clear_registered_settings()
    clear_preboot_overrides()
    register_settings(*saved)


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


class TestSettingsIdentity:
    def test_settings_are_registered(self, registered) -> None:
        from functualize._cli.data.func_settings import SETTINGS_ORDER

        assert "deploy.environment" in SETTINGS_ORDER
        assert "deploy.config_profile" in SETTINGS_ORDER

    def test_the_app_has_its_own_name(self) -> None:
        assert _main.APP_NAME == "deploy-tool"

    def test_it_reads_its_own_env_prefix_not_funcs(self, registered) -> None:
        """The point of C2.2: two apps, one machine, no bleed.

        `app_name` alone would *not* achieve this — it namespaces the global
        config file, not the environment. The env prefix comes from the app's
        own `AppSettingsSchema`, which is why the example declares one.
        """
        from functualize._cli.data.func_settings import FuncSettingsStore

        schema = _main.settings_schema()
        store = FuncSettingsStore(
            layers=[],
            env={
                "FUNCTUALIZE_DEPLOY_ENVIRONMENT": "func-said-so",
                "DEPLOY_TOOL_DEPLOY_ENVIRONMENT": "prod",
            },
            schema=schema,
            app_name="deploy-tool",
        )
        assert store.effective_values()["deploy.environment"] == "prod"

    def test_it_nests_under_its_own_pyproject_table(self, registered) -> None:
        """`[tool.deploy-tool]`, not `[tool.functualize]`."""
        schema = _main.settings_schema()
        assert schema.section_prefix_for("pyproject.toml") == "tool.deploy-tool"


class TestGeneratedFlags:
    def test_environment_generates_a_root_flag(self, registered) -> None:
        from functualize.app.adapters.cli import _setting_flag_specs

        flags = {flag for flag, _d, _n, _h in _setting_flag_specs()}
        assert "--environment" in flags
        assert "--config-profile" in flags

    def test_only_config_profile_is_early(self, registered) -> None:
        """`--environment` is an ordinary flag; the profile must be pre-boot."""
        from functualize._cli.data.func_settings import early_flag_specs

        assert dict(early_flag_specs()) == {"--config-profile": "deploy.config_profile"}

    def test_the_early_flag_applies_before_a_store_exists(self, registered) -> None:
        from functualize._cli.data.func_settings import FuncSettingsStore
        from functualize._cli.dispatch import scan_early_setting_flags

        assert scan_early_setting_flags(["--config-profile", "staging"]) == 1
        store = FuncSettingsStore(layers=[], env={}, app_name="deploy-tool")
        assert store.effective_values()["deploy.config_profile"] == "staging"

    def test_a_generated_flag_outranks_env(self, registered) -> None:
        from functualize._cli.data.func_settings import FuncSettingsStore

        store = FuncSettingsStore(
            layers=[],
            env={"FUNCTUALIZE_DEPLOY_ENVIRONMENT": "staging"},
            app_name="deploy-tool",
        )
        assert store.effective_values()["deploy.environment"] == "staging"

        store.set_cli_override("deploy.environment", "prod", flag="--environment")
        assert store.effective_values()["deploy.environment"] == "prod"
