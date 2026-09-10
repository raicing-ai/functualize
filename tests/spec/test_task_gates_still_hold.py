"""Every acceptance gate a `tasks.md` declares is re-run, and must still hold.

A gate in this repository is *authored by running it*: the task records the
command, the value before (`now:`) and the value after (`after:`). That makes
each gate true at the moment it was written — and nothing re-runs it afterwards.
So a later task can change the code, a `[x]` can come to rest on a number that
has since moved, and nobody finds out.

Adversarial review found exactly that in four features at once
(`run-request-entry` F3, `adjacent-defects` M5, `agent-step-port` S-4, and a
`job-owned-freshness` gate naming a path that does not exist). This test turns
"the gate was true once" into "the gate is true now".

It also catches the branch's signature defect — **a gate that cannot fail**. Ten
have been found so far, each broken a different way:

- `\\b` before a name normally reached through a `_`-prefixed attribute
- `rg -l 'P1' -e 'P2'` reading `P1` as a *file path*, writing to stderr, exit 0
- a single-line pattern against a signature `ruff format` had wrapped
- a count of one spelling standing in for a dependency
- a sabotage naming a suite that exercises none of the code
- a test comparing a function to itself

A gate whose `now:` already equals its `after:` proves nothing by passing, and is
reported here rather than quietly counted as green.

**This test must not become the eleventh.** It reports how many gates it could
parse and asserts that number is substantial, so a parser that silently matches
nothing fails instead of passing.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_FEATURES = _ROOT / ".spec" / "features"

_GATE = re.compile(
    r"```bash\n(?P<cmd>.+?)\n```\s*\n(?P<values>[^\n]*?after:[^\n]*)", re.S
)
_AFTER_INT = re.compile(r"after:\s*`?(\d+)`?")
_NOW_INT = re.compile(r"now(?: at [^:]*)?:\s*`?(\d+)`?")
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
_EXEMPT = re.compile(r"\binvariant\b|\bsuperseded\b", re.I)


def _task_files() -> list[Path]:
    files = sorted(_FEATURES.glob("*/tasks.md"))
    assert files, f"no tasks.md under {_FEATURES}"
    return files


_TASK = re.compile(r"^### \[(?P<done>[ x])\] (?P<name>T\d+)", re.M)


def _gates(path: Path) -> list[tuple[str, str, int, int | None]]:
    """Gates belonging to **finished** tasks only.

    A gate for an unstarted task records the value its work will produce, and
    asserting it now would fail for the one honest reason there is: the work has
    not been done. Only a `[x]` task claims its gate holds.
    """
    text = path.read_text()
    tasks = [
        (m.start(), m.group("done") == "x", m.group("name"))
        for m in _TASK.finditer(text)
    ]

    def owner(pos: int) -> tuple[bool, str]:
        done, name = False, "?"
        for start, is_done, task_name in tasks:
            if start < pos:
                done, name = is_done, task_name
            else:
                break
        return done, name

    out: list[tuple[str, str, int, int | None]] = []
    for match in _GATE.finditer(text):
        after = _AFTER_INT.search(match.group("values"))
        if after is None:
            continue
        cmd = match.group("cmd").strip()
        if cmd.startswith("uv run") or "&&" in cmd or "\n" in cmd:
            continue
        # **Counting gates only.** `rg -c` and `| wc -l` return a number, and
        # comparing that to the recorded `after:` is meaningful. A bare `rg -n`
        # returns *matching lines*, and its recorded values are line numbers —
        # `job-owned-freshness` T3 reads `now: 1026 · after: 1026`, which is one
        # line, not one thousand and twenty-six of anything. Treating those as
        # counts made this test report a defect that was its own misreading.
        if "-c " not in cmd and "wc -l" not in cmd:
            continue
        done, task_name = owner(match.start())
        if not done:
            continue
        if _EXEMPT.search(match.group("values")):
            _EXEMPTED.append(f"{path.parent.name} {task_name}")
            continue
        now = _NOW_INT.search(match.group("values"))
        out.append(
            (task_name, cmd, int(after.group(1)), int(now.group(1)) if now else None)
        )
    return out


def _run(cmd: str) -> int:
    """A counting gate's value.

    `rg` exits 1 with no output when nothing matches, which *is* the answer zero
    — treating that as an error is how a satisfied gate comes to look broken.
    """
    proc = subprocess.run(
        cmd, shell=True, cwd=_ROOT, capture_output=True, text=True, timeout=120
    )
    text = proc.stdout.strip()
    if not text:
        return 0
    total = 0
    for line in text.splitlines():
        tail = line.rsplit(":", 1)[-1].strip()
        if tail.isdigit():
            total += int(tail)
        elif line.strip().isdigit():
            total += int(line.strip())
        else:
            total += 1
    return total


_EXEMPTED: list[str] = []
_ALL = [(p, g) for p in _task_files() for g in _gates(p)]


@pytest.mark.skipif(shutil.which("rg") is None, reason="gates are written in ripgrep")
class TestEveryRecordedGateStillHolds:
    def test_the_parser_actually_found_gates(self) -> None:
        """The tripwire against this test becoming the eleventh unfalsifiable one."""
        assert len(_ALL) >= 12, (
            f"only {len(_ALL)} gates parsed from {len(_task_files())} task files — "
            "the format probably changed and this test now checks nothing"
        )

    def test_the_exemption_is_not_a_way_out(self) -> None:
        """`invariant` and `superseded` must stay a minority.

        An exemption anyone can write is an exemption that eventually covers
        everything. This bounds it: if more gates are exempt than checked, the
        convention has become the escape hatch it was meant not to be.
        """
        assert len(_EXEMPTED) <= len(_ALL), (
            f"{len(_EXEMPTED)} gates are exempt and only {len(_ALL)} are checked: "
            f"{_EXEMPTED}"
        )

    @pytest.mark.parametrize(
        ("path", "gate"),
        _ALL,
        ids=[f"{p.parent.name}-{g[0]}" for p, g in _ALL],
    )
    def test_the_after_value_is_still_true(
        self, path: Path, gate: tuple[str, str, int, int | None]
    ) -> None:
        task, cmd, expected, _ = gate

        assert _run(cmd) == expected, (
            f"{path.relative_to(_ROOT)} {task} records `after: {expected}` for\n"
            f"    {cmd}\n"
            "and that is no longer what it returns. Either a later task moved the "
            "code and the record is stale, or something regressed. Both are worth "
            "knowing; neither should be silent."
        )


@pytest.mark.skipif(shutil.which("rg") is None, reason="gates are written in ripgrep")
class TestNoGateIsAlreadySatisfied:
    def test_none_records_the_same_value_before_and_after(self) -> None:
        """A gate whose `now:` equals its `after:` cannot fail.

        It passes the day it is written and every day after, whatever the code
        does. Some are legitimately phrased that way — a task whose gate is "this
        count must not change" — and those say so in prose beside the numbers.
        """
        # A gate whose prose says the count is deliberately unchanged is
        # exempt: some tasks legitimately assert "this must not move". Those
        # say so beside the numbers, and the recorded line is what this reads.
        already = [
            f"{path.parent.name} {task}: now == after == {after} for {cmd}"
            for path, (task, cmd, after, now) in _ALL
            if now is not None and now == after
        ]

        assert not already, (
            "these gates are satisfied before their task runs, so passing proves "
            "nothing:\n  " + "\n  ".join(already)
        )
