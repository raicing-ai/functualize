"""The port refuses what it was built to refuse — AC-6, AC-7, and the premise.

`plugin-host-protocol` exists because two shipped plugins reached past the
facades into `app._di_registry`, and `app: Any` reported nothing either time.
Both reaches were also **permanently dead** — one guarded by
`hasattr(app, "resolve")`, which is False, the other by an import of a domain
ADR-022 retired — so nothing failed at runtime to give them away either.

That is the whole argument for a port, and an argument is not a gate. This file
runs mypy over `fixtures/the_host_cannot_be_bypassed.py`, which makes both
original reaches plus seven more, and requires the errors to fall on exactly the
lines marked `# want-error`.

**Both halves matter, and the fixture carries both.** Its first function makes
nine calls a shipped plugin really makes and must type-check clean; everything
after it is a reach that must not. A port that refused everything would pass a
negatives-only file while being useless, and a port that allowed everything is
`Any` with extra ceremony.

`tasks.md` put this in `tests/spec/test_the_port_is_not_leaked.py`, which is
`store-substrate`'s file about the *substrate* port and the filesystem. Sharing
it would give one file two unrelated reasons to change — the divergent-change
smell the port's own home decision was made to avoid (`spec.md` §E3). Its
second gate, `FUNCTUALIZE_TEST_SUBSTRATE=sqlite`, belongs to that feature too:
this port has no second pass, because it has no second implementation.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "the_host_cannot_be_bypassed.py"

_ERROR_LINE = re.compile(r"^.*?:(\d+): error:")

#: The reaches that must stay refused, as `(substring, why)`. Kept separately
#: from the line numbers so a reviewer sees *what* is being refused without
#: opening the fixture, and so deleting a case fails the count below.
REFUSALS = {
    "app.dii": "a misspelled facade",
    "provdie": "a misspelled method, one level down",
    "_di_registry": "the private reach this feature exists to close",
    "app.resolve(": "the `hasattr(app, 'resolve')` probe, as a call",
    "hook_registry": "the firing half of the hook API",
    "execution_engine": "excluded: one real client after T4",
    "substrate_override": "excluded: the install slot is the engine's",
    "app.run()": "excluded: re-entering delivery from inside delivery",
    "app.workflows": "excluded: no plugin client at all",
}


def _marked_lines() -> set[int]:
    return {
        n
        for n, line in enumerate(FIXTURE.read_text().splitlines(), start=1)
        if line.rstrip().endswith("# want-error")
    }


def _error_lines() -> tuple[set[int], str]:
    api = pytest.importorskip("mypy.api", reason="mypy is a dev dependency")
    out, _err, _code = api.run(["--strict", str(FIXTURE)])
    lines = set()
    for report in out.splitlines():
        match = _ERROR_LINE.match(report)
        if match:
            lines.add(int(match.group(1)))
    return lines, out


def test_every_named_refusal_is_present_in_the_fixture() -> None:
    """So a case cannot be quietly dropped to make the file pass."""
    text = FIXTURE.read_text()
    missing = [needle for needle in REFUSALS if needle not in text]
    assert not missing, f"refusal case(s) removed from the fixture: {missing}"
    assert len(_marked_lines()) == len(REFUSALS)


def test_the_port_refuses_exactly_the_marked_reaches() -> None:
    errors, report = _error_lines()
    marked = _marked_lines()

    unexpected = errors - marked
    assert not unexpected, (
        "mypy rejected a call a plugin is supposed to make, at line(s) "
        f"{sorted(unexpected)}. The port has become unusable rather than "
        f"narrow:\n{report}"
    )
    missing = marked - errors
    assert not missing, (
        f"no error at marked line(s) {sorted(missing)}. Either a member was "
        "added to the port that was argued off it, or a misspelling was "
        f"'fixed' into a real member -- which is how a negative test dies:\n"
        f"{report}"
    )
