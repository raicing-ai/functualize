"""The gate tripwire's verdict is a fact about a file, not about a branch's progress.

`test_task_gates_still_hold.py::test_the_parser_actually_found_gates` — the check
that stops the whole file from becoming the eleventh unfalsifiable test — used to
be::

    assert len(_ALL) >= 12

`_ALL` holds gates of **ticked** tasks only, so that assertion passed or failed as
the branch was executed. On `run-request-entry` it was red from the file's first
commit until T6 was ticked, green at 8 gates, red again when a task was un-ticked
during rework, and finally green at 12 — five verdicts, one unchanged format. A
gate that moves with the tick state cannot be read as evidence about anything: a
red result says "not enough progress yet", which is exactly what it must never
say, and a green one says nothing about whether the parser still reads the file.

`test_the_parser_actually_found_gates` now compares each `tasks.md` against
**itself** — every counting gate the file records, ticked or not, must be one the
parser read — and this file holds the fixtures that pin that down:

- the *same* file text, at every tick state, gets the same verdict, while the set
  of gates actually re-run still moves with it (`test_…same_verdict…`,
  `test_…only_the_ticked…`);
- a file that records gates in a form the parser cannot read is a **shortfall**,
  at zero ticked tasks as much as at sixteen (`test_…other_language…`,
  `test_…records_unreadable…`) — the direction the old floor could not see at all,
  because a floor only ever complains about too *few* gates;
- a file with one gate is not a shortfall (`test_…small_file…`): twelve was a
  number about one particular feature, not about the format.

Everything here drives `tests/spec/_gate_parser.py` directly on a `tmp_path`
fixture. It imports that module rather than `test_task_gates_still_hold.py`
because the latter skips itself at import when `.spec/features/` is empty — and on
`master` it is empty, so a test that imported the parser through it would be
skipped on the very tree where the tripwire is being judged.
"""

from __future__ import annotations

from collections.abc import Collection
from pathlib import Path

import pytest

from tests.spec._gate_parser import parse_gates, tripwire_shortfalls

#: Tasks the default (16-task) fixture writes, and the three that carry a gate.
#: Three, not twelve: a fixture that satisfies an absolute floor cannot also be
#: evidence that no absolute floor is wanted.
_TASKS = 16
_GATED = (5, 12, 16)

#: Tick states the same text is run through. Every one of them must reach the
#: same verdict, and between them they cover: nothing done, the first tasks done,
#: exactly the gated tasks done, everything done, and an interleaved half.
_TICK_STATES = (
    (),
    (1,),
    (1, 2, 3),
    (5, 12, 16),
    tuple(range(1, _TASKS + 1)),
    (2, 4, 6, 8, 10, 12, 14, 16),
)


def _tasks_md(
    ticked: Collection[int],
    *,
    tasks: int = _TASKS,
    gated: Collection[int] = _GATED,
    language: str = "bash",
) -> str:
    """A `tasks.md` of ``tasks`` tasks, ``gated`` of which record a counting gate.

    Shaped like the real files: one `### [x] T<n>` header per task, its gate in a
    fenced block under it, the recorded values on the line after the fence. Plus
    two fences that are **not** gates — a suite run and a JSON block — because the
    tripwire's denominator is "commands that could be a count", and a fixture
    without decoys cannot show that.
    """
    lines = ["# Fixture — tick-independence", ""]
    for n in range(1, tasks + 1):
        lines += [f"### [{'x' if n in ticked else ' '}] T{n} — fixture task {n}", ""]
        lines += [f"Body of task {n}.", ""]
        if n in gated:
            lines += [
                f"```{language}",
                f"rg -c 'fixture_marker_{n}' fixture_{n}.txt",
                "```",
                f"now: `0` · after: `{n}`",
                "",
            ]
        if n == 1:
            lines += ["```bash", "uv run pytest tests/fixture", "```", ""]
        if n == 2:
            lines += ["```json", '{ "waves": [0, 1] }', "```", ""]
    return "\n".join(lines)


def _tasks_file(tmp_path: Path, text: str) -> Path:
    """``text`` written where a `tasks.md` lives, under a named feature directory."""
    feature = tmp_path / "fixture-feature"
    feature.mkdir(parents=True, exist_ok=True)
    path = feature / "tasks.md"
    path.write_text(text)
    return path


@pytest.mark.parametrize("ticked", _TICK_STATES, ids=lambda t: f"{len(t)}-ticked")
def test_the_same_file_gets_the_same_verdict_at_every_tick_state(
    tmp_path: Path, ticked: tuple[int, ...]
) -> None:
    """The property the old floor lacked, over one unchanged file text."""
    path = _tasks_file(tmp_path, _tasks_md(ticked))

    assert tripwire_shortfalls([path]) == []


def test_the_tick_state_still_moves_the_set_of_gates_that_are_checked(
    tmp_path: Path,
) -> None:
    """Otherwise the test above would pass on a tripwire that reads nothing.

    The verdict is tick-independent; **what is checked is not**, and must not
    become so. A gate for an unstarted task records the value its work will
    produce, and asserting it now would fail for the one honest reason there is.
    """
    unticked = _tasks_file(tmp_path / "a", _tasks_md(()))
    partly = _tasks_file(tmp_path / "b", _tasks_md((5,)))

    assert parse_gates(unticked).gates == ()
    assert [gate.task for gate in parse_gates(partly).gates] == ["T5"]
    assert [gate.task for gate in parse_gates(partly, include_unticked=True).gates] == [
        "T5",
        "T12",
        "T16",
    ]
    assert tripwire_shortfalls([unticked, partly]) == []


def test_a_file_whose_gates_are_fenced_in_another_language_is_a_shortfall(
    tmp_path: Path,
) -> None:
    """Format drift: the fences are there, the parser reads none of them.

    The commands are identical and the records are identical — only the fence tag
    moved from `bash` to `sh` — so *what is checked* quietly drops from three
    gates to none. The file still records three, and that is the comparison that
    fires.
    """
    path = _tasks_file(tmp_path, _tasks_md((5, 12, 16), language="sh"))

    assert parse_gates(path, include_unticked=True).gates == ()
    shortfalls = tripwire_shortfalls([path])
    assert len(shortfalls) == 1
    assert "records 3 counting gate(s)" in shortfalls[0]
    assert "the parser read 0" in shortfalls[0]


def test_a_file_whose_records_are_unreadable_is_a_shortfall(tmp_path: Path) -> None:
    """Format drift the file's own account cannot catch, because it drifted too.

    `after:` renamed to `expected:` leaves nothing to subtract — the file no longer
    records a value the parser recognises — so the shape of the fences is the only
    evidence left, and a file with three gate-shaped fences and zero read gates is
    not a file with no gates.
    """
    path = _tasks_file(tmp_path, _tasks_md((5, 12, 16)).replace("after:", "expected:"))

    shortfalls = tripwire_shortfalls([path])
    assert len(shortfalls) == 1
    assert "3 gate-shaped fence(s)" in shortfalls[0]


def test_a_drifted_language_does_not_excuse_a_drifted_record(tmp_path: Path) -> None:
    """Both kinds of drift at once still fail — the language leg cannot be the only one.

    `sh` fences carrying `expected:` records leave the parser with nothing at all:
    no gate records to subtract, and no `bash` fence that even looks like a gate.
    A file holding three commands of exactly the right shape is still not a file
    with no gates, so the gate-shaped set is counted whatever the fence language.
    """
    text = _tasks_md((5, 12, 16), language="sh").replace("after:", "expected:")
    path = _tasks_file(tmp_path, text)

    shortfalls = tripwire_shortfalls([path])
    assert len(shortfalls) == 1
    assert "3 gate-shaped fence(s)" in shortfalls[0]


def test_a_small_file_is_not_a_shortfall(tmp_path: Path) -> None:
    """Twelve was a number about one feature. Two gates in a two-task file are fine."""
    path = _tasks_file(tmp_path, _tasks_md((1,), tasks=2, gated=(1,)))

    assert len(parse_gates(path, include_unticked=True).gates) == 1
    assert tripwire_shortfalls([path]) == []


def test_an_exempted_gate_is_read_even_though_it_is_not_checked(tmp_path: Path) -> None:
    """`invariant`/`superseded` gates must not read as a shortfall.

    The parser skips them deliberately — the count is *supposed* not to move — so
    the tripwire has to count them as read, or the exemption convention would turn
    the tripwire red on a well-formed file.
    """
    text = _tasks_md((5,)).replace(
        "now: `0` · after: `5`", "now: `1` · after: `1` — invariant: must not change"
    )
    path = _tasks_file(tmp_path, text)
    parsed = parse_gates(path)

    assert parsed.gates == ()
    assert [gate.task for gate in parsed.exempt] == ["T5"]
    assert tripwire_shortfalls([path]) == []


def test_a_file_with_no_gates_at_all_is_not_a_shortfall(tmp_path: Path) -> None:
    """The other side of the same coin: nothing recorded, nothing to read."""
    path = _tasks_file(tmp_path, _tasks_md((1,), tasks=2, gated=()))

    assert tripwire_shortfalls([path]) == []
