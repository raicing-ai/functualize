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

**This test must not become the eleventh.** It compares every `tasks.md` against
*itself*: each counting gate the file records — ticked or not — must be one the
parser reads. A parser that has gone blind to the file's fences therefore fails
instead of passing. The comparison used to be an absolute floor
(`len(_ALL) >= 12`), which made the verdict a function of the branch's **tick
state** rather than of its format — see `test_the_parser_actually_found_gates`.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.spec._gate_parser import (
    AFTER_INT,
    EXEMPT,
    FENCE,
    PARSER_LANGUAGE,
    TASK,
    Gate,
    joined,
    parse_gates,
    tripwire_shortfalls,
)

_ROOT = Path(__file__).resolve().parents[2]
_FEATURES = _ROOT / ".spec" / "features"

# The fence/task/value patterns and the parser itself now live in
# `tests/spec/_gate_parser.py` — this module skips at import when
# `.spec/features/` is empty, and a parser that can only be imported through a
# module which skips itself is a parser no other test can exercise.


def _task_files() -> list[Path]:
    files = sorted(_FEATURES.glob("*/tasks.md"))
    if not files:
        pytest.skip(
            ".spec/features/ is intentionally empty after the pre-merge cleanup",
            allow_module_level=True,
        )
    return files


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


_FILES = _task_files()
#: Parsed **once**, ticked gates only, and never re-parsed: `test_the_exemption_is_not_a_way_out`
#: compares exemption count against gate count, so a second parse would count the
#: same gate twice. (It did once: the count read 108.)
_PARSED = [(path, parse_gates(path)) for path in _FILES]
_EXEMPTED: list[str] = [
    f"{path.parent.name} {gate.task}"
    for path, parsed in _PARSED
    for gate in parsed.exempt
]
_ALL = [(path, gate) for path, parsed in _PARSED for gate in parsed.gates]


@pytest.mark.skipif(shutil.which("rg") is None, reason="gates are written in ripgrep")
class TestEveryRecordedGateStillHolds:
    def test_the_parser_actually_found_gates(self) -> None:
        """The tripwire against this test becoming the eleventh unfalsifiable one.

        Every counting gate a `tasks.md` records — **ticked or not** — must be
        one the parser reads, so the verdict is a fact about the file's format
        and never about the branch's tick state.

        The predecessor was `len(_ALL) >= 12`: an absolute floor. `_ALL` holds
        ticked gates only, so that assertion was red for the whole of a feature
        branch whose first six tasks had not been done yet, and green again once
        they were — the same file, the same format, a different verdict, and no
        diff to explain it. It was wrong in both directions too: a four-gate
        feature could never satisfy it however well-formed the file, and a
        thirty-gate one satisfied it while the parser quietly read half.
        """
        shortfalls = tripwire_shortfalls(_FILES)
        assert not shortfalls, (
            "these task files record counting gates the parser does not read — "
            "the format probably changed and this test now checks less than it "
            "claims:\n  " + "\n  ".join(shortfalls)
        )

    def test_every_fenced_gate_is_accounted_for(self) -> None:
        """A *category* of gate must not go missing silently.

        `test_the_parser_actually_found_gates` compares counts, and a count can
        say that *one* gate went missing but not which kind stopped being read:
        for a long time this file skipped every gate whose command was wrapped
        with a trailing backslash, and — worse — one gate whose `now:`/`after:`
        sat on two lines caused the non-greedy `cmd` pattern to run past its own
        closing fence and **swallow the next gate whole**. The old absolute floor
        stayed comfortably above 12 throughout, so it saw neither. Both were
        found only when an unrelated comment pushed a swallowed gate from 0 to
        2 and this file stayed green.

        So every fenced `bash` block in every `tasks.md` must be *either*
        checked, or skipped **for a reason this test can name**. An unclassified
        fence fails, which is what makes "the parser reads them all" a claim
        rather than a hope.
        """
        unclassified: list[str] = []
        for path in _FILES:
            text = path.read_text()
            tasks = [(m.start(), m.group("done") == "x") for m in TASK.finditer(text)]

            def _task_is_done(pos: int, tasks: list[tuple[int, bool]] = tasks) -> bool:
                done = False
                for start, is_done in tasks:
                    if start < pos:
                        done = is_done
                    else:
                        break
                return done

            for match in FENCE.finditer(text):
                if match.group("lang") != PARSER_LANGUAGE:
                    continue
                cmd = joined(match.group("cmd"))
                tail = text[match.end() :]
                values = tail.split("\n\n", 1)[0]
                reasons = [
                    (not AFTER_INT.search(values), "no recorded `after:`"),
                    (cmd.startswith("uv run"), "runs a test suite, not a count"),
                    ("&&" in cmd or "\n" in cmd, "several commands, not one"),
                    (
                        "-c " not in cmd and "wc -l" not in cmd,
                        "not a counting command",
                    ),
                    (bool(EXEMPT.search(values)), "explicitly exempt"),
                    (
                        not _task_is_done(match.start()),
                        "the task has not run yet, so its gate records what its "
                        "work will produce",
                    ),
                ]
                if any(hit for hit, _ in reasons):
                    continue
                # Compared against the **precomputed** `_ALL`. Re-parsing here
                # returns the same gates but makes this test re-derive the very
                # list it is auditing, so a parse that stops matching a file
                # would keep agreeing with itself.
                if not any(
                    cmd == parsed_cmd and parsed_path == path
                    for parsed_path, (_, parsed_cmd, _, _) in _ALL
                ):
                    unclassified.append(f"{path.parent.name}: {cmd[:70]}")

        assert not unclassified, (
            "these fenced gates are neither checked nor skipped for a stated "
            "reason, which is how a whole category went missing before:\n  "
            + "\n  ".join(unclassified)
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
    def test_the_after_value_is_still_true(self, path: Path, gate: Gate) -> None:
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
