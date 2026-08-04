"""Tests for Shell interactivity (S2/T13): watchers/responders, pty, and sudo
(§B.4). Responders answer scripted prompts by writing to stdin.
"""

from __future__ import annotations

import re
import sys

import pytest

from functualize._engine.capabilities.shell import WiredShell
from functualize.job import FailingResponder, Responder, ShellError
from functualize.testing import FakeShell


@pytest.fixture
def sh() -> WiredShell:
    return WiredShell()


def _fake_sudo(tmp_path):
    """A fake `sudo` on PATH emulating ``sudo -S -p PROMPT [flag] cmd...``.

    Prints the ``-p`` prompt, reads the password from stdin, then execs the
    rest — enough to prove the password travelled over stdin and not argv.
    Returns the directory to prepend to PATH.
    """
    import stat

    fake_sudo = tmp_path / "sudo"
    fake_sudo.write_text(
        "#!/bin/sh\n"
        'printf "%s" "$3"\n'  # print the -p prompt
        "read pw\n"  # consume the password our responder writes
        "shift 3\n"  # drop -S -p PROMPT
        'if [ "$1" = "--preserve-env" ]; then shift; fi\n'
        'echo "pw=$pw"\n'
        'exec "$@"\n'
    )
    fake_sudo.chmod(fake_sudo.stat().st_mode | stat.S_IEXEC)
    return tmp_path


class _SecretCollector:
    """An interactive surface that answers, recording what it was asked."""

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.requests: list = []

    def collect(self, request):
        self.requests.append(request)
        from functualize._types.interactivity import PromptResponse

        return PromptResponse(value=self.answer)


def _prompt_over(collector):
    from functualize._engine.capabilities.prompt import Prompt

    return Prompt(_provider=collector)


class TestWatchers:
    def test_responder_answers_scripted_prompt(self, sh: WiredShell) -> None:
        # A script that prompts, reads a line, and echoes it back.
        script = 'printf "Name: "; read name; echo "hello $name"'
        r = sh(
            script,
            shell=True,
            watchers=[Responder(pattern="Name:", response="ada\n")],
        )
        assert "hello ada" in r.stdout

    def test_responder_regex_pattern(self, sh: WiredShell) -> None:
        script = 'printf "Continue? "; read a; echo "ans=$a"'
        r = sh(
            script,
            shell=True,
            watchers=[Responder(pattern=re.compile(r"Continue\?"), response="y\n")],
        )
        assert "ans=y" in r.stdout

    def test_responder_answers_prompt_on_stderr(self, sh: WiredShell) -> None:
        # Prompts commonly go to stderr; watchers must see both streams.
        script = 'printf "PW: " >&2; read pw; echo "got:$pw"'
        r = sh(
            script,
            shell=True,
            watchers=[Responder(pattern="PW:", response="s3cr3t\n")],
        )
        assert "got:s3cr3t" in r.stdout

    def test_failing_responder_aborts_on_sentinel(self, sh: WiredShell) -> None:
        # Output contains the sentinel → the command is killed and raises.
        script = 'echo "Sorry, try again"; sleep 5'
        with pytest.raises(ShellError) as exc:
            sh(
                script,
                shell=True,
                timeout=10,
                watchers=[
                    FailingResponder(
                        pattern="never", response="x\n", sentinel="Sorry, try again"
                    )
                ],
            )
        assert "sentinel" in exc.value.result.stderr

    def test_watcher_capture_still_works(self, sh: WiredShell) -> None:
        script = 'printf "Q: "; read a; echo "done"'
        r = sh(script, shell=True, watchers=[Responder(pattern="Q:", response="1\n")])
        assert r.returncode == 0
        assert "done" in r.stdout


@pytest.mark.skipif(sys.platform == "win32", reason="pty is POSIX-only")
class TestPty:
    def test_child_sees_a_tty(self, sh: WiredShell) -> None:
        r = sh(
            [sys.executable, "-c", "import sys; print(sys.stdin.isatty())"],
            pty=True,
        )
        assert "True" in r.stdout

    def test_pty_captures_output(self, sh: WiredShell) -> None:
        r = sh([sys.executable, "-c", "print('hello-pty')"], pty=True)
        assert "hello-pty" in r.stdout

    def test_pty_with_watcher(self, sh: WiredShell) -> None:
        prog = (
            "import sys; sys.stdout.write('Name: '); sys.stdout.flush(); "
            "n = sys.stdin.readline().strip(); print('hi', n)"
        )
        r = sh(
            [sys.executable, "-c", prog],
            pty=True,
            watchers=[Responder(pattern="Name:", response="grace\n")],
        )
        assert "hi grace" in r.stdout


class TestSudo:
    def test_sudo_requires_password(self, sh: WiredShell) -> None:
        """A precondition error, not a command failure — nothing ran.

        With no interactive surface to ask (T-S6b-4), the refusal is now
        *typed* and names both the config field and the env var that would set
        it, so a CI failure tells you how to fix it. Prompting here instead
        would hang: nothing in CI can answer.
        """
        from functualize._engine.missing_value import MissingValueError

        with pytest.raises(MissingValueError) as excinfo:
            sh.sudo(["true"])

        assert excinfo.value.field == "[shell] sudo_password"
        assert excinfo.value.env_var == "SHELL_SUDO_PASSWORD"

    def test_sudo_rejects_string_form(self, sh: WiredShell) -> None:
        with pytest.raises(ValueError, match="list command form"):
            sh.sudo("rm -rf /", password="x")  # type: ignore[arg-type]

    @pytest.mark.skipif(sys.platform == "win32", reason="fake sudo uses /bin/sh")
    def test_sudo_answers_password_without_leaking_it(self, tmp_path) -> None:
        import os

        sh = WiredShell(sudo_password="s3cr3t")
        path = f"{_fake_sudo(tmp_path)}{os.pathsep}{os.environ['PATH']}"
        r = sh.sudo(["echo", "done"], env={"PATH": path})

        assert "done" in r.stdout  # the wrapped command ran
        assert "pw=s3cr3t" in r.stdout  # the responder delivered the password
        assert "s3cr3t" not in r.command  # but it never entered the echoed argv

    @pytest.mark.skipif(sys.platform == "win32", reason="fake sudo uses /bin/sh")
    def test_a_prompted_password_is_handled_like_a_configured_one(
        self, tmp_path
    ) -> None:
        """T-S6b-4's point: prompting is a *source* for the secret, not a
        second code path.

        Once collected it goes through the same responder — reaching sudo's
        stdin and never the argv — so the masking guarantee cannot hold for the
        configured password and quietly fail for the typed one, which is the
        password more likely to be a real production credential.
        """
        import os

        collector = _SecretCollector("typed-pw")
        sh = WiredShell(prompt=_prompt_over(collector))
        path = f"{_fake_sudo(tmp_path)}{os.pathsep}{os.environ['PATH']}"

        r = sh.sudo(["echo", "done"], env={"PATH": path})

        assert "pw=typed-pw" in r.stdout  # collected, then delivered
        assert "typed-pw" not in r.command  # and still never in the argv

    @pytest.mark.skipif(sys.platform == "win32", reason="fake sudo uses /bin/sh")
    def test_the_sudo_prompt_is_masked(self, tmp_path) -> None:
        """A sudo password echoed to the screen while being typed is the
        classic shoulder-surf; SECRET_INPUT is what tells a surface to mask."""
        import os

        from functualize._types.interactivity import PromptIntent

        collector = _SecretCollector("typed-pw")
        path = f"{_fake_sudo(tmp_path)}{os.pathsep}{os.environ['PATH']}"

        WiredShell(prompt=_prompt_over(collector)).sudo(["true"], env={"PATH": path})

        assert collector.requests[0].intent is PromptIntent.SECRET_INPUT

    def test_sudo_password_resolved_from_shell_config(self) -> None:
        from unittest.mock import MagicMock

        from functualize._engine.executor import JobExecutionEngine
        from functualize._events.bus import EventBus
        from functualize._events.hooks import HookRegistry
        from functualize._types.redaction import MASK, Secret

        class _Chain:
            def resolve(self, key, section):
                assert section == "shell"
                value = "from-config" if key == "sudo_password" else None
                return type("R", (), {"value": value})()

        engine = JobExecutionEngine(
            di_registry=MagicMock(),
            hook_registry=HookRegistry(),
            middleware_chain=MagicMock(has_middleware=False),
            event_bus=EventBus(),
            resolution_chain=_Chain(),
        )
        pw = engine._resolve_sudo_password()
        assert isinstance(pw, Secret)
        assert pw.get_secret_value() == "from-config"
        assert str(pw) == MASK  # never leaks through an f-string

    def test_fake_shell_sudo_prepends_and_records(self) -> None:
        from functualize.job import ShellResult

        fake = FakeShell(
            {"sudo systemctl restart nginx": ShellResult(0, "", "", "", 1.0)}
        )
        r = fake.sudo(["systemctl", "restart", "nginx"], password="ignored")
        assert r.returncode == 0
        assert fake.calls[0].command == "sudo systemctl restart nginx"
