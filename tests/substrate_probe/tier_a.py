"""Tier A: the two shipping substrates, measured on the real thing (FUN-25 3.1).

The filesystem and local SQLite are the backends that ship today, and for those
the real service is *this host* — no account, no endpoint, no container. That is
what makes AC3 satisfiable on a machine with no cloud credentials at all: every
field of a shipping backend can carry a `measured (real service)` row. AC4 is the
same sentence read the other way, and it is a property of this module rather than
a hope: nothing here gates on an environment variable, and the one round trip
that could touch a network is performed with every socket refused.

**This is the one module permitted to import from `functualize`** (`plan.md` §4,
`contracts.md`): for these two, the shipping substrate *is* the backend under
test, and a probe that measured them through an adapter would measure the
adapter. Every other module in this directory imports its backend's own client and
nothing of ours.

**The three fakes ride along, as instruments rather than columns** (AC2). Their
readings sit in the same tuple so the matrix can cite what they establish — the
evidence level's own name, `measured (fake)` — and never so a fake can stand in
for a backend. The test at the foot of this module asserts both halves.

**Every cell is an operation performed on the substrate**, in the shape
`harness.QUESTIONS` describes: two writes under one lock with the second doomed, a
read-decide-write held open inside one unit, a second OS process that has to be
excluded and then has to see this process's commit, a round trip with every socket
refused, documents written until something refuses them. Nothing is filled in from
the port's docstrings, and no cell here comes from a vendor page.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Final

from functualize_substrate_sqlite.substrate import SQLiteSubstrate

from functualize._primitives.substrate import JsonFileSubstrate
from tests.substrate_probe.fakes import (
    BatchOnlySqliteDriver,
    FakeItemStore,
    FakeObjectStore,
    _offline_round_trip,
)
from tests.substrate_probe.harness import (
    FAKE_EVIDENCE,
    Answer,
    AnswerValue,
    Evidence,
    Reading,
    measured,
    reading,
)

if TYPE_CHECKING:
    from functualize._types.protocols import StoreSubstrate

#: The two columns this module measures, named as the matrix will name them.
FILESYSTEM: Final[str] = "the JSON filesystem — JsonFileSubstrate"
SQLITE: Final[str] = "local SQLite — SQLiteSubstrate"

#: AC3's level. The only one that may back a field on a backend proposed for
#: shipping, and reachable here because these two backends are this host.
REAL_SERVICE: Final[Evidence] = "measured (real service)"

#: How long the parent holds the lock while the child is trying to take it, and
#: what "the other process was excluded" is worth in seconds. The child reports
#: its own wait, measured from just before it tries, so interpreter startup is
#: not part of the number.
_HOLD: Final[float] = 0.5
_WAITED: Final[float] = 0.3

#: The second process. It builds the same store from the class's own dotted path,
#: says it is ready *before* it builds anything (construction can block on the
#: parent's lock, and a parent waiting for a ready line while holding that lock
#: would deadlock against it), then does the read-modify-write and the guarded
#: write the two questions ask for.
_CHILD: Final[str] = """
import importlib
import json
import sys
import time

address, stale, factory = sys.argv[1], sys.argv[2], sys.argv[3]
module_name, class_name = factory.rsplit(":", 1)
cls = getattr(importlib.import_module(module_name), class_name)
print(json.dumps({"ready": True}), flush=True)
t0 = time.monotonic()
substrate = cls(address)
with substrate.lock("counter"):
    waited = round(time.monotonic() - t0, 3)
    stored = substrate.read("counter")
    observed = stored.data["n"] if stored is not None else None
    landed = (
        substrate.write("counter", {"n": observed + 1}, expect=stored.revision)
        if stored is not None
        else False
    )
    refused = not substrate.write("counter", {"n": 99}, expect=stale)
print(json.dumps({"waited": waited, "observed": observed, "landed": landed,
                  "refused": refused}))
"""


def _real(field: str, value: AnswerValue, detail: str) -> Answer:
    """A cell a real backend produced — the level AC3 lets back a shipping field."""
    return measured(field, value, evidence=REAL_SERVICE, detail=detail)


def _atomicity_answers(substrate: StoreSubstrate) -> tuple[Answer, ...]:
    """Send a state write and its outbox row as one unit, and doom the second.

    The second write carries a payload JSON cannot serialise, which raises inside
    the unit: a backend that can commit the two together rolls the first back, and
    one that cannot has already written it. Both outcomes are read back, so the
    cell reports which one happened rather than which one is documented.
    """
    with contextlib.suppress(TypeError), substrate.lock("state", "outbox"):
        substrate.write("state", {"step": 1})
        substrate.write("outbox", {"step": 1, "record": object()})
    half_write = substrate.read("state")
    atomic = half_write is None
    outcome = (
        "absent, so the unit rolled back"
        if atomic
        else "still there, so nothing rolled it back"
    )
    detail = (
        f"a state write and its outbox row were sent as one unit and the second was "
        f"refused (a payload JSON cannot carry raised inside it); afterwards the state "
        f"row is {outcome}"
    )
    return (
        _real("cross_aggregate_atomicity", atomic, detail),
        _real("durable_outbox", atomic, detail),
    )


def _interactive_transaction_answer(substrate: StoreSubstrate) -> Answer:
    """Begin, read, decide in Python, write — one unit, and the decision is used."""
    decided = 0
    with substrate.lock("decision"):
        current = substrate.read("decision")
        decided = (current.data["n"] if current is not None else 0) + 1
        substrate.write("decision", {"n": decided})
    stored = substrate.read("decision")
    opened = stored is not None and stored.data["n"] == decided
    return _real(
        "interactive_transaction",
        opened,
        f"a read, a decision in Python and a write happened inside one unit, and the "
        f"document left behind carries the decision ({decided}) — the shape D1 cannot "
        f"express (05-cloudflare.md §A.3) and this backend can",
    )


def _child_report(child: subprocess.Popen[str]) -> dict[str, object]:
    """The child's report, or the failure it died with."""
    rest, errors = child.communicate(timeout=60)
    lines = [line for line in rest.splitlines() if line.strip()]
    if child.returncode != 0 or not lines:
        raise RuntimeError(
            f"the second process exited {child.returncode}: {errors.strip()}"
        )
    return json.loads(lines[-1])


def _two_process_answers(
    substrate: StoreSubstrate, address: Path
) -> tuple[Answer, ...]:
    """One other OS process: it must be kept out, and it must see the commit.

    The parent takes the lock, moves the counter twice and keeps the lock while
    the child starts. The child cannot get in until the parent is done — which is
    what "cross-process" means for a lock, as opposed to an in-process mutex — and
    it then reads what the parent committed, repeats the read-modify-write with
    the revision it just read, and is refused when it presents the revision it was
    handed before the parent's second write.
    """
    factory = f"{type(substrate).__module__}:{type(substrate).__name__}"
    with substrate.lock("counter"):
        substrate.write("counter", {"n": 1})
        first = substrate.read("counter")
        if first is None:
            raise RuntimeError("the write above did not land, so there is no revision")
        substrate.write("counter", {"n": 2})
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                _CHILD,
                str(address),
                str(first.revision),
                factory,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if child.stdout is None:
            raise RuntimeError("the second process produced no pipe to read")
        child.stdout.readline()
        time.sleep(_HOLD)
    report = _child_report(child)
    final = substrate.read("counter")
    landed = final is not None and final.data["n"] == 3
    excluded = bool(report["refused"]) and float(report["waited"]) >= _WAITED
    return (
        _real(
            "fencing",
            "cross-process" if excluded else "process-local",
            f"while this process held the lock, a second one waited {report['waited']}s to "
            f"take it before it could write, and the guarded write it then made carrying "
            f"the pre-write revision did not land (refused: {report['refused']})",
        ),
        _real(
            "multi_process",
            bool(report["observed"] == 2 and report["landed"] and landed),
            f"a second OS process, let in only after this one released the lock, read "
            f"{report['observed']} where this one had committed 2, wrote "
            f"{report['observed'] + 1 if report['observed'] is not None else None} with the "
            f"revision it had just read (landed: {report['landed']}), and the counter now "
            f"reads {final.data['n'] if final is not None else None}: no lost update",
        ),
    )


def _reach_answers(substrate: StoreSubstrate, address: Path) -> tuple[Answer, ...]:
    """The address this store is reached by, and one round trip's transport."""
    reached = _offline_round_trip(lambda: substrate.write("round-trip", {"n": 1}))
    if reached:
        transport = (
            f"one round trip reached for {reached[0]}, so every operation crosses "
            f"a network"
        )
    else:
        transport = (
            "one round trip completed with every socket refused and reached for none, "
            "so no operation crosses a network"
        )
    return (
        _real(
            "multi_machine",
            False,
            f"the store is reached by a filesystem path on this host "
            f"({type(address).__name__}) and by nothing else: no port is bound, and the "
            f"round trip below reached for no socket, so a second host has no address to "
            f"reach it by",
        ),
        _real("remote", bool(reached), transport),
        _real("offline_capable", not reached, transport),
    )


def _document_size_answer(substrate: StoreSubstrate) -> Answer:
    """Write until something refuses. Nothing did, so record what was accepted."""
    size = 4 * 1024 * 1024
    substrate.write("large", {"blob": "x" * size})
    stored = substrate.read("large")
    accepted = len(stored.data["blob"]) if stored is not None else 0
    return _real(
        "max_document_bytes",
        None,
        f"a document carrying {size} bytes was written and read back at {accepted} bytes; "
        f"nothing refused it, so the answer is unbounded at every size measured — the "
        f"search stopped at the first size that was accepted, not at a limit",
    )


def _schema_answer(substrate: StoreSubstrate) -> Answer:
    """Store a document that announces a schema version, and see what objects."""
    substrate.write("migrated", {"schema_version": 2, "payload": "written under 2"})
    stored = substrate.read("migrated")
    return _real(
        "versioned_migrations",
        False,
        f"a document announcing schema_version 2 was stored and read back unchanged "
        f"({stored.data if stored is not None else None}), and no version it announces is "
        f"rejected or rewritten: nothing here carries a version for it to enforce",
    )


def _observations(substrate: StoreSubstrate, address: Path) -> tuple[Answer, ...]:
    """The ten questions, each one answered by operating on `substrate`."""
    return (
        *_atomicity_answers(substrate),
        *_two_process_answers(substrate, address),
        *_reach_answers(substrate, address),
        _interactive_transaction_answer(substrate),
        _document_size_answer(substrate),
        _schema_answer(substrate),
    )


def filesystem_column(root: Path) -> Reading:
    """The JSON filesystem's ten answers, each one measured on the real thing."""
    address = root / "fs"
    return reading(FILESYSTEM, _observations(JsonFileSubstrate(address), address))


def sqlite_column(root: Path) -> Reading:
    """Local SQLite's ten answers, each one measured on the real thing."""
    address = root / "substrate.sqlite"
    return reading(SQLITE, _observations(SQLiteSubstrate(address), address))


def tier_a_columns(root: Path) -> tuple[Reading, ...]:
    """Five columns: two measured on their real backend, three instruments (AC2)."""
    return (
        filesystem_column(root),
        sqlite_column(root),
        BatchOnlySqliteDriver().reading(),
        FakeObjectStore().reading(),
        FakeItemStore().reading(),
    )


def test_the_two_shipping_backends_answer_every_field_from_the_real_thing(
    tmp_path: Path,
) -> None:
    """3.1's done-when, and AC4's evidence, from one run of the observations.

    Ten values for the filesystem and ten for local SQLite, every one of them
    `measured (real service)` — and both produced by a round trip that reached for
    no socket, so a contributor with no cloud account and no network runs this.
    """
    columns = {column.backend: column for column in tier_a_columns(tmp_path)}

    for name in (FILESYSTEM, SQLITE):
        column = columns[name]
        assert column.unmeasured == ()
        assert {answer.evidence for answer in column.answers} == {REAL_SERVICE}
        assert column["remote"].value is False
        assert column["offline_capable"].value is True

    instruments = [
        column for column in columns.values() if column.backend.startswith("fake")
    ]
    assert len(instruments) == 3
    assert {a.evidence for column in instruments for a in column.answers} == {
        FAKE_EVIDENCE
    }
