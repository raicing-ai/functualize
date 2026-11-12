"""Direct-run StdoutSurface gate (app/adapters/surface_gate.py).

The gate decides when a direct ``func <job>`` run wraps execution in
``stdout_live_session``:

- ``uses_live`` or an eligible ambient construct → yes (pre-existing gate),
- an *explicit* STDOUT preference (``@surface_hint("stdout")`` or the
  ``tui.default_surface`` setting / its env override) → yes (item 6's
  "general STDOUT branch" for direct runs),
- otherwise → no, keeping plain ``func <job>`` output byte-identical.

The ``requires_tty`` HARD rung outranks preferences: an EXCLUSIVE job never
gets a StdoutSurface that would fight it for the terminal.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

from functualize._types.enums import RunStatus
from functualize.app import ConfigSources, FunctualizeApp, JobSources, PluginSources
from functualize.app.adapters.surface_gate import wants_stdout_surface

if TYPE_CHECKING:
    import pytest

# =============================================================================
# Helpers
# =============================================================================


def _descriptor(**overrides: Any) -> SimpleNamespace:
    defaults: dict[str, Any] = {
        "name": "my_job",
        "surface_hint": None,
        "requires_tty": False,
        "uses_live": False,
        "suppress_live": (),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _app_with_surface(setting: str | None = None) -> SimpleNamespace:
    class _Settings:
        def get(self, name: str, default: Any = None) -> Any:
            assert name == "tui.default_surface"
            return setting if setting is not None else default

    return SimpleNamespace(settings=_Settings())


def _standard_app() -> FunctualizeApp:
    return FunctualizeApp(
        "example",
        job_sources=JobSources(functions=[]),
        config_sources=ConfigSources(),
        plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
    )


# =============================================================================
# Gate unit tests
# =============================================================================


class TestWantsStdoutSurface:
    def test_uses_live_opens_the_gate(self) -> None:
        assert wants_stdout_surface(_app_with_surface(), _descriptor(), uses_live=True)

    def test_no_preference_keeps_gate_closed(self) -> None:
        """The regression fence: a plain job gets no surface."""
        assert not wants_stdout_surface(
            _app_with_surface(), _descriptor(), uses_live=False
        )

    def test_stdout_hint_opens_the_gate(self) -> None:
        assert wants_stdout_surface(
            _app_with_surface(), _descriptor(surface_hint="stdout"), uses_live=False
        )

    def test_panel_hint_is_ignored_on_direct_runs(self) -> None:
        assert not wants_stdout_surface(
            _app_with_surface(), _descriptor(surface_hint="panel"), uses_live=False
        )

    def test_stdout_setting_opens_the_gate(self) -> None:
        assert wants_stdout_surface(
            _app_with_surface("stdout"), _descriptor(), uses_live=False
        )

    def test_env_override_opens_the_gate(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The declared env setting opens the direct-run gate."""
        monkeypatch.chdir(tmp_path)  # no project config layers interfering
        monkeypatch.setenv("FUNCTUALIZE_TUI_DEFAULT_SURFACE", "stdout")
        app = _standard_app()
        assert app.settings.get("tui.default_surface") == "stdout"
        assert wants_stdout_surface(app, _descriptor(), uses_live=False)

    def test_the_setting_is_active_without_shell_registration(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A direct run reads the declaration even without TUI registration."""
        from functualize._cli.data.func_settings import _BASE_SETTINGS

        assert not any(s.name == "tui.default_surface" for s in _BASE_SETTINGS)
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".functualize.toml").write_text(
            '[tui]\ndefault_surface = "stdout"\n'
        )
        app = _standard_app()
        assert wants_stdout_surface(app, _descriptor(), uses_live=False)

    def test_requires_tty_outranks_stdout_preference(self) -> None:
        """HARD rung wins: an EXCLUSIVE job never gets a StdoutSurface."""
        assert not wants_stdout_surface(
            _app_with_surface("stdout"),
            _descriptor(surface_hint="stdout", requires_tty=True),
            uses_live=False,
        )

    def test_hint_beats_absent_setting_and_never_raises(self) -> None:
        class _ExplodingSettings:
            def get(self, name: str, default: Any = None) -> Any:
                raise RuntimeError("settings unavailable")

        app = SimpleNamespace(settings=_ExplodingSettings())
        assert not wants_stdout_surface(app, _descriptor(), uses_live=False)
        assert wants_stdout_surface(
            app, _descriptor(surface_hint="stdout"), uses_live=False
        )

    def test_none_descriptor_is_tolerated(self) -> None:
        assert not wants_stdout_surface(_app_with_surface(), None, uses_live=False)

    def test_eligible_ambient_opens_the_gate(self) -> None:
        with patch(
            "functualize._engine.ambient.has_eligible_ambient", return_value=True
        ):
            assert wants_stdout_surface(
                _app_with_surface(), _descriptor(), uses_live=False
            )


# =============================================================================
# Command-path integration
# =============================================================================


class TestLazyCommandPath:
    """make_lazy_command consults the gate at invocation time."""

    def _run(self, descriptor_kwargs: dict[str, Any]) -> MagicMock:
        from functualize._types.descriptors import JobDescriptor
        from functualize.app.adapters.lazy_command import make_lazy_command

        descriptor = JobDescriptor(
            name="my_job",
            group=None,
            module_path="my.module",
            docstring="",
            config_fields=[],
            **descriptor_kwargs,
        )
        app = MagicMock()
        app.settings.get.return_value = None
        app.execution_engine.materialize_job.return_value = MagicMock()
        # A real JobResult, not a mock: the lazy path now hands its result to
        # the same boundary handler the eager path uses (so cold and warm agree
        # on exit codes), and any mock attribute reads as "the job raised".
        from functualize._engine.result import JobResult
        from functualize._types.enums import RunStatus

        app.execution_engine.run.return_value = JobResult(
            status=RunStatus.SUCCESS,
            return_value=None,
            duration_ms=0.0,
            job_name="my_job",
        )

        session = MagicMock()
        with patch("functualize.ui.stdout_live_session", session):
            command = make_lazy_command(descriptor, app, surface="app.cli")
            command.callback()
        return session

    def test_stdout_hint_pushes_surface(self) -> None:
        session = self._run({"surface_hint": "stdout"})
        session.assert_called_once()

    def test_no_preference_pushes_nothing(self) -> None:
        session = self._run({})
        session.assert_not_called()


class TestCreateJobCommandPath:
    """create_job_command consults the gate at invocation time."""

    def _run(self, descriptor: Any) -> MagicMock:
        from functualize._engine.executor import JobExecutionEngine
        from functualize.app.adapters.click_params import create_job_command

        def my_job() -> None:
            """A plain job."""

        app = MagicMock()
        app.settings.get.return_value = None
        engine = MagicMock(spec=JobExecutionEngine)
        # A real status, not a MagicMock attribute: `deliver_job_result` now
        # routes every status through `exit_code_for_status`, so a mock that
        # never says what it is simulating exits 1 rather than falling through
        # to 0. That fall-through was the trap D-6 removed, and this fixture is
        # a small instance of it — the test asserted surface behaviour while
        # silently modelling a run with no outcome.
        engine.run.return_value = MagicMock(exception=None, status=RunStatus.SUCCESS)
        app._execution_engine = engine
        app.execution_engine = engine
        app.get_job.return_value = descriptor

        session = MagicMock()
        with patch("functualize.ui.stdout_live_session", session):
            command = create_job_command("my_job", my_job, None, app)
            command()
        return session

    def test_stdout_hint_pushes_surface(self) -> None:
        session = self._run(_descriptor(surface_hint="stdout"))
        session.assert_called_once()

    def test_no_preference_pushes_nothing(self) -> None:
        session = self._run(_descriptor())
        session.assert_not_called()
