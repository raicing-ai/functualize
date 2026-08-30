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

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from functualize.app.adapters.surface_gate import wants_stdout_surface

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


class _NoSettingsStore:
    """FuncSettingsStore stand-in stating no preference."""

    @classmethod
    def discover(cls, *args: Any, **kwargs: Any) -> _NoSettingsStore:
        return cls()

    def effective_values(self) -> dict[str, str]:
        return {}


class _StdoutSettingsStore(_NoSettingsStore):
    """FuncSettingsStore stand-in with tui.default_surface = stdout."""

    def effective_values(self) -> dict[str, str]:
        return {"tui.default_surface": "stdout"}


def _patch_settings(store: type) -> Any:
    return patch("functualize._cli.data.func_settings.FuncSettingsStore", store)


# =============================================================================
# Gate unit tests
# =============================================================================


class TestWantsStdoutSurface:
    def test_uses_live_opens_the_gate(self) -> None:
        with _patch_settings(_NoSettingsStore):
            assert wants_stdout_surface(object(), _descriptor(), uses_live=True)

    def test_no_preference_keeps_gate_closed(self) -> None:
        """The regression fence: a plain job gets no surface."""
        with _patch_settings(_NoSettingsStore):
            assert not wants_stdout_surface(object(), _descriptor(), uses_live=False)

    def test_stdout_hint_opens_the_gate(self) -> None:
        with _patch_settings(_NoSettingsStore):
            assert wants_stdout_surface(
                object(), _descriptor(surface_hint="stdout"), uses_live=False
            )

    def test_panel_hint_is_ignored_on_direct_runs(self) -> None:
        with _patch_settings(_NoSettingsStore):
            assert not wants_stdout_surface(
                object(), _descriptor(surface_hint="panel"), uses_live=False
            )

    def test_stdout_setting_opens_the_gate(self) -> None:
        with _patch_settings(_StdoutSettingsStore):
            assert wants_stdout_surface(object(), _descriptor(), uses_live=False)

    def test_env_override_opens_the_gate(self, monkeypatch: Any, tmp_path: Any) -> None:
        """FUNCTUALIZE_TUI_DEFAULT_SURFACE=stdout flows through the real
        settings store's env layer."""
        monkeypatch.chdir(tmp_path)  # no project config layers interfering
        monkeypatch.setenv("FUNCTUALIZE_TUI_DEFAULT_SURFACE", "stdout")
        assert wants_stdout_surface(object(), _descriptor(), uses_live=False)

    def test_requires_tty_outranks_stdout_preference(self) -> None:
        """HARD rung wins: an EXCLUSIVE job never gets a StdoutSurface."""
        with _patch_settings(_StdoutSettingsStore):
            assert not wants_stdout_surface(
                object(),
                _descriptor(surface_hint="stdout", requires_tty=True),
                uses_live=False,
            )

    def test_hint_beats_absent_setting_and_never_raises(self) -> None:
        class _ExplodingStore:
            @classmethod
            def discover(cls, *args: Any, **kwargs: Any) -> Any:
                raise RuntimeError("settings unavailable")

        with _patch_settings(_ExplodingStore):
            # Settings failure collapses to "no preference"...
            assert not wants_stdout_surface(object(), _descriptor(), uses_live=False)
            # ...but the hint rung still works.
            assert wants_stdout_surface(
                object(), _descriptor(surface_hint="stdout"), uses_live=False
            )

    def test_none_descriptor_is_tolerated(self) -> None:
        with _patch_settings(_NoSettingsStore):
            assert not wants_stdout_surface(object(), None, uses_live=False)

    def test_eligible_ambient_opens_the_gate(self) -> None:
        with patch(
            "functualize._engine.ambient.has_eligible_ambient", return_value=True
        ):
            assert wants_stdout_surface(object(), _descriptor(), uses_live=False)


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
        app.execution_engine.materialize_job.return_value = MagicMock()
        # A real JobResult, not a mock: the lazy path now hands its result to
        # the same boundary handler the eager path uses (so cold and warm agree
        # on exit codes), and any mock attribute reads as "the job raised".
        from functualize._engine.result import JobResult
        from functualize._types.enums import RunStatus

        app.execution_engine.execute.return_value = JobResult(
            status=RunStatus.SUCCESS,
            return_value=None,
            duration_ms=0.0,
            job_name="my_job",
        )

        session = MagicMock()
        with (
            _patch_settings(_NoSettingsStore),
            patch("functualize.ui.stdout_live_session", session),
        ):
            command = make_lazy_command(descriptor, app)
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
        engine = MagicMock(spec=JobExecutionEngine)
        engine.execute.return_value = MagicMock(exception=None)
        app._execution_engine = engine
        app.execution_engine = engine
        app.get_job.return_value = descriptor

        session = MagicMock()
        with (
            _patch_settings(_NoSettingsStore),
            patch("functualize.ui.stdout_live_session", session),
        ):
            command = create_job_command("my_job", my_job, None, app)
            command()
        return session

    def test_stdout_hint_pushes_surface(self) -> None:
        session = self._run(_descriptor(surface_hint="stdout"))
        session.assert_called_once()

    def test_no_preference_pushes_nothing(self) -> None:
        session = self._run(_descriptor())
        session.assert_not_called()
