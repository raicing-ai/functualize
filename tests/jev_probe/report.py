"""The probe's record: what was measured, and what each number came from.

The instrument and the reference are two files with one source of truth: a
measurement module records a `Fact`, and the reference transcribes it. A fact
carries the row it belongs to, an id a reader can cite, the value as measured,
and the evidence level — so the reference never has to compose a cell from
prose, and a cell that was not measured cannot be spelled like one that was.

The record is printed at the end of the run by `conftest.py`
(`pytest_terminal_summary`), which is why `uv run pytest -q -m jev_probe`
prints the matrix: pytest's own output formats an item's *pass*, and a passing
run with `-q` shows none of the captured output a module printed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

#: `measured (real service)` — the operation ran against the actual service.
#: The only level this probe can emit: it speaks to one endpoint over the wire.
REAL_SERVICE: Final[str] = "measured (real service)"

#: The level for a cell nobody could measure, with the reason it was not.
NOT_MEASURED: Final[str] = "NOT MEASURED"

EVIDENCE_LEVELS: Final[tuple[str, ...]] = (REAL_SERVICE, NOT_MEASURED)

#: The rows of the measurement matrix, in the order the reference publishes
#: them. A fact names one; a row with no facts is a gap, not a blank.
ROWS: Final[tuple[tuple[str, str], ...]] = (
    ("A", "Contract"),
    ("B", "Identities"),
    ("C", "Stability"),
    ("D", "Cost shape"),
    ("E", "Error taxonomy"),
    ("F", "Reachability"),
    ("G", "Authority boundary"),
)

_ROW_NAMES: Final[frozenset[str]] = frozenset(letter for letter, _ in ROWS)


@dataclass(frozen=True, slots=True)
class Fact:
    """One measured cell: a row, a citable id, the value, and its evidence."""

    row: str
    fact_id: str
    name: str
    value: str
    detail: str = ""
    evidence: str = REAL_SERVICE

    def line(self) -> str:
        """The one-line form, with the fact's own evidence stamp.

        The stamp is a field rather than a constant here because the record can
        hold both kinds of cell, and a gap printed under a measurement's stamp
        is exactly the over-claim this instrument exists to prevent. A test in
        `test_gating.py` renders a gap and asserts it says so.
        """
        rendered = f"  {self.fact_id}  {self.name}: {self.value} — {self.evidence}"
        return f"{rendered}\n        {self.detail}" if self.detail else rendered


@dataclass(slots=True)
class Report:
    """Every fact one run recorded, in the order the modules recorded them."""

    facts: list[Fact] = field(default_factory=list)

    def record(self, fact: Fact) -> Fact:
        self.facts.append(fact)
        return fact

    def clear(self) -> None:
        self.facts.clear()

    def of(self, row: str) -> tuple[Fact, ...]:
        return tuple(fact for fact in self.facts if fact.row == row)

    def render(self, *, header: str = "") -> str:
        """The measured values, grouped by row, ready to print."""
        lines = [header] if header else []
        for letter, title in ROWS:
            facts = self.of(letter)
            if not facts:
                continue
            lines.append("")
            lines.append(f"{letter}. {title}")
            lines.extend(fact.line() for fact in facts)
        lines.append("")
        lines.append(f"{len(self.facts)} facts recorded.")
        return "\n".join(lines)


#: The run's record. One per process; `conftest.py` clears it at session start.
REPORT: Final[Report] = Report()


def measured(
    row: str,
    fact_id: str,
    name: str,
    value: str,
    detail: str = "",
) -> Fact:
    """Record a cell backed by an observation on the real service.

    A value that would be a guess is not recordable here — leave the row to
    `not_measured` and say why instead.
    """
    if row not in _ROW_NAMES:
        raise ValueError(
            f"{row!r} is not a matrix row; the rows are {sorted(_ROW_NAMES)}"
        )
    if not value.strip():
        raise ValueError(
            f"{fact_id}: a measured fact needs the value that was measured"
        )
    return REPORT.record(
        Fact(row=row, fact_id=fact_id, name=name, value=value, detail=detail)
    )


def not_measured(row: str, fact_id: str, name: str, reason: str) -> Fact:
    """Record a cell nobody could measure, and why.

    Returns the fact rather than raising, so a module can record a gap and
    carry on to the rows it *can* measure.
    """
    if row not in _ROW_NAMES:
        raise ValueError(
            f"{row!r} is not a matrix row; the rows are {sorted(_ROW_NAMES)}"
        )
    if not reason.strip():
        raise ValueError(
            f"{fact_id}: an unmeasured cell must say why — {NOT_MEASURED} alone "
            "is indistinguishable from an oversight"
        )
    return REPORT.record(
        Fact(
            row=row,
            fact_id=fact_id,
            name=name,
            value=NOT_MEASURED,
            detail=reason,
            evidence=NOT_MEASURED,
        )
    )
