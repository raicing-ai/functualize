"""`Stdout` capability — explicit stdout data channel (Part C, revised).

Design: `functualize._types.stdout`.

The load-bearing assertions here are the *wiring* ones: the capability must be
injected and reach real stdout through the real execution path, and a job's
return value must NOT be emitted. Unit-level formatting is covered by the
emitter's own tests.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass

from functualize._engine.capabilities.stdout import WiredStdout
from functualize.job import Stdout
from functualize.testing import FakeStdout


class TestProtocolConformance:
    """Both the wired implementation and the test double satisfy `Stdout`."""

    def test_wired_stdout_satisfies_protocol(self) -> None:
        assert isinstance(WiredStdout(), Stdout)

    def test_fake_stdout_satisfies_protocol(self) -> None:
        assert isinstance(FakeStdout(), Stdout)


class TestEmitFormatMatrix:
    """`--output` x value-type matrix (design note's table)."""

    def _emit(self, fmt: str, value: object) -> str:
        buf = io.StringIO()
        WiredStdout(fmt, stream=buf).emit(value)
        return buf.getvalue()

    def test_auto_dispatches_str_as_raw(self) -> None:
        assert self._emit("auto", "hello") == "hello"

    def test_auto_dispatches_dict_as_one_json_doc(self) -> None:
        assert json.loads(self._emit("auto", {"a": 1})) == {"a": 1}

    def test_auto_streams_generator_as_ndjson(self) -> None:
        def rows():
            yield {"n": 1}
            yield {"n": 2}

        lines = self._emit("auto", rows()).splitlines()
        assert [json.loads(x) for x in lines] == [{"n": 1}, {"n": 2}]

    def test_output_decides_list_handling(self) -> None:
        """The meaningful lever: json => one array, ndjson => one line per item."""
        value = [{"i": 1}, {"i": 2}]
        assert json.loads(self._emit("json", value)) == value
        assert [
            json.loads(x) for x in self._emit("ndjson", value).splitlines()
        ] == value

    def test_dataclass_emits_as_json(self) -> None:
        @dataclass
        class Report:
            rows: int

        assert json.loads(self._emit("auto", Report(rows=3))) == {"rows": 3}

    def test_none_format_suppresses(self) -> None:
        assert self._emit("none", {"a": 1}) == ""

    def test_none_value_emits_nothing(self) -> None:
        assert self._emit("json", None) == ""


class TestWrite:
    """`write()` is a verbatim passthrough — no serialization, no newline."""

    def test_write_is_verbatim(self) -> None:
        buf = io.StringIO()
        WiredStdout("auto", stream=buf).write("a,b,c")
        assert buf.getvalue() == "a,b,c"

    def test_write_suppressed_by_none(self) -> None:
        buf = io.StringIO()
        WiredStdout("none", stream=buf).write("nope")
        assert buf.getvalue() == ""


class TestRedaction:
    """Secrets must not leak through the data channel (schema §5)."""

    def test_emit_masks_secret_values(self) -> None:
        buf = io.StringIO()
        WiredStdout("json", secrets={"hunter2"}, stream=buf).emit({"token": "hunter2"})
        out = buf.getvalue()
        assert "hunter2" not in out
        assert "•••" in out

    def test_write_masks_secret_values(self) -> None:
        buf = io.StringIO()
        WiredStdout("auto", secrets={"hunter2"}, stream=buf).write("t=hunter2")
        assert "hunter2" not in buf.getvalue()


class TestFakeStdout:
    """The double records objects *and* the rendered wire text."""

    def test_records_emitted_objects(self) -> None:
        fake = FakeStdout()
        fake.emit({"id": 1})
        fake.emit({"id": 2})
        assert fake.emitted == [{"id": 1}, {"id": 2}]

    def test_renders_wire_text(self) -> None:
        fake = FakeStdout("ndjson")
        fake.emit({"id": 1})
        fake.emit({"id": 2})
        assert [json.loads(x) for x in fake.text.splitlines()] == [
            {"id": 1},
            {"id": 2},
        ]

    def test_records_writes(self) -> None:
        fake = FakeStdout()
        fake.write("raw")
        assert fake.writes == ["raw"]
        assert fake.text == "raw"
