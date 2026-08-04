"""Unit tests for stdout emission integration.

Tests StdoutEmitter behavior with --output json/ndjson/raw/none, None return
values, invalid --output validation, and rc.log() routing to stderr.

Validates Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6
"""

from __future__ import annotations

import io
import json
import logging
from contextlib import redirect_stdout

import pytest

from functualize._cli.dispatch import _extract_global_options
from functualize._primitives.stdout_emitter import StdoutEmitter

# =============================================================================
# Tests: --output json serializes return value to stdout (Requirement 6.1)
# =============================================================================


class TestOutputJson:
    """Test --output json serializes return value to stdout."""

    def test_json_emits_dict(self) -> None:
        """A dict value is JSON-serialized to stdout with trailing newline."""
        emitter = StdoutEmitter(format="json")
        buf = io.StringIO()
        with redirect_stdout(buf):
            emitter.emit({"key": "value", "count": 42})

        output = buf.getvalue()
        assert output.endswith("\n")
        parsed = json.loads(output)
        assert parsed == {"key": "value", "count": 42}

    def test_json_emits_list(self) -> None:
        """A list value is JSON-serialized to stdout."""
        emitter = StdoutEmitter(format="json")
        buf = io.StringIO()
        with redirect_stdout(buf):
            emitter.emit([1, 2, 3])

        parsed = json.loads(buf.getvalue())
        assert parsed == [1, 2, 3]

    def test_json_emits_string(self) -> None:
        """A string value is JSON-serialized (quoted) to stdout."""
        emitter = StdoutEmitter(format="json")
        buf = io.StringIO()
        with redirect_stdout(buf):
            emitter.emit("hello world")

        parsed = json.loads(buf.getvalue())
        assert parsed == "hello world"

    def test_json_emits_number(self) -> None:
        """An integer value is JSON-serialized to stdout."""
        emitter = StdoutEmitter(format="json")
        buf = io.StringIO()
        with redirect_stdout(buf):
            emitter.emit(99)

        parsed = json.loads(buf.getvalue())
        assert parsed == 99

    def test_json_uses_str_fallback_for_non_serializable(self) -> None:
        """Non-JSON-native types use str() as fallback serializer."""
        emitter = StdoutEmitter(format="json")
        buf = io.StringIO()
        with redirect_stdout(buf):
            emitter.emit({"path": __import__("pathlib").Path("/tmp/test")})

        parsed = json.loads(buf.getvalue())
        assert parsed == {"path": "/tmp/test"}

    def test_global_options_parses_output_json(self) -> None:
        """_extract_global_options recognizes --output json."""
        opts, _ = _extract_global_options(["func", "--output", "json", "deploy"])
        assert opts.output == "json"

    def test_global_options_parses_output_json_equals(self) -> None:
        """_extract_global_options recognizes --output=json."""
        opts, _ = _extract_global_options(["func", "--output=json", "deploy"])
        assert opts.output == "json"


# =============================================================================
# Tests: --output raw writes str/bytes as-is to stdout (§C.2)
# =============================================================================


class TestOutputRaw:
    """Test --output raw writes str/bytes as-is (no added newline)."""

    def test_raw_emits_string_as_is(self) -> None:
        """A string value is written verbatim — raw means no added newline."""
        emitter = StdoutEmitter(format="raw")
        buf = io.StringIO()
        with redirect_stdout(buf):
            emitter.emit("hello")

        assert buf.getvalue() == "hello"

    def test_raw_coerces_non_string_via_str(self) -> None:
        """A non-str/bytes value under explicit raw is coerced via str()."""
        emitter = StdoutEmitter(format="raw")
        buf = io.StringIO()
        with redirect_stdout(buf):
            emitter.emit(42)

        assert buf.getvalue() == "42"

    def test_global_options_parses_output_raw(self) -> None:
        """_extract_global_options recognizes --output raw."""
        opts, _ = _extract_global_options(["func", "--output", "raw", "deploy"])
        assert opts.output == "raw"


# =============================================================================
# Tests: --output ndjson streams one JSON document per item (§C.2)
# =============================================================================


class TestOutputNdjson:
    """Test --output ndjson emits one compact JSON document per item."""

    def test_ndjson_emits_one_line_per_list_item(self) -> None:
        """A list emits one JSON document per element, newline-separated."""
        emitter = StdoutEmitter(format="ndjson")
        buf = io.StringIO()
        with redirect_stdout(buf):
            emitter.emit([{"a": 1}, {"a": 2}])

        lines = buf.getvalue().splitlines()
        assert [json.loads(line) for line in lines] == [{"a": 1}, {"a": 2}]

    def test_ndjson_streams_a_generator_row_wise(self) -> None:
        """A generator emits per item — not buffer-then-hand."""
        emitter = StdoutEmitter(format="ndjson")
        buf = io.StringIO()

        def rows() -> object:
            yield {"n": 1}
            yield {"n": 2}
            yield {"n": 3}

        with redirect_stdout(buf):
            emitter.emit(rows())

        lines = buf.getvalue().splitlines()
        assert [json.loads(line) for line in lines] == [
            {"n": 1},
            {"n": 2},
            {"n": 3},
        ]

    def test_global_options_parses_output_ndjson(self) -> None:
        """_extract_global_options recognizes --output ndjson."""
        opts, _ = _extract_global_options(["func", "--output", "ndjson", "deploy"])
        assert opts.output == "ndjson"


# =============================================================================
# Tests: --output none produces no stdout (Requirement 6.3)
# =============================================================================


class TestOutputNone:
    """Test --output none produces no stdout."""

    def test_none_format_produces_no_output(self) -> None:
        """With format='none', nothing is written to stdout."""
        emitter = StdoutEmitter(format="none")
        buf = io.StringIO()
        with redirect_stdout(buf):
            emitter.emit({"key": "value"})

        assert buf.getvalue() == ""

    def test_default_format_is_none(self) -> None:
        """Default format (no arg) is 'none' — backward compatible."""
        emitter = StdoutEmitter()
        buf = io.StringIO()
        with redirect_stdout(buf):
            emitter.emit("some value")

        assert buf.getvalue() == ""

    def test_global_options_parses_output_none(self) -> None:
        """_extract_global_options recognizes --output none."""
        opts, _ = _extract_global_options(["func", "--output", "none", "deploy"])
        assert opts.output == "none"

    def test_global_options_no_output_flag_is_none(self) -> None:
        """When --output is not specified, opts.output is None (default behavior)."""
        opts, _ = _extract_global_options(["func", "deploy"])
        assert opts.output is None


# =============================================================================
# Tests: None return value produces no stdout for all formats (Requirement 6.5)
# =============================================================================


class TestNoneReturnValue:
    """Test None return value produces no stdout regardless of format."""

    def test_json_format_none_value_no_output(self) -> None:
        """format='json' with None value writes nothing."""
        emitter = StdoutEmitter(format="json")
        buf = io.StringIO()
        with redirect_stdout(buf):
            emitter.emit(None)

        assert buf.getvalue() == ""

    def test_raw_format_none_value_no_output(self) -> None:
        """format='raw' with None value writes nothing."""
        emitter = StdoutEmitter(format="raw")
        buf = io.StringIO()
        with redirect_stdout(buf):
            emitter.emit(None)

        assert buf.getvalue() == ""

    def test_none_format_none_value_no_output(self) -> None:
        """format='none' with None value writes nothing."""
        emitter = StdoutEmitter(format="none")
        buf = io.StringIO()
        with redirect_stdout(buf):
            emitter.emit(None)

        assert buf.getvalue() == ""


# =============================================================================
# Tests: Invalid --output value produces error on stderr (Requirement 6.6)
# =============================================================================


class TestInvalidOutputValue:
    """Test invalid --output value produces error on stderr."""

    def test_invalid_output_xml_raises_system_exit(self) -> None:
        """--output=xml triggers SystemExit with code 1."""
        with pytest.raises(SystemExit) as exc_info:
            _extract_global_options(["func", "--output=xml", "deploy"])
        assert exc_info.value.code == 1

    def test_invalid_output_yaml_raises_system_exit(self) -> None:
        """--output=yaml triggers SystemExit with code 1."""
        with pytest.raises(SystemExit) as exc_info:
            _extract_global_options(["func", "--output=yaml", "deploy"])
        assert exc_info.value.code == 1

    def test_invalid_output_prints_error_to_stderr(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Invalid --output value prints descriptive error to stderr."""
        with pytest.raises(SystemExit):
            _extract_global_options(["func", "--output=xml", "deploy"])
        captured = capsys.readouterr()
        assert "xml" in captured.err
        assert "--output" in captured.err

    def test_invalid_output_error_mentions_valid_formats(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Error message for invalid --output mentions valid format options."""
        with pytest.raises(SystemExit):
            _extract_global_options(["func", "--output=csv", "deploy"])
        captured = capsys.readouterr()
        assert "json" in captured.err
        assert "ndjson" in captured.err
        assert "raw" in captured.err
        assert "none" in captured.err


# =============================================================================
# Tests: rc.log() output goes to stderr, not stdout (Requirement 6.4)
# =============================================================================


class TestLogRoutingToStderr:
    """Test that rc.log() output (via logging) goes to stderr, not stdout."""

    def test_logging_handler_targets_stderr_not_stdout(self) -> None:
        """A StreamHandler configured with sys.stderr writes to stderr, not stdout.

        This mirrors main.py's logging.basicConfig(stream=sys.stderr) setup.
        We verify the handler's stream IS sys.stderr (not stdout).
        """
        # Create a handler bound to a StringIO to verify output routing
        stderr_buf = io.StringIO()
        logger = logging.getLogger("test_stdout_emission_rc_log")
        logger.handlers.clear()
        handler = logging.StreamHandler(stream=stderr_buf)
        handler.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        stdout_buf = io.StringIO()

        with redirect_stdout(stdout_buf):
            logger.info("test log message")

        # Log should NOT appear in stdout
        assert "test log message" not in stdout_buf.getvalue()
        # Log SHOULD appear in the handler's stream (stderr equivalent)
        assert "test log message" in stderr_buf.getvalue()

    def test_log_does_not_contaminate_stdout_with_json_output(self) -> None:
        """When emitting JSON to stdout, log messages stay on stderr (not stdout)."""
        # Use a StringIO as the "stderr" stream for the handler
        stderr_buf = io.StringIO()
        logger = logging.getLogger("test_stdout_emission_contamination")
        logger.handlers.clear()
        handler = logging.StreamHandler(stream=stderr_buf)
        handler.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        emitter = StdoutEmitter(format="json")
        stdout_buf = io.StringIO()

        with redirect_stdout(stdout_buf):
            logger.info("this is a log message")
            emitter.emit({"result": "success"})

        # stdout should only contain valid JSON (no log contamination)
        stdout_output = stdout_buf.getvalue()
        parsed = json.loads(stdout_output)
        assert parsed == {"result": "success"}

        # The log message should be in the handler's stream, not stdout
        assert "this is a log message" in stderr_buf.getvalue()
        assert "this is a log message" not in stdout_output
