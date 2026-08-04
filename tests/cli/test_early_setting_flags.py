"""C3.2 — `phase="early"` pre-boot argv scan.

"Early" means *before the app exists*. A flag that changes discovery or config
resolution cannot wait for the click callback, which runs after boot — so the
distinguishing property is not "is it applied" but "is it applied without
constructing anything".
"""

from __future__ import annotations

import pytest

from functualize._cli.data.func_settings import (
    FuncSetting,
    FuncSettingsStore,
    clear_preboot_overrides,
    clear_registered_settings,
    early_flag_specs,
    preboot_overrides,
    register_settings,
    registered_settings,
)
from functualize._cli.data.settings_schema import SettingSchema
from functualize._cli.dispatch import scan_early_setting_flags


def _setting(
    name: str,
    *,
    default: str = "base",
    cli_flag: str | None = None,
    phase: str | None = None,
) -> FuncSetting:
    section, _, key = name.rpartition(".")
    return FuncSetting(
        name=name,
        section=section,
        key=key,
        schema=SettingSchema(name=key, type="str", description=f"{name} help"),
        default=default,
        cli_flag=cli_flag,
        phase=phase,
    )


@pytest.fixture
def clean():
    saved = registered_settings()
    clear_registered_settings()
    clear_preboot_overrides()
    yield
    clear_registered_settings()
    clear_preboot_overrides()
    register_settings(*saved)


class TestEarlySelection:
    def test_only_early_settings_are_scanned(self, clean) -> None:
        """The AC's negative half: a non-early flag is not read pre-boot."""
        register_settings(
            _setting("demo.early", cli_flag="--early", phase="early"),
            _setting("demo.late", cli_flag="--late"),
        )
        assert dict(early_flag_specs()) == {"--early": "demo.early"}

    def test_a_flag_without_a_phase_is_not_early(self, clean) -> None:
        register_settings(_setting("demo.late", cli_flag="--late"))
        assert early_flag_specs() == []

    def test_an_early_setting_without_a_flag_is_not_scannable(self, clean) -> None:
        """`phase` is meaningless without something to type."""
        register_settings(_setting("demo.odd", phase="early"))
        assert early_flag_specs() == []

    def test_no_shipped_setting_is_early_yet(self, clean) -> None:
        """Baseline guard — the scan is a no-op for func itself."""
        register_settings(*registered_settings())
        assert early_flag_specs() == []


class TestScanning:
    def test_space_separated_value(self, clean) -> None:
        register_settings(_setting("demo.early", cli_flag="--early", phase="early"))
        assert scan_early_setting_flags(["--early", "yes", "deploy"]) == 1
        assert preboot_overrides()["demo.early"] == ("yes", "--early")

    def test_equals_separated_value(self, clean) -> None:
        register_settings(_setting("demo.early", cli_flag="--early", phase="early"))
        assert scan_early_setting_flags(["--early=yes"]) == 1
        assert preboot_overrides()["demo.early"] == ("yes", "--early")

    def test_non_early_flags_are_ignored(self, clean) -> None:
        register_settings(
            _setting("demo.early", cli_flag="--early", phase="early"),
            _setting("demo.late", cli_flag="--late"),
        )
        assert scan_early_setting_flags(["--late", "no"]) == 0
        assert preboot_overrides() == {}

    def test_a_trailing_flag_with_no_value_is_left_alone(self, clean) -> None:
        """The real parser reports that error; this scan must not guess."""
        register_settings(_setting("demo.early", cli_flag="--early", phase="early"))
        assert scan_early_setting_flags(["--early"]) == 0
        assert preboot_overrides() == {}

    def test_scan_is_a_no_op_with_nothing_early(self, clean) -> None:
        register_settings(_setting("demo.late", cli_flag="--late"))
        assert scan_early_setting_flags(["--late", "x", "--early", "y"]) == 0


class TestTakesEffectBeforeConstruction:
    def test_a_store_built_after_the_scan_sees_the_value(self, clean) -> None:
        """The whole point: the value is live for the *first* store."""
        register_settings(
            _setting("demo.early", default="base", cli_flag="--early", phase="early")
        )
        scan_early_setting_flags(["--early", "scanned"])

        store = FuncSettingsStore(layers=[], env={})
        assert store.effective_values()["demo.early"] == "scanned"

    def test_it_outranks_env(self, clean) -> None:
        register_settings(
            _setting("demo.early", default="base", cli_flag="--early", phase="early")
        )
        scan_early_setting_flags(["--early", "scanned"])

        store = FuncSettingsStore(layers=[], env={"FUNCTUALIZE_DEMO_EARLY": "from-env"})
        assert store.effective_values()["demo.early"] == "scanned"

    def test_without_a_scan_the_default_still_wins(self, clean) -> None:
        register_settings(
            _setting("demo.early", default="base", cli_flag="--early", phase="early")
        )
        store = FuncSettingsStore(layers=[], env={})
        assert store.effective_values()["demo.early"] == "base"

    def test_the_source_label_names_the_flag(self, clean) -> None:
        register_settings(
            _setting("demo.early", default="base", cli_flag="--early", phase="early")
        )
        scan_early_setting_flags(["--early", "scanned"])
        store = FuncSettingsStore(layers=[], env={})
        assert store.source_labels()["demo.early"] == "--early"


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
                "scan_early_setting_flags(['--anything', 'x']);"
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
