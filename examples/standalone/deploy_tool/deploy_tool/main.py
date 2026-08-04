"""`deploy-tool` — a functualize app that is not `func`.

This example exists to show the four things convergence Phase C made possible
for an app that is *not* functualize itself:

1. **Its own settings identity** — `[tool.deploy-tool]` in `pyproject.toml`,
   `DEPLOY_TOOL_*` environment variables, its own global config file. None of
   it collides with `func`'s, and neither app sees the other's values.
2. **A generated root flag** — `--environment` exists because the setting
   declares `cli_flag`, not because anything here writes a `click.Option`.
3. **An `phase="early"` flag** — `--config-profile` is read from argv *before
   the app is constructed*, which is what a setting affecting discovery
   requires.
4. **A bare invocation that opens a shell** — `deploy-tool` with no arguments
   at a TTY launches the interactive shell; `inline_tui = false` in the config
   turns that back into printing help.

Run it with ``uv run deploy-tool``.
"""

from __future__ import annotations

from functualize.app import FunctualizeApp, JobSources
from functualize.app.adapters import CliAdapter

APP_NAME = "deploy-tool"


def build_app() -> FunctualizeApp:
    """Construct the app.

    ``name`` is what makes this a separate identity: the settings store
    namespaces its global config file by app name, so `deploy-tool` and `func`
    cannot read each other's values even on the same machine.
    """
    return FunctualizeApp(
        name=APP_NAME,
        job_sources=JobSources(directories=["jobs"], lazy=True),
    )


def register_settings() -> None:
    """Contribute this app's settings to the catalog.

    Registration (rather than a hardcoded catalog) is what convergence C2.4
    added — it is the same seam the interactive shell uses to contribute its
    own ``tui.*`` knobs, and it is why a setting declared here shows up in the
    resolution chain, the settings panel, and ``--help`` without any of those
    being told about it individually.
    """
    from functualize._cli.data.func_settings import FuncSetting, register_settings
    from functualize._cli.data.settings_schema import SettingSchema

    register_settings(
        FuncSetting(
            name="deploy.environment",
            section="deploy",
            key="environment",
            schema=SettingSchema(
                name="environment",
                type="enum",
                description="Target environment for deploys",
                choices=["dev", "staging", "prod"],
            ),
            default="dev",
            # Generates `--environment` on the root group (C3.1). Resolution
            # order becomes: default < config file < DEPLOY_TOOL_DEPLOY_ENVIRONMENT
            # < --environment.
            cli_flag="--environment",
        ),
        FuncSetting(
            name="deploy.config_profile",
            section="deploy",
            key="config_profile",
            schema=SettingSchema(
                name="config_profile",
                type="str",
                description="Config profile to load before discovery runs",
            ),
            default="default",
            cli_flag="--config-profile",
            # Read pre-boot (C3.2). It has to be: by the time the click
            # callback runs, discovery has already happened, so a profile that
            # selects *which jobs exist* would be applied too late to matter.
            phase="early",
        ),
    )


def settings_schema():
    """This app's settings declaration — its own env prefix and file sections.

    Three things have to be declared for `deploy-tool` to be a genuinely
    separate identity, and each replaces something that used to be a hardcoded
    ``functualize`` literal inside the store:

    - ``env_prefix`` → ``DEPLOY_TOOL_DEPLOY_ENVIRONMENT`` rather than
      ``FUNCTUALIZE_…``. Passing ``app_name`` alone is **not** enough: that
      namespaces the global config *file*, not the environment variables.
    - ``file_section_prefixes`` → settings nest under ``[tool.deploy-tool]`` in
      the shared ``pyproject.toml``, and sit at the top level of the app's own
      file.
    - ``sources`` → the project file names to walk upward for.
    """
    from functualize._cli.data.func_settings import FUNC_SCHEMA
    from functualize.plugin import AppSettingsSchema, SettingsSources

    return AppSettingsSchema(
        settings=FUNC_SCHEMA.settings,
        env_prefix="DEPLOY_TOOL",
        sources=SettingsSources(
            global_file_name="config.toml",
            project_file_names=("pyproject.toml", ".deploy-tool.toml"),
        ),
        file_section_prefixes={"pyproject.toml": "tool.deploy-tool"},
    )


def settings_store():
    """A store scoped to this app: its catalog, its env prefix, its files."""
    from functualize._cli.data.func_settings import FuncSettingsStore

    store = FuncSettingsStore.discover()
    return FuncSettingsStore(
        layers=store._layers,
        schema=settings_schema(),
        app_name=APP_NAME,
    )


def main() -> None:
    """Entry point."""
    register_settings()
    app = build_app()
    adapter = CliAdapter()
    adapter(app)
    adapter.run()


if __name__ == "__main__":
    main()
