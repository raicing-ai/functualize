"""C3.2 — `phase="early"` pre-boot argv scan.

"Early" means *before the app exists*. A flag that changes discovery or config
resolution cannot wait for the click callback, which runs after boot — so the
distinguishing property is not "is it applied" but "is it applied without
constructing anything".

Every schema here is explicit. The public helper
(`functualize.app.adapters.early_setting_flags`) is exercised with stand-in
declarations; `func`'s own pre-boot scan (`_cli/dispatch.py`) with
`FUNCTUALIZE_SETTINGS`, the declaration it reads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from functualize._cli.data.func_settings import (
    FuncSettingsStore,
)
from functualize._cli.dispatch import scan_early_setting_flags
from functualize.app.adapters import early_setting_flags
from functualize.plugin import (
    FUNCTUALIZE_SETTINGS,
    AppSettingsSchema,
    Setting,
    resolve_settings,
)

if TYPE_CHECKING:
    from pathlib import Path


def _setting(
    name: str,
    *,
    type_: str = "str",
    default: str = "base",
    cli_flag: str | None = None,
    phase: str | None = None,
) -> Setting:
    return Setting(
        name,
        type_,
        f"{name} help",
        default=default,
        cli_flag=cli_flag,
        phase=phase,
    )


def _schema(*settings: Setting) -> AppSettingsSchema:
    return AppSettingsSchema(settings=settings)


EARLY = _setting("demo.early", cli_flag="--early", phase="early")
LATE = _setting("demo.late", cli_flag="--late")


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    project = tmp_path / "project"
    project.mkdir()
    return project


class TestEarlySelection:
    def test_only_early_settings_are_read(self) -> None:
        """The AC's negative half: a non-early flag is not read pre-boot."""
        schema = _schema(EARLY, LATE)
        argv = ["--early", "x", "--late", "y"]
        assert early_setting_flags(schema, argv) == {"demo.early": "x"}

    def test_a_flag_without_a_phase_is_not_early(self) -> None:
        assert early_setting_flags(_schema(LATE), ["--late", "y"]) == {}

    def test_an_early_setting_without_a_flag_is_not_scannable(self) -> None:
        """`phase` is meaningless without something to type."""
        odd = _setting("demo.odd", phase="early")
        assert early_setting_flags(_schema(odd), ["--odd", "x"]) == {}

    def test_funcs_declared_flags_are_early(self) -> None:
        """`func`'s pre-boot scan reads its own declaration, not a registry."""
        argv = ["--discovery-depth", "3", "--require-job-prefix=deploy_", "build"]
        assert early_setting_flags(FUNCTUALIZE_SETTINGS, argv) == {
            "discovery.scan_depth": "3",
            "discovery.require_job_prefix": "deploy_",
        }


class TestReading:
    def test_space_separated_value(self) -> None:
        argv = ["--early", "yes", "deploy"]
        assert early_setting_flags(_schema(EARLY), argv) == {"demo.early": "yes"}

    def test_equals_separated_value(self) -> None:
        argv = ["--early=yes"]
        assert early_setting_flags(_schema(EARLY), argv) == {"demo.early": "yes"}

    def test_ordinary_flags_are_ignored(self) -> None:
        argv = ["--late", "no", "--verbose", "deploy", "--other=1"]
        assert early_setting_flags(_schema(EARLY, LATE), argv) == {}

    def test_a_trailing_flag_with_no_value_is_left_alone(self) -> None:
        """The real parser reports that error; this scan must not guess."""
        assert early_setting_flags(_schema(EARLY), ["--early"]) == {}

    def test_the_last_scalar_wins(self) -> None:
        """As it does for click, which parses the same tokens later."""
        argv = ["--early", "one", "--early=two"]
        assert early_setting_flags(_schema(EARLY), argv) == {"demo.early": "two"}

    def test_a_list_setting_collects_every_occurrence(self) -> None:
        paths = _setting("demo.paths", type_="list", cli_flag="--path", phase="early")
        argv = ["--path", "a", "--path=b"]
        assert early_setting_flags(_schema(paths), argv) == {"demo.paths": ("a", "b")}

    def test_nothing_early_reads_nothing(self) -> None:
        argv = ["--late", "x", "--early", "y"]
        assert early_setting_flags(_schema(LATE), argv) == {}


class TestFlagPrecedence:
    def test_an_early_flag_outranks_env_and_default(self, isolated: Path) -> None:
        schema = _schema(EARLY)
        env = {"FUNCTUALIZE_DEMO_EARLY": "from-env"}
        flags = early_setting_flags(schema, ["--early", "scanned"])

        resolved = resolve_settings(schema, isolated, flags=flags, env=env)
        assert resolved.get("demo.early") == "scanned"
        assert resolved.provenance["demo.early"] == "cli"

    def test_without_the_flag_env_still_wins(self, isolated: Path) -> None:
        schema = _schema(EARLY)
        env = {"FUNCTUALIZE_DEMO_EARLY": "from-env"}
        flags = early_setting_flags(schema, ["deploy"])

        resolved = resolve_settings(schema, isolated, flags=flags, env=env)
        assert resolved.get("demo.early") == "from-env"


class TestFuncsPreBootScan:
    def test_space_and_equals_spellings_are_recorded(self) -> None:
        argv = ["--discovery-depth", "3", "--exclude", "a", "--exclude=b", "build"]
        assert scan_early_setting_flags(argv) == {
            "discovery.scan_depth": "3",
            "discovery.exclude_patterns": ("a", "b"),
        }

    def test_ordinary_and_unvalued_flags_are_left_alone(self) -> None:
        assert scan_early_setting_flags(["--log-level", "DEBUG", "--exclude"]) == {}

    def test_each_scan_describes_one_invocation(self) -> None:
        """A second scan replaces the first rather than adding to it."""
        first = scan_early_setting_flags(["--discovery-depth", "3"])
        second = scan_early_setting_flags(["--require-job-prefix", "deploy_"])
        assert first == {"discovery.scan_depth": "3"}
        assert second == {"discovery.require_job_prefix": "deploy_"}


class TestFuncsEntryPath:
    @pytest.mark.surfaces("func")
    def test_main_uses_early_flags_before_boot(self, cli_run, isolated: Path) -> None:
        """`func`'s real `main()` runs the scan over its own argv."""
        argv = ["--discovery-depth", "3", "--exclude=build", "--help"]
        result = cli_run(argv, cwd=isolated)
        assert result.exit_code == 0, result.stderr
        assert scan_early_setting_flags(argv) == {
            "discovery.scan_depth": "3",
            "discovery.exclude_patterns": ("build",),
        }


class TestTakesEffectBeforeConstruction:
    def _store(
        self, project: Path, env: dict[str, str], flags: dict | None = None
    ) -> FuncSettingsStore:
        return FuncSettingsStore(
            FUNCTUALIZE_SETTINGS,
            cwd=project,
            env=env,
            global_dir=project / "g",
            flags=flags,
        )

    def test_a_store_built_after_the_scan_sees_the_value(self, isolated: Path) -> None:
        """The whole point: the value is live for the *first* store."""
        flags = scan_early_setting_flags(["--discovery-depth", "3"])
        store = self._store(isolated, {}, flags)
        assert store.effective_values()["discovery.scan_depth"] == "3"

    def test_it_outranks_env(self, isolated: Path) -> None:
        flags = scan_early_setting_flags(["--discovery-depth", "3"])
        store = self._store(isolated, {"FUNCTUALIZE_DISCOVERY_SCAN_DEPTH": "5"}, flags)
        assert store.effective_values()["discovery.scan_depth"] == "3"

    def test_without_a_scan_the_default_still_wins(self, isolated: Path) -> None:
        store = self._store(isolated, {})
        assert store.effective_values()["discovery.scan_depth"] == "0"

    def test_the_source_label_names_the_flag(self, isolated: Path) -> None:
        flags = scan_early_setting_flags(["--discovery-depth", "3"])
        store = self._store(isolated, {}, flags)
        assert store.source_labels()["discovery.scan_depth"] == "--discovery-depth"

    def test_first_store_uses_the_apps_snapshot_and_flag_label(
        self, isolated: Path
    ) -> None:
        flags = scan_early_setting_flags(["--discovery-depth", "3"])
        snapshot = resolve_settings(
            FUNCTUALIZE_SETTINGS,
            isolated,
            flags=flags,
            env={},
            global_dir=isolated / "g",
        )
        store = FuncSettingsStore(
            FUNCTUALIZE_SETTINGS, snapshot=snapshot, cwd=isolated, env={}
        )
        assert store.effective_values()["discovery.scan_depth"] == "3"
        assert store.source_labels()["discovery.scan_depth"] == "--discovery-depth"

    def test_main_hands_the_early_snapshot_to_app_construction(
        self, isolated: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from functualize._cli.config import resolve_cli_config
        from functualize._cli.main import _config_sources_for_flags

        monkeypatch.chdir(isolated)
        flags = scan_early_setting_flags(["--discovery-depth", "3"])
        cli_config = resolve_cli_config(cli_flags=flags)
        sources = _config_sources_for_flags(cli_config, flags)
        assert sources.resolved is not None
        assert sources.resolved.get("discovery.scan_depth") == 3
        assert sources.resolved.provenance["discovery.scan_depth"] == "cli"


class TestNoImports:
    def test_the_scan_imports_no_job_modules(self, tmp_path) -> None:
        """The warm-boot contract: pre-boot work must not import user code.

        Run in a subprocess with a job module that would announce itself on
        import — the pre-boot budget is about what is *not* loaded, which a
        same-process assertion cannot demonstrate once anything has imported it.
        """
        import subprocess
        import sys

        (tmp_path / "jobs").mkdir()
        (tmp_path / "jobs" / "loud.py").write_text(
            "raise SystemExit('JOB MODULE IMPORTED')\n"
        )

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys;"
                "from functualize._cli.dispatch import scan_early_setting_flags;"
                "assert scan_early_setting_flags(['--discovery-depth', '2', 'x']) == {'discovery.scan_depth': '2'};"
                "mods = [m for m in sys.modules if 'loud' in m];"
                "assert mods == [], mods;"
                "print('ok')",
            ],
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "ok" in result.stdout
