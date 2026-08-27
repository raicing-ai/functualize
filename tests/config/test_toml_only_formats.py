"""TOML is the only config format registered by default (ADR-007).

Two things are asserted here, and they are different things:

- **The default registry carries TOML alone.** Before this, ``boot_standard``
  registered ``IniFormatProvider`` unconditionally *before* entry-point
  discovery ran, so removing the ``ini`` entry point from ``pyproject.toml``
  changed nothing at all — the ADR's decision was a no-op. A test that only
  checked the entry points would have passed against the broken build.
- **INI is still reachable on purpose.** ``IniFormatProvider`` stays in-tree
  and importable. An application that still reads INI registers it itself.
  Narrowing the default is not the same as deleting the capability, and the
  test that proves the narrowing must also prove the escape hatch.

``func builtin config migrate`` is covered here too, because it is the answer
the narrowing owes its users — and because its helper, ``migrate_ini_to_toml``,
sat in the tree with zero callers and zero tests until this command reached it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize._app.state import AppState
from functualize._config.providers.ini import IniFormatProvider
from functualize.app.config import JobSources
from functualize.app.core import FunctualizeApp


@pytest.fixture(autouse=True)
def _reset_state():
    AppState.reset()
    yield
    AppState.reset()


def _extensions(app: FunctualizeApp) -> set[str]:
    return set(app.config_registry.list_format_providers())


class TestDefaultFormatRegistry:
    """What a freshly booted app can parse, with nobody having said anything."""

    def test_toml_is_registered(self) -> None:
        app = FunctualizeApp(name="t", job_sources=JobSources(directories=[]))
        assert ".toml" in _extensions(app)

    def test_ini_is_not_registered(self) -> None:
        """The regression that made ADR-007 a no-op.

        Sabotage check: restore the ``register_format_provider(
        IniFormatProvider())`` line in ``_app/boot.py`` and this goes red.
        """
        app = FunctualizeApp(name="t", job_sources=JobSources(directories=[]))
        assert ".ini" not in _extensions(app)
        assert ".cfg" not in _extensions(app)

    def test_the_provider_is_still_importable_and_registerable(self) -> None:
        """Narrowed, not removed — the class and the registry seam both remain.

        This asserts only what it says: the registry accepts it. It is *not*
        the escape hatch, because by the time an app object exists the
        resolution chain has already been built from the providers registered
        during boot. ``TestIniViaPlugin`` covers the path that actually works,
        and the distinction is the whole subject of this file.
        """
        app = FunctualizeApp(name="t", job_sources=JobSources(directories=[]))
        app.config_registry.register_format_provider(IniFormatProvider())

        exts = _extensions(app)
        assert ".ini" in exts
        assert ".cfg" in exts
        assert app.config_registry.get_format_provider(".ini") is not None


class TestIniFileIsNotDiscovered:
    """The user-visible half: a `.ini` config no longer anchors a directory."""

    def _project(self, tmp_path: Path, filename: str) -> Path:
        root = tmp_path / filename.replace(".", "_")
        jobs = root / ".functualize" / "jobs"
        jobs.mkdir(parents=True)
        jobs.joinpath("show.py").write_text(
            "from pydantic import BaseModel, Field\n"
            "\n"
            "from functualize.job.decorators import job\n"
            "\n"
            "\n"
            "class ShowConfig(BaseModel):\n"
            '    app_name: str = Field(default="from-model-default")\n'
            "\n"
            "\n"
            "@job\n"
            "def show(config: ShowConfig) -> None:\n"
            '    print("app_name=" + config.app_name)\n'
        )
        return root

    def test_toml_config_is_read(self, tmp_path: Path, cli_run) -> None:
        root = self._project(tmp_path, "config.base.toml")
        (root / "config.base.toml").write_text('[show]\napp_name = "from-toml"\n')

        result = cli_run(["show"], cwd=root)
        assert result.exit_code == 0
        assert "app_name=from-toml" in result.stdout

    def test_ini_config_is_ignored(self, tmp_path: Path, cli_run) -> None:
        """Same content, `.ini` extension — the model default survives."""
        root = self._project(tmp_path, "config.base.ini")
        (root / "config.base.ini").write_text("[show]\napp_name = from-ini\n")

        result = cli_run(["show"], cwd=root)
        assert result.exit_code == 0
        assert "app_name=from-model-default" in result.stdout
        assert "from-ini" not in result.stdout


class TestConfigMigrate:
    """`func builtin config migrate` — the reachability the helper lacked.

    Sabotage check: replace the ``migrate_ini_to_toml(source, target)`` call in
    ``_cli/builtins.py`` with ``pass`` and every test in this class goes red.
    """

    def test_converts_sections_and_keys(self, tmp_path: Path, cli_run) -> None:
        src = tmp_path / "config.base.ini"
        src.write_text("[general]\napp_name = demo\nretries = 3\n")

        result = cli_run(
            ["builtin", "config", "migrate", str(src), str(tmp_path / "out.toml")]
        )

        assert result.exit_code == 0, result.stderr
        written = (tmp_path / "out.toml").read_text()
        assert "[general]" in written
        assert 'app_name = "demo"' in written
        assert 'retries = "3"' in written

    def test_destination_defaults_to_toml_sibling(
        self, tmp_path: Path, cli_run
    ) -> None:
        src = tmp_path / "config.prod.ini"
        src.write_text("[general]\napp_name = demo\n")

        result = cli_run(["builtin", "config", "migrate", str(src)])

        assert result.exit_code == 0, result.stderr
        assert (tmp_path / "config.prod.toml").exists()

    def test_source_is_left_in_place(self, tmp_path: Path, cli_run) -> None:
        """Nothing is deleted for the user."""
        src = tmp_path / "config.base.ini"
        src.write_text("[general]\napp_name = demo\n")

        cli_run(["builtin", "config", "migrate", str(src)])

        assert src.exists()

    def test_refuses_to_overwrite(self, tmp_path: Path, cli_run) -> None:
        src = tmp_path / "config.base.ini"
        src.write_text("[general]\napp_name = demo\n")
        dest = tmp_path / "config.base.toml"
        dest.write_text("# hand-written, do not clobber\n")

        result = cli_run(["builtin", "config", "migrate", str(src), str(dest)])

        assert result.exit_code == 1
        assert "already exists" in result.stderr
        assert "hand-written" in dest.read_text()

    def test_reports_interpolation_by_line(self, tmp_path: Path, cli_run) -> None:
        """`%(key)s` has no TOML equivalent — say so, don't write half a file."""
        src = tmp_path / "config.base.ini"
        src.write_text("[general]\nroot = /srv\npath = %(root)s/data\n")

        result = cli_run(["builtin", "config", "migrate", str(src)])

        assert result.exit_code == 1
        assert "line 3" in result.stderr
        assert "interpolation" in result.stderr
        assert not (tmp_path / "config.base.toml").exists()

    def test_missing_source_is_an_error(self, tmp_path: Path, cli_run) -> None:
        result = cli_run(["builtin", "config", "migrate", str(tmp_path / "nope.ini")])

        assert result.exit_code == 1
        assert "not found" in result.stderr

    def test_listed_as_a_config_subcommand(self, cli_run) -> None:
        """Discoverable, not just callable."""
        result = cli_run(["builtin", "config"])

        assert "migrate" in result.stdout


_INI_PLUGIN = """
from functualize._config.providers.ini import IniFormatProvider


class _Plugin:
    name = "ini-format"
    version = "1.0.0"
    description = "Restores INI config parsing"

    def __call__(self, app):
        app.config_registry.register_format_provider(IniFormatProvider())


plugin = _Plugin()
"""


class TestIniViaPlugin:
    """The escape hatch that actually works, end to end.

    Boot loads plugins *before* it builds the resolution chain, precisely so a
    plugin can register providers. Registering on ``app.config_registry`` after
    construction is too late for file discovery — ADR-007's original wording
    named that as the escape hatch, and it would have left a user who followed
    the ADR with a `.ini` file that is parseable and never read.
    """

    def _project(self, project_tree, *, config_name: str) -> Path:
        root = project_tree(
            jobs={
                "show.py": (
                    "from pydantic import BaseModel, Field\n"
                    "\n"
                    "from functualize.job.decorators import job\n"
                    "\n"
                    "\n"
                    "class ShowConfig(BaseModel):\n"
                    '    app_name: str = Field(default="from-model-default")\n'
                    "\n"
                    "\n"
                    "@job\n"
                    "def show(config: ShowConfig) -> None:\n"
                    '    print("app_name=" + config.app_name)\n'
                ),
            },
            plugins={"ini_format.py": _INI_PLUGIN},
        )
        (root / config_name).write_text("[show]\napp_name = from-ini\n")
        return root

    def test_a_plugin_restores_ini_file_resolution(self, project_tree, cli_run) -> None:
        root = self._project(project_tree, config_name="config.base.ini")

        result = cli_run(["show"], cwd=root)

        assert result.exit_code == 0
        assert "app_name=from-ini" in result.stdout

    def test_without_the_plugin_the_same_file_is_ignored(
        self, project_tree, cli_run
    ) -> None:
        """The control. Same tree, same file, no plugin."""
        root = project_tree(
            jobs={
                "show.py": (
                    "from pydantic import BaseModel, Field\n"
                    "\n"
                    "from functualize.job.decorators import job\n"
                    "\n"
                    "\n"
                    "class ShowConfig(BaseModel):\n"
                    '    app_name: str = Field(default="from-model-default")\n'
                    "\n"
                    "\n"
                    "@job\n"
                    "def show(config: ShowConfig) -> None:\n"
                    '    print("app_name=" + config.app_name)\n'
                ),
            },
        )
        (root / "config.base.ini").write_text("[show]\napp_name = from-ini\n")

        result = cli_run(["show"], cwd=root)

        assert result.exit_code == 0
        assert "app_name=from-model-default" in result.stdout
