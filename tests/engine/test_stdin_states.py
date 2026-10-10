"""What a ``Stdin`` parameter receives from stdin, per real plumbing state.

Every state here is driven through a real pipe or a real device — no mocks —
because the question the feature answers is precisely about what plumbing
does: "nothing was piped" and "an empty stream was piped" are different facts
about the same command line, and a mock would only restate the implementation.
The one timing bound is the wall clock on the never-written pipe; everything
else asserts the value the job receives.

Both doors — ``Stdin`` parameter resolution and the prompt collector — are
pinned per state in :class:`TestBothDoorsAgree` so they agree rather than
contradict (acceptance criterion 4).
"""

from __future__ import annotations

import io
import os
import sys
import time
from typing import TYPE_CHECKING, Any

import pytest

from functualize._engine.capabilities.stdin_collector import StdinCollector
from functualize._engine.stdin_reader import (
    StdinState,
    resolve_stdin_params,
    stdin_state,
)
from functualize._types.cli_markers import Stdin

if TYPE_CHECKING:
    from collections.abc import Iterator

# The motivating command pipes `sleep 30`: a blocking read would show up as
# ~30s, the probe as microseconds. One second is both generous and damning.
WALL_CLOCK_BOUND_S = 1.0


class _Pipe:
    """A real stdin: the read end of an ``os.pipe()``, write end owned."""

    def __init__(self) -> None:
        read_fd, self.write_fd = os.pipe()
        self.file = os.fdopen(read_fd, "r", encoding="utf-8")
        self._writer_closed = False

    def write(self, data: str) -> None:
        os.write(self.write_fd, data.encode("utf-8"))

    def close_writer(self) -> None:
        if not self._writer_closed:
            self._writer_closed = True
            os.close(self.write_fd)


class _FakeTty:
    """stdin as a terminal: the only thing a TTY verdict reads is ``isatty``."""

    def isatty(self) -> bool:
        return True


@pytest.fixture
def pipe_stdin(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Install a real pipe as ``sys.stdin``; writer held open until teardown."""
    pipes: list[_Pipe] = []

    def install() -> _Pipe:
        pipe = _Pipe()
        pipes.append(pipe)
        monkeypatch.setattr("sys.stdin", pipe.file)
        return pipe

    yield install
    for pipe in pipes:
        pipe.close_writer()
        pipe.file.close()


class TestNothingWasPiped:
    """A terminal and a pipe that is never written both keep the default."""

    def test_a_terminal_keeps_the_default(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("sys.stdin", _FakeTty())
        assert stdin_state() is StdinState.TTY
        assert resolve_stdin_params({"data": Stdin()}, {}) == {}

    def test_a_never_written_pipe_keeps_the_default_without_waiting(
        self, pipe_stdin: Any
    ):
        pipe = pipe_stdin()  # writer held open, never written
        started = time.monotonic()
        assert resolve_stdin_params({"data": Stdin()}, {}) == {}
        elapsed = time.monotonic() - started
        assert stdin_state(pipe.file) is StdinState.NO_INPUT
        pipe.close_writer()
        assert elapsed < WALL_CLOCK_BOUND_S, (
            f"resolution waited {elapsed:.2f}s for a pipe that is never written"
        )


class TestAnEmptyStreamWasPiped:
    """An empty-but-present stream is a document: it deposits ``""``."""

    def test_a_closed_empty_pipe_deposits_the_empty_string(self, pipe_stdin: Any):
        pipe = pipe_stdin()
        pipe.close_writer()
        assert stdin_state() is StdinState.READY
        assert resolve_stdin_params({"data": Stdin()}, {}) == {"data": ""}

    def test_dev_null_deposits_the_empty_string(self, monkeypatch: pytest.MonkeyPatch):
        with open(os.devnull, encoding="utf-8") as devnull:
            monkeypatch.setattr("sys.stdin", devnull)
            assert resolve_stdin_params({"data": Stdin()}, {}) == {"data": ""}


class TestDataArrivesIntact:
    """Acceptance criterion 3: content is deposited whole."""

    @pytest.mark.parametrize(
        "content",
        ["line1\nline2\nline3\n", "héllo wörld ✓ — ünïcode\n", "a\tb\n", "\n"],
        ids=["multi-line", "multi-byte", "whitespace", "single-newline"],
    )
    def test_content_is_deposited_whole(self, pipe_stdin: Any, content: str):
        pipe = pipe_stdin()
        pipe.write(content)
        pipe.close_writer()
        assert resolve_stdin_params({"data": Stdin()}, {}) == {"data": content}


class TestStreamingKeepsItsContract:
    """The iterator-typed parameter is the documented opt-in to waiting."""

    def test_an_iterator_param_streams_on_a_never_written_pipe(self, pipe_stdin: Any):
        pipe = pipe_stdin()
        started = time.monotonic()
        resolved = resolve_stdin_params(
            {"rows": Stdin()}, {}, streaming=frozenset({"rows"})
        )
        elapsed = time.monotonic() - started
        assert "rows" in resolved and resolved["rows"] is not None
        pipe.close_writer()
        assert elapsed < WALL_CLOCK_BOUND_S

    def test_an_iterator_param_is_not_deposited_on_a_terminal(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr("sys.stdin", _FakeTty())
        resolved = resolve_stdin_params(
            {"rows": Stdin()}, {}, streaming=frozenset({"rows"})
        )
        assert resolved == {}


class TestUnprobeableStreamsKeepTheEagerRule:
    """fd-less streams (test doubles) have no readiness: the read decides."""

    @pytest.mark.parametrize(
        ("content", "expected"),
        [("data", {"data": "data"}), ("", {"data": ""})],
        ids=["with-content", "empty"],
    )
    def test_an_fdless_stream_reads_as_before(
        self, monkeypatch: pytest.MonkeyPatch, content: str, expected: dict
    ):
        monkeypatch.setattr("sys.stdin", io.StringIO(content))
        assert stdin_state() is StdinState.READY
        assert resolve_stdin_params({"data": Stdin()}, {}) == expected


class TestBothDoorsAgree:
    """Acceptance criterion 4: one classification, two projections.

    The parameter door deposits the parameter's default / ``""`` / data; the
    prompt door prompts at a terminal and stays unavailable everywhere else
    (``default`` / ``InputNotAvailable``). Each row fixes both verdicts per
    state, so changing one door without the other fails here rather than
    contradicting in production.
    """

    @staticmethod
    def _tty_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
        # A TTY verdict needs both halves; stdout's half is not under test.
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    def test_a_terminal_prompts_and_deposits_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr("sys.stdin", _FakeTty())
        self._tty_stdout(monkeypatch)
        assert stdin_state() is StdinState.TTY
        assert resolve_stdin_params({"data": Stdin()}, {}) == {}
        assert StdinCollector.is_available() is True

    def test_a_never_written_pipe_deposits_nothing_and_never_prompts(
        self, monkeypatch: pytest.MonkeyPatch, pipe_stdin: Any
    ):
        pipe_stdin()
        self._tty_stdout(monkeypatch)
        assert stdin_state() is StdinState.NO_INPUT
        assert resolve_stdin_params({"data": Stdin()}, {}) == {}
        assert StdinCollector.is_available() is False

    def test_an_empty_stream_deposits_empty_and_never_prompts(
        self, monkeypatch: pytest.MonkeyPatch, pipe_stdin: Any
    ):
        pipe = pipe_stdin()
        pipe.close_writer()
        self._tty_stdout(monkeypatch)
        assert stdin_state() is StdinState.READY
        assert resolve_stdin_params({"data": Stdin()}, {}) == {"data": ""}
        assert StdinCollector.is_available() is False

    def test_data_deposits_the_data_and_never_prompts(
        self, monkeypatch: pytest.MonkeyPatch, pipe_stdin: Any
    ):
        pipe = pipe_stdin()
        pipe.write("piped\n")
        pipe.close_writer()
        self._tty_stdout(monkeypatch)
        assert stdin_state() is StdinState.READY
        assert resolve_stdin_params({"data": Stdin()}, {}) == {"data": "piped\n"}
        assert StdinCollector.is_available() is False
