"""Tests for the Shell capability core (S2/T8): command forms + injection
safety, capture, check, and the FakeShell test double.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock

import pytest

from functualize._engine.capabilities.shell import WiredShell
from functualize._engine.executor import JobExecutionEngine
from functualize._events.bus import EventBus
from functualize._events.hooks import HookRegistry
from functualize.job import Shell, ShellError, ShellResult
from functualize.testing import FakeShell


@pytest.fixture
def sh() -> WiredShell:
    return WiredShell()


class TestCommandForms:
    def test_list_form_runs_without_shell(self, sh: WiredShell) -> None:
        r = sh(["echo", "hello world"])
        assert r.returncode == 0
        assert r.stdout.strip() == "hello world"
        assert r.command == "echo 'hello world'"

    def test_template_form_auto_quotes(self, sh: WiredShell) -> None:
        # A value with shell metacharacters must survive as a single argument.
        r = sh("echo {msg}", msg="a b; rm -rf /")
        assert r.stdout.strip() == "a b; rm -rf /"

    def test_raw_form_requires_shell_true(self, sh: WiredShell) -> None:
        r = sh("echo hi | tr a-z A-Z", shell=True)
        assert r.stdout.strip() == "HI"

    def test_bare_raw_string_is_error(self, sh: WiredShell) -> None:
        with pytest.raises(ValueError, match="require shell=True"):
            sh("echo hi; echo bye")

    def test_non_str_non_list_rejected(self, sh: WiredShell) -> None:
        with pytest.raises(ValueError, match="must be a list or str"):
            sh(123)  # type: ignore[arg-type]


class TestCheckAndCapture:
    def test_check_raises_on_nonzero(self, sh: WiredShell) -> None:
        with pytest.raises(ShellError) as exc:
            sh(["false"])
        assert exc.value.result.returncode != 0

    def test_check_false_returns_result(self, sh: WiredShell) -> None:
        r = sh(["false"], check=False)
        assert r.returncode != 0
        assert r.ok is False

    def test_capture_false_yields_empty_streams(self, sh: WiredShell) -> None:
        r = sh(["true"], capture=False)
        assert r.stdout == ""
        assert r.returncode == 0

    def test_cwd_is_honored(self, sh: WiredShell, tmp_path) -> None:
        (tmp_path / "marker.txt").write_text("x")
        r = sh(["ls"], cwd=str(tmp_path))
        assert "marker.txt" in r.stdout

    def test_env_merge(self, sh: WiredShell) -> None:
        r = sh("echo {v}", v="$MYVAR", shell=False)  # literal, not expanded
        assert r.stdout.strip() == "$MYVAR"
        r2 = sh('printf "%s" "$MYVAR"', shell=True, env={"MYVAR": "hello"})
        assert r2.stdout == "hello"

    def test_missing_executable_is_shell_error(self, sh: WiredShell) -> None:
        with pytest.raises(ShellError):
            sh(["this-command-does-not-exist-xyz"])


class TestStreamingAndIO:
    def test_stream_tees_with_capture(self, sh: WiredShell) -> None:
        chunks: list[str] = []
        r = sh(["printf", "a\nb\nc\n"], stream=chunks.append)
        # captured in full AND streamed live
        assert r.stdout == "a\nb\nc\n"
        assert "".join(chunks) == "a\nb\nc\n"

    def test_stream_without_capture_still_streams(self, sh: WiredShell) -> None:
        chunks: list[str] = []
        r = sh(["printf", "x\ny\n"], stream=chunks.append, capture=False)
        assert r.stdout == ""  # not captured
        assert "".join(chunks) == "x\ny\n"  # but streamed

    def test_stream_reports_returncode(self, sh: WiredShell) -> None:
        r = sh(["false"], stream=lambda _c: None, check=False)
        assert r.returncode != 0

    def test_in_stream_feeds_stdin(self, sh: WiredShell) -> None:
        r = sh(["cat"], in_stream="piped input\n")
        assert r.stdout == "piped input\n"

    def test_in_stream_with_streaming(self, sh: WiredShell) -> None:
        chunks: list[str] = []
        r = sh(["cat"], in_stream="hello\n", stream=chunks.append)
        assert "".join(chunks) == "hello\n"
        assert r.stdout == "hello\n"


class TestShellProgram:
    def test_default_program_is_platform_shell(self, sh: WiredShell) -> None:
        r = sh("echo one two | wc -w", shell=True)
        assert r.stdout.strip() == "2"

    def test_program_override(self) -> None:
        import shutil

        bash = shutil.which("bash")
        if bash is None:
            pytest.skip("bash not available")
        sh = WiredShell(program=bash)
        # bash-specific: brace expansion proves the configured shell ran it.
        r = sh("echo {1..3}", shell=True)
        assert r.stdout.strip() == "1 2 3"

    def test_resolve_shell_program_from_config(self) -> None:
        from functualize._engine.executor import JobExecutionEngine

        class _Chain:
            def resolve(self, key, section):
                assert (key, section) == ("program", "shell")
                return type("R", (), {"value": "/bin/bash"})()

        engine = JobExecutionEngine(
            di_registry=MagicMock(),
            hook_registry=HookRegistry(),
            middleware_chain=MagicMock(has_middleware=False),
            event_bus=EventBus(),
            resolution_chain=_Chain(),
        )
        assert engine._resolve_shell_program() == "/bin/bash"

    def test_resolve_shell_program_none_without_chain(self) -> None:
        from functualize._engine.executor import JobExecutionEngine

        engine = JobExecutionEngine(
            di_registry=MagicMock(),
            hook_registry=HookRegistry(),
            middleware_chain=MagicMock(has_middleware=False),
            event_bus=EventBus(),
        )
        assert engine._resolve_shell_program() is None


class TestTimeoutAndRetry:
    def test_timeout_kills_and_raises(self, sh: WiredShell) -> None:
        import time as _t

        start = _t.perf_counter()
        with pytest.raises(ShellError) as exc:
            sh(["sleep", "10"], timeout=0.3)
        assert exc.value.result.returncode == 124
        assert _t.perf_counter() - start < 5  # killed promptly, not after 10s

    def test_timeout_raises_even_with_check_false(self, sh: WiredShell) -> None:
        with pytest.raises(ShellError):
            sh(["sleep", "10"], timeout=0.3, check=False)

    def test_retry_reruns_failing_command(self, sh: WiredShell) -> None:
        from functualize._types.job_declaration import Retry

        r = sh(
            ["false"],
            retry=Retry(attempts=2, backoff="constant"),
            check=False,
        )
        assert r.returncode != 0  # still fails after exhausting attempts

    def test_retry_on_exit_codes_filters(self, sh: WiredShell) -> None:
        from functualize._types.job_declaration import Retry

        # exit 1 not in on_exit_codes → no retry; returns immediately with 1
        r = sh(
            ["false"],
            retry=Retry(attempts=3, backoff="constant", on_exit_codes=(2,)),
            check=False,
        )
        assert r.returncode == 1

    def test_retry_succeeds_eventually(self, sh: WiredShell, tmp_path) -> None:
        from functualize._types.job_declaration import Retry

        # A command that fails until a marker file exists, created after first try.
        marker = tmp_path / "ok"
        script = f"if [ -f {marker} ]; then exit 0; else touch {marker}; exit 1; fi"
        r = sh(script, shell=True, retry=Retry(attempts=3, backoff="constant"))
        assert r.returncode == 0


class TestCdAndPrefix:
    def test_cd_changes_directory(self, sh: WiredShell, tmp_path) -> None:
        (tmp_path / "marker.txt").write_text("x")
        with sh.cd(str(tmp_path)):
            assert "marker.txt" in sh(["ls"]).stdout

    def test_cd_nests_relatively(self, sh: WiredShell, tmp_path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "inner.txt").write_text("x")
        with sh.cd(str(tmp_path)), sh.cd("sub"):
            assert "inner.txt" in sh(["ls"]).stdout

    def test_cd_restored_after_block(self, sh: WiredShell, tmp_path) -> None:
        with sh.cd(str(tmp_path)):
            pass
        # after the block the stack is empty again
        assert sh._cd_stack == []

    def test_prefix_list(self, sh: WiredShell) -> None:
        with sh.prefix(["echo"]):
            assert sh(["hello"]).stdout.strip() == "hello"

    def test_prefix_string(self, sh: WiredShell) -> None:
        with sh.prefix("echo"):
            assert sh(["world"]).stdout.strip() == "world"

    def test_prefix_nests(self, sh: WiredShell) -> None:
        with sh.prefix(["env"]), sh.prefix(["echo"]):
            # env echo hi → echo runs hi
            assert sh(["hi"]).stdout.strip() == "hi"

    def test_per_call_cwd_overrides_cd(self, sh: WiredShell, tmp_path) -> None:
        other = tmp_path / "other"
        other.mkdir()
        (other / "z.txt").write_text("x")
        with sh.cd(str(tmp_path)):
            assert "z.txt" in sh(["ls"], cwd=str(other)).stdout


class TestProtocolConformance:
    def test_wired_shell_is_a_shell(self, sh: WiredShell) -> None:
        assert isinstance(sh, Shell)

    def test_fake_shell_is_a_shell(self) -> None:
        assert isinstance(FakeShell(), Shell)


class TestFakeShell:
    def test_answers_exact_string(self) -> None:
        fake = FakeShell(
            {
                "git rev-parse HEAD": ShellResult(
                    0, "abc123\n", "", "git rev-parse HEAD", 1.0
                )
            }
        )
        r = fake(["git", "rev-parse", "HEAD"])
        assert r.stdout == "abc123\n"

    def test_answers_regex(self) -> None:
        fake = FakeShell(
            {
                re.compile(r"docker build .*"): ShellResult(
                    0, "", "", "docker build", 1.0
                )
            }
        )
        r = fake("docker build -t app .")
        assert r.returncode == 0

    def test_records_calls(self) -> None:
        fake = FakeShell({"a b": ShellResult(0, "", "", "a b", 1.0)})
        fake(["a", "b"], check=False, cwd="/tmp")
        assert fake.calls[0].argv == ["a", "b"]
        assert fake.calls[0].command == "a b"
        assert fake.calls[0].kwargs["cwd"] == "/tmp"

    def test_loud_on_unexpected(self) -> None:
        fake = FakeShell({"known": ShellResult(0, "", "", "known", 1.0)})
        with pytest.raises(AssertionError, match="unexpected command"):
            fake(["unknown"])

    def test_honors_check(self) -> None:
        fake = FakeShell({"boom": ShellResult(3, "", "bad", "boom", 1.0)})
        with pytest.raises(ShellError):
            fake(["boom"])
        assert fake(["boom"], check=False).returncode == 3


class TestDIInjection:
    """The engine injects a working Shell for a `sh: Shell` job parameter."""

    def _engine(self) -> JobExecutionEngine:
        di_registry = MagicMock()
        di_registry.available_types.return_value = set()
        middleware_chain = MagicMock()
        middleware_chain.has_middleware = False
        return JobExecutionEngine(
            di_registry=di_registry,
            hook_registry=HookRegistry(),
            middleware_chain=middleware_chain,
            event_bus=EventBus(),
        )

    def test_shell_is_injected_and_runs(self) -> None:
        captured: dict[str, object] = {}

        def my_job(sh: Shell) -> str:
            captured["sh"] = sh
            return sh(["echo", "injected"]).stdout.strip()

        engine = self._engine()
        result = engine.execute("my_job", my_job, kwargs={})

        assert isinstance(captured["sh"], Shell)
        assert isinstance(captured["sh"], WiredShell)
        assert result.return_value == "injected"
