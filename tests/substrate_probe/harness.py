"""The ten probe questions, in one place (FUN-25 task 1.3).

`StoreProfile` was a FUN-17 proposal when this probe was written; FUN-17 has since
frozen it in `src/functualize/_types/persistence.py` (`StoreProfile`, ADR-028). This
ticket's job is to find out what real backends would make its fields say, so the
questions below are transcribed from that proposal's twelve attributes minus its two
labels (`name`, `description`), in its own order; the answers are measured here.

**Shape, and why it is this shape.** Plain functions and frozen dataclasses.
No ABC, no `ProbeBackend` base class, nothing for a backend to inherit — a
shared base can only promise what all eight backends do, which is precisely the
intersection contract ADR-022 exists to forbid and `.spec/CONSTITUTION.md`
lists under *Forbidden Patterns*. A backend module answers the subset it can
answer and hands its answers to `reading()`; the fields it did not answer come
back `NOT MEASURED`, which is the only honest default.

**This module imports nothing of ours**, and that is checkable::

    $ rg -n "^(from|import) functualize" tests/substrate_probe/harness.py
    # must be empty

A probe routed through our adapter would measure the adapter. The one permitted
exception is `tier_a.py`, where for the filesystem and local SQLite the shipping
substrate *is* the backend under test.

**Never invent a cell.** Every constructor below refuses the shortcuts that
would put an unmeasured value in the matrix: an unknown field name, a second
answer for a field already answered, a value of the wrong shape, a
`NOT MEASURED` without a reason, and a "measurement" whose evidence level says
it was not measured.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final, Literal

if TYPE_CHECKING:
    from collections.abc import Iterable

#: How much a cell is worth. A vendor doc is not on this list: acceptance
#: criterion 6 says every field is traceable to a probe result, never to a
#: claim, so there is no evidence level that can carry one.
Evidence = Literal[
    "measured (real service)",
    "measured (emulator)",
    "measured (fake)",
    "NOT MEASURED",
]

EVIDENCE_LEVELS: Final[tuple[Evidence, ...]] = (
    "measured (real service)",
    "measured (emulator)",
    "measured (fake)",
    "NOT MEASURED",
)

#: The three fakes are instruments, not columns (AC2): a fake populates the
#: evidence level of a cell, and may never be the thing a cell is about.
FAKE_EVIDENCE: Final[Evidence] = "measured (fake)"

#: What a `StoreProfile` field is allowed to hold.
Shape = Literal["bool", "fencing", "bytes-or-unbounded"]

FENCING_VALUES: Final[tuple[str, ...]] = ("none", "process-local", "cross-process")

AnswerValue = bool | str | int | None


@dataclass(frozen=True, slots=True)
class Question:
    """One `StoreProfile` field, as something a backend can be asked.

    `asks` is the question in words; `answered_by` is the observation that
    settles it. `answered_by` exists because the failure this ticket guards
    against is a cell filled in from a vendor page — writing down the
    observation next to the question makes "measured" checkable by a reader.
    """

    field: str
    shape: Shape
    asks: str
    answered_by: str


#: The ten, in the proposal's own order. Two labels (`name`, `description`) are
#: not questions, which is why twelve attributes yield ten columns.
QUESTIONS: Final[tuple[Question, ...]] = (
    Question(
        field="cross_aggregate_atomicity",
        shape="bool",
        asks="Can two different keys be written so that either both land or neither does?",
        answered_by=(
            "write two keys in one operation with the second doomed to fail, then read "
            "both back: atomic means the first one is absent too"
        ),
    ),
    Question(
        field="fencing",
        shape="fencing",
        asks="How far does a lock reach — nowhere, this process, or every writer?",
        answered_by=(
            "hold the lock and have a second writer in another process attempt the same "
            "guarded write; cross-process means the second is refused, not queued behind "
            "an in-memory mutex"
        ),
    ),
    Question(
        field="multi_process",
        shape="bool",
        asks="Can two processes on one machine share this store without corrupting it?",
        answered_by=(
            "two OS processes interleave read-modify-write on one key; the lost-update "
            "count is the answer"
        ),
    ),
    Question(
        field="multi_machine",
        shape="bool",
        asks="Can two machines share it?",
        answered_by=(
            "whether the store is addressable from outside the host at all — a path on a "
            "local disk is not, an endpoint is"
        ),
    ),
    Question(
        field="durable_outbox",
        shape="bool",
        asks="Can a state change and the record that it happened commit together?",
        answered_by=(
            "write the state and its outbox row in one atomic unit, kill the writer "
            "between them if the backend allows it, and see whether a half-write is "
            "observable"
        ),
    ),
    Question(
        field="versioned_migrations",
        shape="bool",
        asks="Is there a schema whose version the store can carry and enforce?",
        answered_by=(
            "whether the backend has a schema object at all, and whether a document "
            "written under one version is rejected or silently accepted under another"
        ),
    ),
    Question(
        field="interactive_transaction",
        shape="bool",
        asks="Can a transaction stay open across a Python decision?",
        answered_by=(
            "begin, read, decide in Python, then write inside the same transaction. D1 "
            "cannot: it has no BEGIN/COMMIT and everything atomic must be one batch "
            "(05-cloudflare.md §A.3)"
        ),
    ),
    Question(
        field="remote",
        shape="bool",
        asks="Does every operation cross a network?",
        answered_by=(
            "measure one round trip; remote decides whether the engine may "
            "read-modify-write in a loop or must buffer and flush once — a 200-transition "
            "workflow is 200 round trips (06-s3.md §5)"
        ),
    ),
    Question(
        field="max_document_bytes",
        shape="bytes-or-unbounded",
        asks="How large a single document does it actually accept?",
        answered_by=(
            "write documents of increasing size until one is refused, and record the size "
            "that was refused rather than the documented cap — D1's 2 MB row limit is a "
            "claim until a write bounces off it (05-cloudflare.md §A.5)"
        ),
    ),
    Question(
        field="offline_capable",
        shape="bool",
        asks="Does it work with no network at all?",
        answered_by=(
            "run the round trip with the network unavailable; ADR-015's guarantee is a "
            "property of the configured store and today nothing states it"
        ),
    ),
)

FIELDS: Final[tuple[str, ...]] = tuple(question.field for question in QUESTIONS)

_BY_FIELD: Final[dict[str, Question]] = {q.field: q for q in QUESTIONS}


@dataclass(frozen=True, slots=True)
class Answer:
    """One cell: what a backend does, and how well we know it."""

    field: str
    value: AnswerValue
    evidence: Evidence
    detail: str

    @property
    def question(self) -> Question:
        return _BY_FIELD[self.field]

    @property
    def is_measured(self) -> bool:
        return self.evidence != "NOT MEASURED"


def measured(
    field: str, value: AnswerValue, *, evidence: Evidence, detail: str
) -> Answer:
    """A cell backed by an observation. `detail` is what was observed.

    Rejects `NOT MEASURED` as an evidence level: a measurement that was not
    made is `not_measured()`, and the two must not be spellable the same way.
    """
    question = _question(field)
    if evidence not in EVIDENCE_LEVELS:
        raise ValueError(
            f"{field}: {evidence!r} is not an evidence level; expected one of "
            f"{EVIDENCE_LEVELS}"
        )
    if evidence == "NOT MEASURED":
        raise ValueError(
            f"{field}: measured() cannot carry 'NOT MEASURED' — use not_measured() "
            "with the reason it was not measured"
        )
    if not detail.strip():
        raise ValueError(
            f"{field}: a measurement needs the observation that produced it, so a "
            "reader can tell it from a vendor claim"
        )
    _check_shape(question, value)
    return Answer(field=field, value=value, evidence=evidence, detail=detail)


def not_measured(field: str, reason: str) -> Answer:
    """A cell nobody measured, and why. The reason is not optional.

    `NOT MEASURED (no credentials)` is a legitimate outcome of this ticket;
    silence is not.
    """
    _question(field)
    if not reason.strip():
        raise ValueError(
            f"{field}: an unmeasured cell must say why — 'NOT MEASURED' alone is "
            "indistinguishable from an oversight"
        )
    return Answer(field=field, value=None, evidence="NOT MEASURED", detail=reason)


@dataclass(frozen=True, slots=True)
class Reading:
    """One backend's column: ten answers, in `QUESTIONS` order, always."""

    backend: str
    answers: tuple[Answer, ...]

    def __getitem__(self, field: str) -> Answer:
        for answer in self.answers:
            if answer.field == field:
                return answer
        raise KeyError(field)

    @property
    def unmeasured(self) -> tuple[Answer, ...]:
        return tuple(a for a in self.answers if not a.is_measured)


def reading(backend: str, answers: Iterable[Answer], *, why: str = "") -> Reading:
    """Assemble a backend's column from whatever subset it could answer.

    This is the whole of the "no inheritance" design: a backend module is a
    handful of plain functions that return `Answer`s, and the fields it did not
    answer are filled in as `NOT MEASURED` rather than left blank or guessed.
    """
    if not backend.strip():
        raise ValueError("a column needs a backend name")
    seen: dict[str, Answer] = {}
    for answer in answers:
        _question(answer.field)
        if answer.field in seen:
            raise ValueError(
                f"{backend}: {answer.field} was answered twice; a cell has one value"
            )
        seen[answer.field] = answer
    default = why.strip() or "NOT MEASURED — this backend was not asked this question"
    return Reading(
        backend=backend,
        answers=tuple(
            seen.get(field, not_measured(field, default)) for field in FIELDS
        ),
    )


def cell(answer: Answer) -> str:
    """Render a cell so its evidence level cannot be dropped on the way out.

    AC2 says every cell carries one; the way that stops being true is somebody
    formatting the value by hand in the matrix.
    """
    if not answer.is_measured:
        return (
            answer.detail
            if answer.detail.startswith("NOT MEASURED")
            else (f"NOT MEASURED — {answer.detail}")
        )
    return f"{_render(answer.value)} — {answer.evidence}"


def downgrade(answer: Answer, evidence: Evidence, why: str) -> Answer:
    """Re-stamp an answer's evidence level, keeping the observation attached.

    For the case the emulator creates: floci measured it, so the value is real
    enough to record and can never back a shipped field (AC3).
    """
    if not answer.is_measured:
        raise ValueError(f"{answer.field}: an unmeasured cell has nothing to re-stamp")
    return replace(answer, evidence=evidence, detail=f"{answer.detail} [{why}]")


def _question(field: str) -> Question:
    try:
        return _BY_FIELD[field]
    except KeyError:
        raise ValueError(
            f"{field!r} is not a StoreProfile field; the ten are {FIELDS}"
        ) from None


def _check_shape(question: Question, value: AnswerValue) -> None:
    if question.shape == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"{question.field} is a bool; got {value!r}")
        return
    if question.shape == "fencing":
        if value not in FENCING_VALUES:
            raise ValueError(
                f"{question.field} is one of {FENCING_VALUES}; got {value!r}"
            )
        return
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(
            f"{question.field} is a positive byte count, or None for unbounded; "
            f"got {value!r}"
        )


def _render(value: AnswerValue) -> str:
    if value is None:
        return "unbounded"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)
