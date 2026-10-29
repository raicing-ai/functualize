"""`WiredStdout` records instead of writing when it is given a record.

A child its parent invoked with `capture=True` gets a `Stdout` whose `emit` and
`write` append to the parent's `EmissionRecord`. The recording happens ahead of
every early return the writing path has — `--emit-format none` and a `None`
value suppress *writing*, not what the parent asked to see — and ahead of
serialization, so the parent receives the objects themselves.

Without a record nothing changes: the expected strings below are what the same
calls wrote before the record existed.
"""

from __future__ import annotations

import io
from types import SimpleNamespace
from typing import Any

import pytest

from functualize._engine.capabilities.stdout import WiredStdout, _make_stdout
from functualize._types.run_request import EmissionRecord, RunRequest

RECORDED_FORMATS = ("json", "none", "raw", "auto")


class _NotJson:
    """An object no JSON encoder accepts."""


class TestRecording:
    @pytest.mark.parametrize("fmt", RECORDED_FORMATS)
    def test_emit_and_write_reach_the_record_and_not_the_stream(self, fmt: str) -> None:
        stream = io.StringIO()
        record = EmissionRecord()
        out = WiredStdout(fmt, stream=stream, record=record)
        doc: dict[str, Any] = {"a": 1}
        rows = [1, 2]
        text = "raw\n"
        blob = b"by"

        out.emit(doc)
        out.write(text)
        out.emit(rows)
        out.write(blob)

        assert stream.getvalue() == ""
        assert [id(v) for v in record.emitted] == [id(doc), id(rows)]
        assert [id(v) for v in record.writes] == [id(text), id(blob)]

    @pytest.mark.parametrize("fmt", RECORDED_FORMATS)
    def test_none_is_recorded(self, fmt: str) -> None:
        stream = io.StringIO()
        record = EmissionRecord()

        WiredStdout(fmt, stream=stream, record=record).emit(None)

        assert record.emitted == [None]
        assert stream.getvalue() == ""

    def test_a_non_json_object_under_json_raises_nothing(self) -> None:
        record = EmissionRecord()
        value = _NotJson()

        WiredStdout("json", stream=io.StringIO(), record=record).emit(value)

        assert record.emitted[0] is value

    def test_secrets_do_not_touch_the_record(self) -> None:
        """Redaction is a property of writing; the parent gets the value."""
        record = EmissionRecord()
        value = {"k": "s3cret"}

        WiredStdout(
            "json", stream=io.StringIO(), secrets={"s3cret"}, record=record
        ).emit(value)

        assert record.emitted[0] is value
        assert value == {"k": "s3cret"}


#: (format, call, argument, what the call wrote before the record existed).
BASE_OUTPUT: list[tuple[str, str, Any, str]] = [
    ("auto", "emit", {"a": 1}, '{"a":1}\n'),
    ("auto", "emit", [1, 2], "[1,2]\n"),
    ("auto", "emit", "hi", "hi"),
    ("auto", "emit", None, ""),
    ("auto", "write", "raw\n", "raw\n"),
    ("auto", "write", b"by", "by"),
    ("json", "emit", {"a": 1}, '{"a":1}\n'),
    ("json", "emit", "hi", '"hi"\n'),
    ("json", "emit", None, ""),
    ("ndjson", "emit", [1, 2], "1\n2\n"),
    ("raw", "emit", {"a": 1}, "{'a': 1}"),
    ("raw", "write", b"by", "by"),
    ("none", "emit", {"a": 1}, ""),
    ("none", "write", "raw\n", ""),
]


class TestWithoutARecord:
    @pytest.mark.parametrize(("fmt", "call", "arg", "expected"), BASE_OUTPUT)
    def test_output_is_unchanged(
        self, fmt: str, call: str, arg: Any, expected: str
    ) -> None:
        stream = io.StringIO()

        getattr(WiredStdout(fmt, stream=stream), call)(arg)

        assert stream.getvalue() == expected

    def test_redaction_is_unchanged(self) -> None:
        stream = io.StringIO()

        WiredStdout("json", stream=stream, secrets={"s3cret"}).emit({"k": "s3cret"})

        assert stream.getvalue() == '{"k":"•••"}\n'


class TestFactory:
    """`_make_stdout` hands the request's record to the channel it builds."""

    @staticmethod
    def _ctx(request: RunRequest | None) -> SimpleNamespace:
        return SimpleNamespace(context=SimpleNamespace(request=request))

    def test_a_request_carrying_a_record_records(self) -> None:
        record = EmissionRecord()
        request = RunRequest(
            job_name="child", surface="invoke", output_format="json", capture=record
        )
        stream = io.StringIO()

        out = _make_stdout(self._ctx(request))
        out._stream = stream
        out.emit({"a": 1})

        assert record.emitted == [{"a": 1}]
        assert stream.getvalue() == ""

    def test_a_request_without_one_writes(self) -> None:
        request = RunRequest(job_name="job", surface="invoke", output_format="json")
        stream = io.StringIO()

        out = _make_stdout(self._ctx(request))
        out._stream = stream
        out.emit({"a": 1})

        assert stream.getvalue() == '{"a":1}\n'

    def test_no_request_writes(self) -> None:
        stream = io.StringIO()

        out = _make_stdout(self._ctx(None))
        out._stream = stream
        out.emit("hi")

        assert stream.getvalue() == "hi"
