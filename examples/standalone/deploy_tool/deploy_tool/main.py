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

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from functualize.app import ConfigSources, FunctualizeApp, JobSources
from functualize.app.adapters import CliAdapter, early_setting_flags
from functualize.plugin import (
    FUNCTUALIZE_SETTINGS,
    AppSettingsSchema,
    Setting,
    SettingsSources,
    resolve_settings,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from functualize.plugin import ResolvedSettings

APP_NAME = "deploy-tool"

#: This app's own settings. Plain data: importing this module registers
#: nothing anywhere, so building the app is the only place they take effect.
DEPLOY_SETTINGS: tuple[Setting, ...] = (
    Setting(
        name="deploy.environment",
        type="enum",
        description="Target environment for deploys",
        default="dev",
        choices=("dev", "staging", "prod"),
        # Generates `--environment` on the root group (C3.1). Resolution
        # order becomes: default < config file < DEPLOY_TOOL_DEPLOY_ENVIRONMENT
        # < --environment.
        cli_flag="--environment",
    ),
    Setting(
        name="deploy.config_profile",
        type="str",
        description="Config profile to load before discovery runs",
        default="default",
        cli_flag="--config-profile",
        # Read pre-boot (C3.2). It has to be: by the time the click callback
        # runs, discovery has already happened, so a profile that selects
        # *which jobs exist* would be applied too late to matter.
        phase="early",
    ),
)


def settings_schema() -> AppSettingsSchema:
    """This app's settings declaration — its own env prefix and file sections.

    The settings are functualize's base catalog **plus** this app's own:
    ``FUNCTUALIZE_SETTINGS.extend`` is the extension point, and it refuses a
    name the base already declares. Passing only the two deploy settings
    would silently drop every built-in key (``discovery.*``, ``cli.*``, …)
    from this app.

    Three things have to be declared for `deploy-tool` to be a genuinely
    separate identity, and each replaces something that used to be a hardcoded
    ``functualize`` literal:

    - ``env_prefix`` → ``DEPLOY_TOOL_DEPLOY_ENVIRONMENT`` rather than
      ``FUNCTUALIZE_…``.
    - ``file_section_prefixes`` → settings nest under ``[tool.deploy-tool]`` in
      the shared ``pyproject.toml``, and sit at the top level of the app's own
      file.
    - ``sources`` → the project file names to walk upward for.
    """
    declared = FUNCTUALIZE_SETTINGS.extend(*DEPLOY_SETTINGS)
    return AppSettingsSchema(
        settings=declared.settings,
        env_prefix="DEPLOY_TOOL",
        sources=SettingsSources(
            global_file_name="config.toml",
            project_file_names=("pyproject.toml", ".deploy-tool.toml"),
        ),
        file_section_prefixes={"pyproject.toml": "tool.deploy-tool"},
    )


def boot_settings(argv: Sequence[str], cwd: Path | None = None) -> ResolvedSettings:
    """Resolve the first snapshot, with this invocation's early flags in it.

    ``early_setting_flags`` reads only the settings declared
    ``phase="early"`` (here ``--config-profile``), in both ``--flag value``
    and ``--flag=value`` spellings, and leaves every other token for click.
    The result enters the resolver as its ``flags`` rung, so it outranks the
    environment and the files exactly like a flag click parses later.
    """
    schema = settings_schema()
    return resolve_settings(
        schema,
        Path.cwd() if cwd is None else cwd,
        flags=early_setting_flags(schema, argv),
    )


def build_app(resolved: ResolvedSettings | None = None) -> FunctualizeApp:
    """Construct the app.

    The declaration travels through ``config_sources``, so the app's boot
    snapshot and every surface that reads it — flags included — agree about
    which settings exist. ``resolved`` is the snapshot :func:`boot_settings`
    produced from argv; without one the app resolves on first use.
    """
    return FunctualizeApp(
        name=APP_NAME,
        job_sources=JobSources(directories=["jobs"], lazy=True),
        config_sources=ConfigSources(settings=settings_schema(), resolved=resolved),
    )


def main() -> None:
    """Entry point."""
    app = build_app(boot_settings(sys.argv[1:]))
    adapter = CliAdapter()
    adapter(app)
    adapter.run()


if __name__ == "__main__":
    main()
