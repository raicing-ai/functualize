"""`app.hooks.on_ready` rejects the four handlers it should — AC-5.

`contracts.md` §5 states eight cases and a required verdict for each. Four must
type-check (a handler typed against the port, a bound method, a handler still
annotated `app: Any`, and the bare decorator form) and four must not (a
non-callable, wrong arity, a wrong parameter type, and a handler that returns a
value).

**A table of verdicts is not a gate.** Before this file the property was
`Callable[..., Any]`, under which *none* of the four failures fired: measured
**4 of 8 behaving**, not the `3 of 8` `tasks.md` claimed, because the four
must-pass cases pass either way and every must-fail case passed too. The claim
and the number were both written without running mypy.

So the check runs mypy, over a fixture that calls the **shipped** property
rather than a local stand-in — otherwise the test would be checking a copy of
the signature instead of the signature.

The fixture's `# want-error` markers are the expected set: a case that stops
being an error fails this test, and so does a case that starts being one. That
second direction is what keeps `Any` from creeping back in — widening the
property would silence four errors at once, and silence is what a looser type
buys.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "on_ready_cases.py"

#: Lines mypy reported an error on, as `path:line: error: ...`.
_ERROR_LINE = re.compile(r"^.*?:(\d+): error:")


def _marked_lines() -> set[int]:
    """The fixture's `# want-error` lines.

    Matched on the line *ending* with the marker, so the module docstring's
    mention of the word is not a case.
    """
    return {
        n
        for n, line in enumerate(FIXTURE.read_text().splitlines(), start=1)
        if line.rstrip().endswith("# want-error")
    }


def _mypy_error_lines() -> tuple[set[int], str]:
    """Run mypy over the fixture; return the error lines and the raw report.

    Uses the repository's own cache directory rather than a temporary one: a
    cold cache costs ~15 s because the whole `functualize` package has to be
    analysed, and a gate that slow gets marked slow, and a gate marked slow
    gets skipped. Warm, this is about a second.
    """
    api = pytest.importorskip("mypy.api", reason="mypy is a dev dependency")
    out, _err, _code = api.run(["--strict", str(FIXTURE)])
    lines = set()
    for report in out.splitlines():
        match = _ERROR_LINE.match(report)
        if match:
            lines.add(int(match.group(1)))
    return lines, out


def test_the_fixture_still_states_eight_cases() -> None:
    """Four marked, four not — so neither half can quietly disappear."""
    text = FIXTURE.read_text()
    marked = _marked_lines()
    assert len(marked) == 4, f"expected four must-fail cases, found {sorted(marked)}"
    numbered = re.findall(r"^# (\d) · ", text, re.MULTILINE)
    assert numbered == ["1", "2", "3", "4", "5", "6", "7", "8"], numbered


def test_exactly_the_marked_cases_fail_type_checking() -> None:
    """The gate. Eight of eight, measured against the shipped property."""
    errors, report = _mypy_error_lines()
    marked = _marked_lines()

    unexpected = errors - marked
    assert not unexpected, (
        "mypy rejected a handler `contracts.md` §5 requires it to accept, at "
        f"line(s) {sorted(unexpected)}:\n{report}"
    )
    missing = marked - errors
    assert not missing, (
        "mypy accepted a handler `contracts.md` §5 requires it to reject, at "
        f"line(s) {sorted(missing)}. `on_ready` has been widened back towards "
        f"`Callable[..., Any]`:\n{report}"
    )
