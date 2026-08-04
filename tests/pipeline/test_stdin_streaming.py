"""Lazy NDJSON stdin — the input half of row-wise pipelining (§C.2).

The load-bearing test here is :class:`TestLaziness`: an iterator-typed `Stdin`
parameter must receive records **as they arrive**, not after the upstream
closes. Without it a three-stage pipeline degrades to buffer-then-hand, which is
exactly what the S5 acceptance criterion forbids.
"""

from __future__ import annotations

import io
from collections.abc import Iterable, Iterator
from typing import Annotated

from functualize._cli.stdin_reader import iter_stdin_ndjson, resolve_stdin_params
from functualize.app.adapters.click_params import _streaming_stdin_params
from functualize.job import Stdin


class _TrackingStdin:
    """A stdin stand-in that reports how many lines have actually been pulled."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines
        self.consumed = 0

    def __iter__(self) -> Iterator[str]:
        for line in self._lines:
            self.consumed += 1
            yield line

    def isatty(self) -> bool:
        return False

    def read(self) -> str:
        self.consumed = len(self._lines)
        return "".join(self._lines)


class TestParsing:
    def test_parses_one_record_per_line(self, monkeypatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO('{"n":1}\n{"n":2}\n'))
        assert list(iter_stdin_ndjson()) == [{"n": 1}, {"n": 2}]

    def test_blank_lines_are_not_records(self, monkeypatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO('{"n":1}\n\n\n{"n":2}\n'))
        assert list(iter_stdin_ndjson()) == [{"n": 1}, {"n": 2}]

    def test_malformed_line_yields_raw_string(self, monkeypatch) -> None:
        """One bad row must not kill a pipeline stage that may not even use it."""
        monkeypatch.setattr("sys.stdin", io.StringIO('{"n":1}\nnot-json\n'))
        assert list(iter_stdin_ndjson()) == [{"n": 1}, "not-json"]

    def test_non_object_json_records(self, monkeypatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO('1\n"two"\n[3]\n'))
        assert list(iter_stdin_ndjson()) == [1, "two", [3]]


class TestLaziness:
    """The AC: records arrive row-wise, not buffer-then-hand."""

    def test_first_record_available_before_stream_is_consumed(
        self, monkeypatch
    ) -> None:
        lines = [f'{{"n":{i}}}\n' for i in range(100)]
        tracking = _TrackingStdin(lines)
        monkeypatch.setattr("sys.stdin", tracking)

        stream = iter_stdin_ndjson()
        first = next(stream)

        assert first == {"n": 0}
        # The whole point: pulling one record must not drain the upstream.
        assert tracking.consumed == 1, (
            f"expected 1 line consumed for 1 record, got {tracking.consumed} "
            "— the stream is buffering instead of streaming"
        )

    def test_resolve_stdin_params_hands_back_a_lazy_iterator(self, monkeypatch) -> None:
        tracking = _TrackingStdin(['{"n":1}\n', '{"n":2}\n'])
        monkeypatch.setattr("sys.stdin", tracking)

        resolved = resolve_stdin_params(
            {"rows": Stdin()}, {"rows": None}, streaming={"rows"}
        )

        value = resolved["rows"]
        assert not isinstance(value, str)
        assert tracking.consumed == 0, "resolution must not read ahead"
        assert next(iter(value)) == {"n": 1}

    def test_non_streaming_param_still_gets_eager_string(self, monkeypatch) -> None:
        tracking = _TrackingStdin(['{"n":1}\n'])
        monkeypatch.setattr("sys.stdin", tracking)

        resolved = resolve_stdin_params({"data": Stdin()}, {"data": None})

        assert isinstance(resolved["data"], str)


class TestStreamingDetection:
    """Which annotations opt into the lazy stream."""

    def test_iterator_annotation_streams(self) -> None:
        def job(rows: Annotated[Iterator[dict], Stdin()]) -> None: ...

        assert _streaming_stdin_params(job, {"rows": Stdin()}) == frozenset({"rows"})

    def test_iterable_annotation_streams(self) -> None:
        def job(rows: Annotated[Iterable[dict], Stdin()]) -> None: ...

        assert _streaming_stdin_params(job, {"rows": Stdin()}) == frozenset({"rows"})

    def test_str_does_not_stream(self) -> None:
        """str is iterable but is emphatically not a stream."""

        def job(data: Annotated[str, Stdin()]) -> None: ...

        assert _streaming_stdin_params(job, {"data": Stdin()}) == frozenset()

    def test_bytes_does_not_stream(self) -> None:
        def job(data: Annotated[bytes, Stdin()]) -> None: ...

        assert _streaming_stdin_params(job, {"data": Stdin()}) == frozenset()
