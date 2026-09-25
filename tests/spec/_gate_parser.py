"""The gate parser `test_task_gates_still_hold.py` runs, and the tripwire over it.

Moved out of that module instead of imported from it, for one concrete reason:
it **skips itself at import** — ``pytest.skip(..., allow_module_level=True)``
when `.spec/features/` is empty — so a second test file importing the parser
through it would be skipped on `master` too, and the tripwire would never be
exercised where there is no feature directory to be wrong about.

Nothing here reads `.spec/features/` on its own: every function takes the file
it parses, so a test can point it at a `tmp_path` fixture whose tick state is
known exactly.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

#: One fenced block, captured **whatever its language tag**.
#:
#: **Fence-aware on purpose**: the command may not contain a fence.
#:
#: The first version was ``r"```bash\n(?P<cmd>.+?)\n```\s*\n(?P<values>[^\n]*?after:[^\n]*)"``
#: with ``re.S``, which requires the recorded values to sit on *one* line
#: directly after the closing fence. `run-request-entry/T11` writes them on two:
#:
#:     now at wave 4 entry: `3` *(…)* ·
#:     after: `0`
#:
#: so the non-greedy ``cmd`` kept expanding past its own closing fence until it
#: found a later one whose next line held ``after:`` — **swallowing the gate in
#: between**. The bridge gate was not merely skipped, it was consumed, and the
#: parser then ran one gate's command against another gate's recorded value.
#:
#: Found while correcting an unrelated comment that pushed that very gate from
#: 0 to 2 with this file green (rre F11 fallout).
#:
#: The language group is what lets the tripwire tell "this file records gates the
#: parser does not read" from "this file records no gates": the parser reads
#: `PARSER_LANGUAGE` only, and a fence tagged anything else is invisible to it.
FENCE = re.compile(
    r"```(?P<lang>[^\s`]*)[ \t]*\n(?P<cmd>(?:(?!```)[\s\S])*?)\n```[ \t]*\n", re.M
)

#: The one fence language a gate is read from. A file that tags its gates
#: ``sh``/``shell``/``Bash`` records them where the parser cannot see them, which
#: is a parse of zero against a file full of gates — the drift the tripwire
#: exists to catch.
PARSER_LANGUAGE = "bash"

TASK = re.compile(r"^### \[(?P<done>[ x])\] (?P<name>T\d+)", re.M)
AFTER_INT = re.compile(r"after:\s*`?(\d+)`?")
NOW_INT = re.compile(r"now(?: at [^:]*)?:\s*`?(\d+)`?")
#: Two exemptions, both **explicit and greppable**, because nothing else can
#: distinguish them from a broken gate:
#:
#: - `invariant` — the gate asserts a count must *not* change ("core still
#:   imports no plugin"). `now == after` is the point, not a defect.
#: - `superseded` — a later task legitimately invalidated the record. The gate
#:   was true for the wave that wrote it and is false against HEAD, and a reader
#:   has to be able to tell that from a regression.
#:
#: Requiring the word means the author *states* which one it is. Inferring it
#: from phrasing was tried and guessed wrong about seven gates.
EXEMPT = re.compile(r"\binvariant\b|\bsuperseded\b", re.I)

_WRAPPED = re.compile(r"\\\n\s*")


class Gate(NamedTuple):
    """One recorded counting gate, and the value `after:` says it must return."""

    task: str
    cmd: str
    expected: int
    now: int | None


class ParsedFile(NamedTuple):
    """What one `tasks.md` yielded.

    ``gates`` holds the gates the caller asked for (ticked tasks only by
    default); ``exempt`` holds those read but skipped for stating `invariant` or
    `superseded`, and is empty when `include_unticked` is false only for gates
    of tasks that have not run.
    """

    gates: tuple[Gate, ...]
    exempt: tuple[Gate, ...]

    @property
    def recognized(self) -> tuple[Gate, ...]:
        """Every gate the parser **read** — checked or exempt.

        The tripwire compares against this, not against `gates` alone, because a
        gate the file deliberately exempts is one the parser understood.
        """
        return self.gates + self.exempt


def _values(text: str, match: re.Match[str]) -> str:
    """The recorded values following a fence — up to the first blank line.

    Bounded so a fence with no record cannot reach forward into the next gate's,
    which is exactly how the old pattern lost one.
    """
    return text[match.end() :].split("\n\n", 1)[0]


def joined(cmd: str) -> str:
    """One command, however it was typed.

    A gate wrapped with a trailing ``\\`` is **one** command that happens to be
    typed on two lines. Joining them was missing once, and ``"\\n" in cmd``
    therefore skipped every wrapped gate **silently** — including
    `run-request-entry/T11`'s, which is the one that guards the transitional
    bridges. A comment added while fixing an unrelated finding pushed that gate
    from 0 to 2 and the suite stayed green.
    """
    return _WRAPPED.sub(" ", cmd.strip())


def _is_counting_gate(cmd: str) -> bool:
    """Whether the recorded value of ``cmd`` means anything.

    `uv run` and ``&&`` gates are skipped because this parser re-runs a *single*
    command and compares its number. And **counting gates only**: `rg -c` and
    ``| wc -l`` return a number, and comparing that to the recorded `after:` is
    meaningful — a bare `rg -n` returns *matching lines*, and its recorded values
    are line numbers (`job-owned-freshness` T3 reads `now: 1026 · after: 1026`,
    which is one line, not one thousand and twenty-six of anything).
    """
    if cmd.startswith("uv run") or "&&" in cmd or "\n" in cmd:
        return False
    return "-c " in cmd or "wc -l" in cmd


def _owner_of(pos: int, tasks: list[tuple[int, bool, str]]) -> tuple[bool, str]:
    done, name = False, "?"
    for start, is_done, task_name in tasks:
        if start < pos:
            done, name = is_done, task_name
        else:
            break
    return done, name


def declared_gates(path: Path) -> tuple[str, ...]:
    """Every counting gate ``path`` records, whatever its fence language and tick state.

    The file's own account of itself, which is what the tripwire compares the
    parse against. It is deliberately blind to the two things that must not
    change the answer — the ``bash`` tag the parser requires, and whether the
    owning task is ticked — so that a shortfall means *the parser* narrowed, not
    that the file changed.
    """
    text = path.read_text()
    out: list[str] = []
    for match in FENCE.finditer(text):
        cmd = joined(match.group("cmd"))
        if not _is_counting_gate(cmd):
            continue
        if AFTER_INT.search(_values(text, match)) is None:
            continue
        out.append(cmd)
    return tuple(out)


def parse_gates(path: Path, *, include_unticked: bool = False) -> ParsedFile:
    """Gates belonging to **finished** tasks only, unless told otherwise.

    A gate for an unstarted task records the value its work will produce, and
    asserting it now would fail for the one honest reason there is: the work has
    not been done. Only a `[x]` task claims its gate holds.

    ``include_unticked=True`` parses the file's gates regardless of tick state —
    the number the tripwire compares against the file, and the only form of this
    parse whose value does not move while a branch is being executed.

    No cache, no module state: calling this twice returns the same thing.
    """
    text = path.read_text()
    tasks = [
        (m.start(), m.group("done") == "x", m.group("name"))
        for m in TASK.finditer(text)
    ]

    gates: list[Gate] = []
    exempt: list[Gate] = []
    for match in FENCE.finditer(text):
        if match.group("lang") != PARSER_LANGUAGE:
            continue
        values = _values(text, match)
        after = AFTER_INT.search(values)
        if after is None:
            continue
        cmd = joined(match.group("cmd"))
        if not _is_counting_gate(cmd):
            continue
        done, task_name = _owner_of(match.start(), tasks)
        if not done and not include_unticked:
            continue
        now = NOW_INT.search(values)
        gate = Gate(
            task=task_name,
            cmd=cmd,
            expected=int(after.group(1)),
            now=int(now.group(1)) if now else None,
        )
        (exempt if EXEMPT.search(values) else gates).append(gate)
    return ParsedFile(gates=tuple(gates), exempt=tuple(exempt))


def gate_shaped_commands(path: Path) -> tuple[str, ...]:
    """Every fence in ``path`` — **whatever its language** — holding a command that could be a gate.

    Shape only: `_is_counting_gate` and nothing else. The language tag is ignored
    here on purpose, so that a run of fences that drifted to `sh` *and* lost its
    `now:`/`after:` records is still visible as "this file holds commands that
    look like counts" rather than as a file with no gates at all.
    """
    text = path.read_text()
    out: list[str] = []
    for match in FENCE.finditer(text):
        cmd = joined(match.group("cmd"))
        if _is_counting_gate(cmd):
            out.append(cmd)
    return tuple(out)


def tripwire_shortfall(path: Path) -> str | None:
    """The message for ``path`` when the parser has gone blind to its gates.

    The comparison is the file against itself, in two legs:

    1. Every counting gate the file records — **ticked or not** — must be one the
       parser read. Both sides are tick-independent on purpose: a verdict that
       moves when a task is ticked is a verdict about the branch's progress, not
       about the file's format.
    2. A file that holds gate-shaped `bash` fences and yields **no** recorded gate
       at all fails, even though leg 1 has nothing to subtract — if the record
       format changed everywhere (`after:` renamed, the record moved out of the
       fence's first paragraph), the file's own account of its gates is gone too
       and leg 1 would agree that it has none.

    There is no third leg for a floor: a floor is a number about *some* feature —
    a small one cannot meet it however well-formed, and a large one passes it
    while silently dropping a whole category.
    """
    declared = declared_gates(path)
    parsed = parse_gates(path, include_unticked=True)
    read = tuple(gate.cmd for gate in parsed.recognized)
    unread = Counter(declared) - Counter(read)
    if unread:
        missing = ", ".join(f"{cmd!r}" for cmd in unread.elements())
        return (
            f"{path.name}: the file records {len(declared)} counting gate(s) and the "
            f"parser read {len(read)} — not read: {missing}"
        )
    if not read and (shaped := gate_shaped_commands(path)):
        return (
            f"{path.name}: {len(shaped)} gate-shaped fence(s) and the parser read no "
            "recorded gate from any of them — either the record format changed "
            "(`now:`/`after:`) or the fence language did (`bash`), or these are "
            "illustrative commands the file does not claim as gates"
        )
    return None


def tripwire_shortfalls(paths: Iterable[Path]) -> list[str]:
    """`tripwire_shortfall` for every path, shortfalls only."""
    return [msg for path in paths if (msg := tripwire_shortfall(path)) is not None]
