"""C1b.3 — the `!` shell mode.

The happy path (`!ls` runs, history records) is the easy half. The half that
actually protects anything is the refusals: a busy worker and a missing
terminal must both stop the command *before* it is handed off.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from functualize._cli.tui.shell_mode import (
    ASK_SIGIL,
    HISTORY_NAMESPACE,
    SHELL_SIGIL,
    execute_shell_handoff,
    make_ask_mode,
    make_shell_mode,
    register_shell_mode,
    run_shell_command,
    shell_candidates,
)
from functualize.plugin import DEFAULT_SIGIL, InputMode, InputModeRegistry


class _FakeLog:
    """Stands in for the RichLog — records what the user would have seen."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def add_class(self, name: str) -> None:  # noqa: ARG002
        pass

    def write(self, text: str) -> None:
        self.lines.append(text)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


class _FakeSuspend:
    def __init__(self, recorder: list[str]) -> None:
        self._recorder = recorder

    def __enter__(self) -> None:
        self._recorder.append("suspended")

    def __exit__(self, *exc: object) -> bool:
        self._recorder.append("resumed")
        return False


class _FakeApp:
    """The narrowest thing `run_shell_command` actually touches."""

    def __init__(self) -> None:
        self.output = _FakeLog()
        self.events: list[str] = []
        self.workers: list[Any] = []
        self.handoffs: list[list[str]] = []
        self.log = self  # app.log.warning(...)
        self.warnings: list[str] = []
        self._settings_store = self

    # app.log.warning
    def warning(self, msg: str) -> None:
        self.warnings.append(msg)

    # settings store
    def effective_values(self) -> dict[str, str]:
        return {}

    def query_one(self, selector: str, widget_type: object = None) -> _FakeLog:  # noqa: ARG002
        return self.output

    def suspend(self) -> _FakeSuspend:
        return _FakeSuspend(self.events)

    def request_handoff(self, tokens: list[str]) -> None:
        self.handoffs.append(list(tokens))


class _RunningWorker:
    name = "cmd-exec"
    is_running = True


@pytest.fixture
def app() -> _FakeApp:
    return _FakeApp()


@pytest.fixture
def tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend we own a real terminal.

    Patches `isatty` on the existing streams rather than replacing them:
    pytest writes its own output through `sys.stdout`, so swapping the object
    out breaks the reporter before the assertion is ever reached.
    """
    import sys

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)


class TestRegistration:
    def test_mode_registers_under_its_sigil(self, app: _FakeApp) -> None:
        reg = InputModeRegistry()
        register_shell_mode(app, reg)
        assert SHELL_SIGIL in reg
        assert reg.get(SHELL_SIGIL).name == "shell"

    def test_registration_is_idempotent(self, app: _FakeApp) -> None:
        """A relaunch must not crash on the registry's duplicate-sigil guard."""
        reg = InputModeRegistry()
        register_shell_mode(app, reg)
        register_shell_mode(app, reg)
        assert len(reg) == 2  # `!` and the reserved `?`


class TestReservedAskMode:
    """C1b.4 — `?` is claimed before it is built."""

    def test_ask_sigil_is_registered(self, app: _FakeApp) -> None:
        reg = InputModeRegistry()
        register_shell_mode(app, reg)
        assert ASK_SIGIL in reg
        assert reg.get(ASK_SIGIL).name == "ask"

    def test_reserved_mode_resolves(self, app: _FakeApp) -> None:
        reg = InputModeRegistry()
        register_shell_mode(app, reg)
        assert reg.resolve("?what is this").name == "ask"

    def test_using_it_raises_rather_than_silently_doing_nothing(self) -> None:
        """A slot that no-op'd would look like a feature that ignores you."""
        mode = make_ask_mode()
        with pytest.raises(NotImplementedError, match="reserved"):
            mode.submit("what is this")
        with pytest.raises(NotImplementedError, match="reserved"):
            mode.candidate_source("what", 4)

    def test_it_is_never_submittable_from_the_ui(self) -> None:
        """`is_ready` False is what keeps the TUI from hitting that raise."""
        assert make_ask_mode().is_ready("anything") is False

    def test_reservation_blocks_a_later_claim(self, app: _FakeApp) -> None:
        reg = InputModeRegistry()
        register_shell_mode(app, reg)
        with pytest.raises(ValueError, match="already registered"):
            reg.register(
                InputMode(
                    sigil=ASK_SIGIL,
                    name="something-else",
                    candidate_source=lambda t, c: [],
                    is_ready=lambda t: True,
                    submit=lambda t: None,
                    history_namespace="x",
                )
            )

    def test_bang_text_resolves_to_shell_not_command(self, app: _FakeApp) -> None:
        reg = InputModeRegistry()
        reg.register(
            InputMode(
                sigil=DEFAULT_SIGIL,
                name="command",
                candidate_source=lambda t, c: [],
                is_ready=lambda t: True,
                submit=lambda t: None,
                history_namespace="command",
            )
        )
        register_shell_mode(app, reg)
        assert reg.resolve("!ls -la").name == "shell"
        assert reg.resolve("deploy").name == "command"

    def test_history_namespace_is_distinct(self, app: _FakeApp) -> None:
        """`!ls` must not pollute job-argument history."""
        assert make_shell_mode(app).history_namespace == HISTORY_NAMESPACE

    def test_bare_sigil_is_not_ready(self, app: _FakeApp) -> None:
        mode = make_shell_mode(app)
        assert mode.is_ready("") is False
        assert mode.is_ready("   ") is False
        assert mode.is_ready("ls") is True


def _inserted(items: list[Any]) -> set[str]:
    """What each candidate would actually type into the bar.

    Read `.value`, not `.main`: `main` is styled `Content` carrying a source
    badge, while `value` is the insertion contract — the thing the user ends up
    with. Asserting on the display text would couple these tests to badge
    formatting.
    """
    return {c.value for c in items}


class TestCandidates:
    def test_first_token_offers_executables(self) -> None:
        """`ls` lives on $PATH in any environment that can run this suite."""
        assert any(n.startswith("l") for n in _inserted(shell_candidates("l", 1)))

    def test_later_tokens_offer_paths(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "target.txt").write_text("x")
        assert any("target.txt" in n for n in _inserted(shell_candidates("cat tar", 7)))

    def test_executables_are_not_offered_after_the_first_token(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "zzz_unique_file").write_text("x")
        names = _inserted(shell_candidates("cat zzz", 7))
        assert names
        assert all("zzz" in n for n in names)

    def test_candidates_are_the_widget_type_not_the_stand_in(self) -> None:
        """Regression: the `!` mode used to return `engine.DropdownItem`.

        That class documents itself as a structural stand-in; handing it to the
        mounted widget raises `VisualError: unable to display 'DropdownItem'
        type` and takes the whole shell down. Caught only by running the real
        TUI, which is why the example's acceptance requires a live check.
        """
        from functualize._cli.completions.engine import (
            DropdownItem as StandInDropdownItem,
        )

        items = shell_candidates("l", 1)
        assert items
        assert not any(isinstance(i, StandInDropdownItem) for i in items)
        # The real item separates display from insertion; the stand-in cannot.
        assert all(hasattr(i, "value") for i in items)


class TestRefusals:
    """The half that matters. Both must refuse *before* suspending."""

    def test_busy_worker_refuses_the_command(self, app: _FakeApp, tty: None) -> None:
        """Design-scrutiny D-02: `!` honours the same single-worker guard.

        Two terminal owners is exactly what the EXCLUSIVE contract prevents,
        and a fresh submit path is where that guard gets forgotten.
        """
        app.workers = [_RunningWorker()]
        run_shell_command(app, "ls")

        assert "suspended" not in app.events, "suspended the TUI despite a busy worker"
        assert "Busy" in app.output.text
        assert any("already running" in w for w in app.warnings)

    def test_non_tty_refuses_rather_than_hanging(
        self, app: _FakeApp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The orchestrator's capability floor: EXCLUSIVE needs a real terminal."""
        import sys

        monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
        run_shell_command(app, "ls")

        assert "suspended" not in app.events, "suspended with no terminal to hand over"
        assert "needs a real terminal" in app.output.text

    def test_empty_command_is_a_noop(self, app: _FakeApp, tty: None) -> None:
        run_shell_command(app, "   ")
        assert app.events == []
        assert app.output.lines == []


class TestHandoff:
    """Execution goes through the orchestrator, not `App.suspend()`.

    The first implementation suspended the TUI, following the builtin path.
    Live verification showed Textual raises `SuspendNotSupported` in inline
    mode, so every `!` command reported failure. The EXCLUSIVE handoff — the
    same route a `tty: TTY` job takes — is what the task specified all along.
    """

    def test_submit_requests_a_handoff(self, app: _FakeApp, tty: None) -> None:
        run_shell_command(app, "echo hi")
        assert app.handoffs == [[SHELL_SIGIL, "echo hi"]]

    def test_the_shell_is_not_suspended(self, app: _FakeApp, tty: None) -> None:
        """`App.suspend()` is unsupported in inline mode — never call it."""
        run_shell_command(app, "echo hi")
        assert app.events == []

    def test_the_sentinel_cannot_collide_with_a_job(self) -> None:
        """C1b.4's reservation is what makes `!` safe as a handoff kind."""
        from functualize._types.naming import RESERVED_SIGILS

        assert SHELL_SIGIL in RESERVED_SIGILS

    def test_busy_worker_requests_no_handoff(self, app: _FakeApp, tty: None) -> None:
        app.workers = [_RunningWorker()]
        run_shell_command(app, "echo hi")
        assert app.handoffs == []

    def test_non_tty_requests_no_handoff(
        self, app: _FakeApp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sys

        monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
        run_shell_command(app, "echo hi")
        assert app.handoffs == []


class TestHandoffExecution:
    """`execute_shell_handoff` runs after the TUI has exited."""

    def test_a_real_command_runs_and_reports_its_code(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert execute_shell_handoff(None, "true") == 0
        assert execute_shell_handoff(None, "false") != 0

    def test_it_records_history(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not `argument_history` — that store is per-job-per-field shaped."""
        monkeypatch.chdir(tmp_path)
        execute_shell_handoff(None, "true")

        from functualize.app.utils import StateStore

        history = StateStore.for_project(tmp_path).get_history()
        assert len(history) == 1
        assert history[0]["command"] == "true"
        assert history[0]["namespace"] == HISTORY_NAMESPACE
        assert history[0]["exit_code"] == 0
        assert history[0]["argv"] == ["true"]

    def test_history_failure_does_not_fail_the_command(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)

        def _boom(*a: object, **k: object) -> None:
            raise OSError("read-only filesystem")

        monkeypatch.setattr("functualize.app.utils.StateStore.for_project", _boom)
        assert execute_shell_handoff(None, "true") == 0

    def test_the_handoff_loop_routes_the_sentinel(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`_run_handoff` must recognise `!` before treating it as a job name."""
        from functualize._cli import inline_tui

        seen: list[str] = []
        monkeypatch.setattr(
            "functualize._cli.tui.shell_mode.execute_shell_handoff",
            lambda app, cmd: (seen.append(cmd), 0)[1],
        )
        inline_tui._run_handoff(object(), [SHELL_SIGIL, "echo hi"])
        assert seen == ["echo hi"]
