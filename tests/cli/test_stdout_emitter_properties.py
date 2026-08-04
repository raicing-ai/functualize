"""Property-based tests for StdoutEmitter.

# Feature: cli-unix-compatibility, Properties 8, 9
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._primitives.stdout_emitter import StdoutEmitter

# =============================================================================
# Strategies: Generate JSON-serializable values
# =============================================================================

# Strategy: JSON-serializable leaf values (excluding None for Property 8)
_json_leaf = st.one_of(
    st.text(min_size=0, max_size=50),
    st.integers(min_value=-(10**9), max_value=10**9),
    st.floats(allow_nan=False, allow_infinity=False),
    st.booleans(),
)

# Strategy: JSON-serializable values (recursive: dicts, lists, leaves)
_json_value = st.recursive(
    _json_leaf,
    lambda children: st.one_of(
        st.lists(children, min_size=0, max_size=5),
        st.dictionaries(
            keys=st.text(min_size=1, max_size=10),
            values=children,
            min_size=0,
            max_size=5,
        ),
    ),
    max_leaves=20,
)

# Strategy: any value (including None) for silence tests
_any_value = st.one_of(
    _json_value,
    st.none(),
)

# Strategy: format choices (§C.2 vocabulary)
_any_format = st.sampled_from(["json", "ndjson", "raw", "none", "auto"])


# =============================================================================
# Property 8: Stdout JSON Round-Trip
# =============================================================================


@pytest.mark.slow
class TestStdoutJsonRoundTrip:
    """Property 8: Stdout JSON Round-Trip.

    For any JSON-serializable non-None value, emitting with format="json"
    and parsing produces equivalent value.

    **Validates: Requirements 6.1, 6.3, 6.5**
    """

    @given(value=_json_value)
    @settings(max_examples=300)
    def test_json_emit_round_trips(self, value: Any):
        """Emitting a JSON-serializable value and parsing back yields equivalent value.

        **Validates: Requirements 6.1, 6.3**
        """
        emitter = StdoutEmitter(format="json")

        # Capture stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            emitter.emit(value)

        output = buf.getvalue()

        # Output should be non-empty (value is not None)
        assert output, f"Expected non-empty output for value={value!r}"

        # Parse the output back
        parsed = json.loads(output)

        # JSON round-trip: int/float/str/bool/list/dict should be preserved
        # Note: json.dump uses default=str for non-native types, but we only
        # generate natively JSON-serializable values so strict equality holds.
        assert parsed == value, (
            f"Round-trip failed:\n"
            f"  original: {value!r}\n"
            f"  output:   {output!r}\n"
            f"  parsed:   {parsed!r}"
        )

    @given(value=_json_value)
    @settings(max_examples=300)
    def test_json_output_ends_with_newline(self, value: Any):
        """JSON output always ends with a trailing newline.

        **Validates: Requirements 6.1**
        """
        emitter = StdoutEmitter(format="json")

        buf = io.StringIO()
        with redirect_stdout(buf):
            emitter.emit(value)

        output = buf.getvalue()
        assert output.endswith("\n"), (
            f"Expected trailing newline, got output={output!r}"
        )

    @given(value=_json_value)
    @settings(max_examples=300)
    def test_json_output_is_valid_json(self, value: Any):
        """JSON output is always parseable by json.loads.

        **Validates: Requirements 6.1**
        """
        emitter = StdoutEmitter(format="json")

        buf = io.StringIO()
        with redirect_stdout(buf):
            emitter.emit(value)

        output = buf.getvalue()

        # Should not raise — valid JSON
        parsed = json.loads(output)
        assert parsed is not None or value is None


# =============================================================================
# Property 9: Stdout Silence
# =============================================================================


@pytest.mark.slow
class TestStdoutSilence:
    """Property 9: Stdout Silence.

    For format="none" or None return value, zero bytes written to stdout.

    **Validates: Requirements 6.3, 6.5**
    """

    @given(value=_any_value)
    @settings(max_examples=300)
    def test_format_none_produces_no_output(self, value: Any):
        """With format='none', no bytes are written regardless of value.

        **Validates: Requirements 6.3**
        """
        emitter = StdoutEmitter(format="none")

        buf = io.StringIO()
        with redirect_stdout(buf):
            emitter.emit(value)

        output = buf.getvalue()
        assert output == "", (
            f"Expected zero bytes for format='none', got {len(output)} bytes: {output!r}"
        )

    @given(fmt=_any_format)
    @settings(max_examples=300)
    def test_none_value_produces_no_output(self, fmt: str):
        """With return_value=None, no bytes are written regardless of format.

        **Validates: Requirements 6.5**
        """
        emitter = StdoutEmitter(format=fmt)

        buf = io.StringIO()
        with redirect_stdout(buf):
            emitter.emit(None)

        output = buf.getvalue()
        assert output == "", (
            f"Expected zero bytes for None value with format={fmt!r}, "
            f"got {len(output)} bytes: {output!r}"
        )

    @given(value=_any_value, fmt=_any_format)
    @settings(max_examples=300)
    def test_silence_conditions_combined(self, value: Any, fmt: str):
        """When EITHER format='none' OR value is None, zero bytes written.

        **Validates: Requirements 6.3, 6.5**
        """
        emitter = StdoutEmitter(format=fmt)

        buf = io.StringIO()
        with redirect_stdout(buf):
            emitter.emit(value)

        output = buf.getvalue()

        if fmt == "none" or value is None:
            assert output == "", (
                f"Expected silence (format={fmt!r}, value={value!r}), "
                f"got {len(output)} bytes: {output!r}"
            )
