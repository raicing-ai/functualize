"""The door that makes `AdapterPlugin.__call__(app: PluginHost)` bite — AC-18.

`tasks.md` for T9 states the hazard plainly: *"The retype alone is provably
inert: nothing statically accepts `AdapterPlugin` today
(`validate_adapter(obj: Any)`, tests-only), so mypy reports nothing."* Measured
and true — retyping the protocol left `uv run mypy` green on all 364 files.

So the retype and its consumer land together. The consumer is
`tests/spec/fixtures/adapters_against_the_port.py`, which hands every concrete
adapter to a function that wants an `AdapterPlugin`; this file runs mypy over
it and requires the errors to fall on exactly the lines marked `# want-error`.

**Both directions matter, and they fail differently.**

- Errors where nothing is marked: an adapter that used to conform has stopped.
- Marks where no error lands: *the door came unwired.* Reverting
  `__call__(app: PluginHost)` to `app: Any` makes four of the five errors
  vanish, because `Any` accepts anything — which is exactly the inert state
  this file exists to prevent, and exactly what a plain green mypy run cannot
  tell you about.

Five marks today, for two different reasons, and only four of them are T10's.
The fixture's docstring says which is which; the short version is that
`MCPAdapterPlugin` never had `run` or `shutdown` and never conformed at all.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "adapters_against_the_port.py"

_ERROR_LINE = re.compile(r"^.*?:(\d+): error:")


def _marked_lines() -> set[int]:
    """Lines *ending* with the marker, so prose that mentions it is not a case."""
    return {
        n
        for n, line in enumerate(FIXTURE.read_text().splitlines(), start=1)
        if line.rstrip().endswith("# want-error")
    }


def _error_lines() -> tuple[set[int], str]:
    api = pytest.importorskip("mypy.api", reason="mypy is a dev dependency")
    pytest.importorskip("functualize_http", reason="plugin packages must be installed")
    pytest.importorskip(
        "functualize_lambda", reason="plugin packages must be installed"
    )
    pytest.importorskip("functualize_mcp", reason="plugin packages must be installed")
    out, _err, _code = api.run(["--strict", str(FIXTURE)])
    lines = set()
    for report in out.splitlines():
        match = _ERROR_LINE.match(report)
        if match:
            lines.add(int(match.group(1)))
    return lines, out


def test_the_door_exists_at_all() -> None:
    """Something must statically accept an `AdapterPlugin`, or nothing is checked.

    This is the `rg -n ': AdapterPlugin' src plugins tests` gate, as a test:
    before T9 the only hit in the repository was a **comment heading** in
    `tests/test_adapter_protocol.py:408`.
    """
    assert ": AdapterPlugin" in FIXTURE.read_text()


def test_exactly_the_marked_adapters_fail_conformance() -> None:
    errors, report = _error_lines()
    marked = _marked_lines()

    unexpected = errors - marked
    assert not unexpected, (
        f"an adapter stopped conforming, at line(s) {sorted(unexpected)}:\n{report}"
    )
    missing = marked - errors
    assert not missing, (
        f"no error at marked line(s) {sorted(missing)}. Either an adapter was "
        "widened without removing its mark, or `AdapterPlugin.__call__` was "
        f"reverted towards `Any` and the door is inert again:\n{report}"
    )
