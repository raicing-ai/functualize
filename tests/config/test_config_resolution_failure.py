"""How a job fails when its required config is not there.

Missing required config is the most common thing a user gets wrong, and it used
to be the worst-reported: `execute()` raised the Pydantic ValidationError
straight out, so the CLI's field-level error panel — which reads
`result.exception` off a returned JobResult — never ran, and the user got a
90-line traceback instead.

The other half of the problem is diagnostic. "Field required" cannot
distinguish "I set the wrong value" from "my config file was never read", and
the second is easy to hit: config files must be named `config.<slot>.<ext>`, so
a plain `config.toml` is ignored, and the fallback to the user config directory
is silent. These tests pin both the failure shape and the hint.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from pydantic import BaseModel, Field, ValidationError

from functualize._app.state import AppState
from functualize.app.adapters.cli import _config_source_hint
from functualize.app.core import FunctualizeApp
from functualize.job import RunStatus


@pytest.fixture(autouse=True)
def _isolated_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None]:
    """Run in an empty project with no config anywhere above it.

    HOME is redirected too: discovery falls back to the user config directory,
    and a developer's real ~/.config/functualize/config.toml would otherwise
    leak into the test.
    """
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(project)
    AppState.reset()
    yield
    AppState.reset()


class NeedsCity(BaseModel):
    city: str = Field(description="Required; no default")
    days: int = 3


def _app() -> FunctualizeApp:
    app = FunctualizeApp(name="cfgtest")

    def report(config: NeedsCity) -> str:
        return f"city={config.city}"

    app.register_dynamic_job("report", report, config_class=NeedsCity)
    return app


class TestFailureShape:
    def test_missing_config_returns_a_result_instead_of_raising(self) -> None:
        """The regression this guards. A raise skips the CLI's error panel,
        which can only render an exception carried on a returned JobResult."""
        result = _app().execute("report")

        assert result.status is RunStatus.FAILURE
        assert isinstance(result.exception, ValidationError)

    def test_the_exception_names_the_missing_field(self) -> None:
        result = _app().execute("report")

        assert result.exception is not None
        fields = {err["loc"][0] for err in result.exception.errors()}
        assert fields == {"city"}

    def test_a_config_failure_does_not_run_the_job(self) -> None:
        app = FunctualizeApp(name="cfgtest")
        ran: list[str] = []

        def report(config: NeedsCity) -> str:
            ran.append("body")
            return "never"

        app.register_dynamic_job("report", report, config_class=NeedsCity)
        app.execute("report")

        assert ran == []

    def test_execute_never_raises_for_missing_config(self) -> None:
        """The invariant, stated directly: `execute()` reports failures by
        returning them. A caller that has to wrap it in try/except for one
        failure mode and check `.status` for every other one cannot write a
        correct runner — which is exactly what the CLI is."""
        try:
            result = _app().execute("report")
        except Exception as exc:  # pragma: no cover - the regression itself
            pytest.fail(f"execute() raised {type(exc).__name__} instead of returning")

        assert result.status is RunStatus.FAILURE

    def test_satisfying_the_config_lets_the_job_run(self) -> None:
        """The failure path must not have broken the success path."""
        result = _app().execute("report", city="Kyoto")

        assert result.status is RunStatus.SUCCESS
        assert result.return_value == "city=Kyoto"


class TestConfigSourceHint:
    def test_it_says_when_nothing_was_discovered(self) -> None:
        hint = _config_source_hint(_app(), "report")

        assert "No config files were discovered" in hint
        # The two ways out, both of which the bare Pydantic error omits.
        assert "config.<slot>.<ext>" in hint
        assert "REPORT__<FIELD>" in hint

    def test_it_lists_the_files_that_were_read(self, tmp_path: Path) -> None:
        (Path.cwd() / "config.base.toml").write_text('[report]\ncity = "Kyoto"\n')
        AppState.reset()

        hint = _config_source_hint(_app(), "report")

        assert "config.base.toml" in hint
        assert "No config files" not in hint

    def test_introspection_failure_never_masks_the_real_error(self) -> None:
        """The hint is a diagnostic on an error path. If it cannot be produced,
        the user must still get the validation error, not a second failure."""

        class Exploding:
            def config_files(self, job_name):
                raise RuntimeError("introspection is broken")

        assert _config_source_hint(Exploding(), "report") == ""


class TestDiscoveryAnchoring:
    """Which filenames anchor discovery, and which are read.

    Both sides now describe the same set — `config.<slot>.<ext>` where `<ext>`
    has a registered format provider — after two rounds of fixing where they
    disagreed (resolved questions 15 and 16). These tests pin the agreement
    from both directions: a file that anchors must be read, and a file that
    cannot be read must not anchor.
    """

    def test_a_slotted_file_anchors_discovery(self) -> None:
        (Path.cwd() / "config.base.toml").write_text('[report]\ncity = "Osaka"\n')
        AppState.reset()

        assert _app().execute("report").return_value == "city=Osaka"

    def test_a_plain_config_toml_does_not_anchor_discovery(self) -> None:
        (Path.cwd() / "config.toml").write_text('[report]\ncity = "Kyoto"\n')
        AppState.reset()

        result = _app().execute("report")
        assert result.status is RunStatus.FAILURE, (
            "an unslotted config.toml must neither anchor nor be read; if this "
            "passes, the slot rule regressed and the hint text is now a lie"
        )

    def test_a_plain_config_toml_is_ignored_even_beside_a_slotted_file(self) -> None:
        """Ratified 2026-07-20 (resolved question 15).

        This is the case that used to be inconsistent: `config.toml` was read
        here — because a slotted sibling had anchored the directory — and
        ignored when it stood alone. The reader now requires the same
        `<slot>` segment the anchor does, so the file is ignored either way
        and `city` stays unresolved.
        """
        cwd = Path.cwd()
        (cwd / "config.base.toml").write_text("[report]\ndays = 5\n")
        (cwd / "config.toml").write_text('[report]\ncity = "Kyoto"\n')
        AppState.reset()

        result = _app().execute("report")

        assert result.status is RunStatus.FAILURE
        assert _config_source_hint(_app(), "report").count("config.toml") == 0

    def test_the_reader_filter_is_a_slot_check_not_an_extension_check(self) -> None:
        """The narrowing is deliberately about the missing `<slot>` only.

        The reader filter accepts any extension, so it does not drop `.cfg` or
        a format some plugin registers. `.cfg` still needs *something* to
        anchor the directory, because the anchor regex separately pins the
        extension to ini|toml — a smaller instance of the same anchor/reader
        asymmetry, left alone because only the slot question was ratified.
        """
        cwd = Path.cwd()
        (cwd / "config.base.toml").write_text("[report]\ndays = 4\n")
        (cwd / "config.prod.cfg").write_text("[report]\ncity = Osaka\n")
        AppState.reset()

        hint = _config_source_hint(_app(), "report")

        # Slotted and non-toml: kept by the reader filter.
        assert "config.prod.cfg" in hint

    def test_a_cfg_file_alone_can_anchor_and_resolve(self) -> None:
        """Ratified 2026-07-20: the anchor no longer pins the extension.

        `.cfg` is handled by the built-in ini provider, so a directory holding
        only `config.base.cfg` must anchor on it. Previously the anchor regex
        spelled `(ini|toml)` inline, so this file could be *read* but never
        *found* — the same asymmetry as the slot, one level down.
        """
        (Path.cwd() / "config.base.cfg").write_text("[report]\ncity = Osaka\n")
        AppState.reset()

        assert _app().execute("report").return_value == "city=Osaka"

    def test_an_extension_no_provider_handles_does_not_anchor(self) -> None:
        """The extension check is delegated to the registered providers, not
        dropped. Anchoring on a file nothing can parse would pick a directory
        that then contributes no values at all."""
        (Path.cwd() / "config.base.xyz").write_text("nonsense")
        AppState.reset()

        assert "No config files were discovered" in _config_source_hint(
            _app(), "report"
        )

    def test_dot_functualize_toml_is_not_job_config(self) -> None:
        """`.functualize.toml` carries settings ([discovery], [tui]); job
        config sections in it are not read."""
        (Path.cwd() / ".functualize.toml").write_text('[report]\ncity = "Nara"\n')
        AppState.reset()

        assert _app().execute("report").status is RunStatus.FAILURE
