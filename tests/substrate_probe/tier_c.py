"""Tier C — Turso/libSQL and Supabase Postgres (FUN-25 5.1 / T11, T15, T16).

**Turso is measured. Supabase is not.** The two columns are in the same module
because they are the same tier, not because they are in the same state, and the
difference is the whole point of what follows.

## Turso — measured against the real service

Ten cells, `measured (real service)`, against a Turso Cloud database. Every
answer here came from an operation, and three of them were **re-derived rather
than ported** when the client changed — see `_turso_transaction_answers`, where
one answer reverses.

Run it with the credentials sourced and the client overlaid::

    set -a; . ~/.config/fun25/probe-tierc.env; set +a
    uv run --with libsql --with "psycopg[binary]" pytest -q \
        tests/substrate_probe/tier_c.py

That is the command that works today. The operator's runner
(`~/.config/fun25/run-probe.sh`) still overlays `libsql-client`, so
`PROBE_TIER_C=1` through the runner will **hang** on this column until that one
token is flipped — which is theirs to do, not this file's.

## The client finding, which is durable knowledge and not a footnote

This module used to import **`libsql-client` 0.3.1** (last release 2024-05-03,
upstream archived). Against Turso Cloud it fails its Hrana WebSocket
handshake — `WSServerHandshakeError: 400, message='Invalid response status'` —
**and then retries forever**, so the column did not fail, it *hung*, and a
`timeout` had to kill the run.

Two things follow, and both matter more than the fix:

1. **That was a client finding, never a service finding.** The service
   answered and the credential authorised; only the abandoned client could not
   speak to them. Anyone reading the old hang as "Turso is unreachable" would
   have drawn the opposite conclusion from the evidence.
2. **A probe run must terminate.** A measurement that never returns is worse
   than one that fails, because a failure is a result. Every remote call below
   is bounded (`_TIMEOUT`, `_CHILD_TIMEOUT`) and there is no retry loop
   anywhere in this file.

The maintained client is **`libsql` 0.1.11**, and it is `sqlite3`-shaped:
`connect(database=…, auth_token=…)`, `execute`, `commit`, `rollback`,
`in_transaction`, `cursor().rowcount`. It has no `batch()`. That is why the
answers had to be re-derived: the old code reasoned from `batch()`'s existence
to a conclusion this client's shape does not support.

## Supabase — not measured, and for two separate reasons

Cheap means free of credentials, free of spend **and free of new dependencies**.
`psycopg` is not declared by any first-party package and `SUPABASE_DB_URL` is
not set, so the column is `NOT MEASURED` and the module's job is to say
**exactly which** — a dependency decision and an account are different prices,
and a column reading "unavailable" would hide which one is owed.

`_supabase_answers()` is still marked `# TRANSITIONAL(T11)` because it has
still never executed. `_turso_answers()` is **not** marked, because it has.
That distinction is the only honest way to write this file.

## Nothing stands in for either service

Stdlib `sqlite3` is not libSQL — that is the local SQLite column, already
measured in Tier A — and an embedded libSQL file is not the Turso *service*, so
neither could carry a `measured (real service)` row. Substituting either would
produce a green run that measured something nobody asked about, which is the
failure `plugins/credentials/functualize-aws/tests/test_integration_floci.py:17-19`
names and this ticket inherited. A test below asserts there is no route through
this module that reaches a measured cell without a client and an account.
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pytest

from tests.substrate_probe.conftest import missing_env
from tests.substrate_probe.harness import (
    Answer,
    Evidence,
    Reading,
    measured,
    reading,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

REAL_SERVICE: Final[Evidence] = "measured (real service)"

#: Sizes walked upward until something refuses one. Never a documented cap.
_SIZES: Final[tuple[int, ...]] = (64 * 1024, 1024 * 1024, 8 * 1024 * 1024)

#: Every remote call is bounded, and that is a requirement rather than caution.
#: The client this module used to import retried a failed handshake *forever*,
#: so the Turso column did not fail — it hung, and a `timeout` had to kill it.
#: A measurement that never returns is worse than one that fails, because a
#: failure is a result and a hang is not.
_TIMEOUT: Final[float] = 15.0

#: The child in the two-process question, bounded the same way.
_CHILD_TIMEOUT: Final[float] = 90.0

#: The second process. A real OS process rather than a thread, because
#: "two processes can share this" is the question, and two threads in one
#: interpreter would answer a different one. It reads what the parent
#: committed and writes through a compare-and-swap on the same row.
_CHILD: Final[str] = """
import os
import libsql

conn = libsql.connect(
    database=os.environ["TURSO_DATABASE_URL"],
    auth_token=os.environ["TURSO_AUTH_TOKEN"],
    timeout=15.0,
)
conn.execute("UPDATE {table} SET v='child' WHERE k='state' AND rev='r0'")
conn.commit()
conn.close()
"""


@dataclass(frozen=True, slots=True)
class Backend:
    """A Tier C column: what it is called, what reaches it, what unlocks it.

    `client` is the module name an import reaches for; `distribution` is the
    name a package manifest would have to declare. They coincide for both
    backends today (`libsql`, `psycopg`), but they are kept apart because they
    answer different questions — importability is about a host, declaration is
    about this project — and the earlier client, `libsql-client`, was a case
    where they differed.
    """

    label: str
    client: str
    distribution: str
    variables: tuple[str, ...]


TURSO: Final[Backend] = Backend(
    "Turso / libSQL",
    "libsql",
    "libsql",
    ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN"),
)
SUPABASE: Final[Backend] = Backend(
    "Supabase Postgres", "psycopg", "psycopg", ("SUPABASE_DB_URL",)
)


@dataclass(frozen=True, slots=True)
class Gap:
    """What is missing, kept apart so the matrix can say which.

    Both causes are reported when both apply. Collapsing them would tell a
    reader that Tier C is "unavailable" and leave them unable to act: one of
    these is unblocked by a dependency decision, the other by an account, and
    they are not the same conversation.
    """

    backend: Backend
    client_absent: bool
    absent_variables: tuple[str, ...]

    @property
    def blocked(self) -> bool:
        return self.client_absent or bool(self.absent_variables)

    @property
    def reason(self) -> str:
        causes: list[str] = []
        detail: list[str] = []
        if self.client_absent:
            causes.append("client absent")
            detail.append(
                f"`import {self.backend.client}` fails and no first-party package "
                f"declares it, so adding it is a dependency decision rather than a "
                f"probe run"
            )
        if self.absent_variables:
            causes.append("no credentials")
            detail.append(
                f"{', '.join(self.absent_variables)} not set in the environment"
            )
        return (
            f"NOT MEASURED ({', '.join(causes)}) — "
            + "; ".join(detail)
            + f". The probe does not fall back to a fake and nothing local stands in "
            f"for {self.backend.label}; the variable names are declared in "
            f".env.example."
        )


def importable(module: str) -> bool:
    """Is the client there? Asked without importing it, so nothing runs."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def gap_for(
    backend: Backend,
    *,
    client_absent: bool | None = None,
    absent_variables: Sequence[str] | None = None,
) -> Gap:
    """What stands between this host and a measurement of `backend`.

    The overrides exist so the routing can be asserted on a host where the
    answer never varies: here both clients are absent and both credential sets
    are empty, so without them three of the four cases would be unreachable and
    the distinction the matrix depends on would go unchecked.
    """
    return Gap(
        backend=backend,
        client_absent=(
            not importable(backend.client) if client_absent is None else client_absent
        ),
        absent_variables=(
            missing_env(*backend.variables)
            if absent_variables is None
            else tuple(absent_variables)
        ),
    )


TURSO_GAP: Final[Gap] = gap_for(TURSO)
SUPABASE_GAP: Final[Gap] = gap_for(SUPABASE)

#: Decided at module level, before any client is constructed (AC5). Applied to
#: the measurement tests rather than as a module-wide skip, for the reason
#: recorded in wave 3's deviation: an aborted import would leave
#: `turso_column()` unimportable and T12's matrix short two columns, and the
#: done-when's other half — "each carries an explicit `NOT MEASURED` reason" —
#: would have no data behind it.
requires_turso = pytest.mark.skipif(TURSO_GAP.blocked, reason=TURSO_GAP.reason)
requires_supabase = pytest.mark.skipif(SUPABASE_GAP.blocked, reason=SUPABASE_GAP.reason)


def _real(field: str, value: Any, detail: str) -> Answer:
    return measured(field, value, evidence=REAL_SERVICE, detail=detail)


def _turso_answers() -> tuple[Answer, ...]:
    """Turso Cloud over the maintained libSQL client, measured.

    **This has executed.** It was written against `libsql` 0.1.11 and run
    against the real service, which is why nothing here is marked transitional
    — unlike `_supabase_answers()` below, which still has not run.

    The answers are re-derived rather than ported. The client this module used
    to import, `libsql-client`, offered `batch()` and no transaction handle, so
    the old code reasoned *the atomic unit is one batched request, therefore a
    transaction cannot be held open*. This client is `sqlite3`-shaped —
    `BEGIN`, `commit()`, `rollback()`, `in_transaction` — so that inference had
    to be redone against what the client can actually do, and one answer
    changed sign because of it.
    """
    import libsql

    conn = libsql.connect(
        database=os.environ["TURSO_DATABASE_URL"],
        auth_token=os.environ["TURSO_AUTH_TOKEN"],
        timeout=_TIMEOUT,
    )
    table = f"fun25_probe_{uuid.uuid4().hex[:8]}"
    try:
        conn.execute(f"CREATE TABLE {table} (k TEXT PRIMARY KEY, v TEXT, rev TEXT)")
        conn.execute(f"INSERT INTO {table} VALUES ('state', '0', 'r0')")
        conn.commit()
        return (
            *_turso_transaction_answers(conn, table),
            *_turso_reach_answers(conn, table),
            _turso_fencing_answer(conn, table),
            _turso_size_answer(conn, table),
            _turso_schema_answer(conn, table),
        )
    finally:
        with contextlib.suppress(Exception):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
            conn.commit()
        with contextlib.suppress(Exception):
            conn.close()


def _turso_transaction_answers(conn: Any, table: str) -> tuple[Answer, ...]:
    """Hold a transaction open across a Python decision, then across a failure.

    Three observations, in one place because they are one mechanism:

    * a transaction is opened, a row is read *inside* it, Python decides what to
      write from what it read, the write happens in the same unit and is
      visible there — then a rollback puts the value back;
    * two different keys are written in one unit with the second doomed, and
      after the rollback the **sibling is gone too**;
    * and the sharp edge — a failed statement does **not** roll the unit back
      by itself. Commit anyway and the sibling survives. The guarantee is real
      and it is the application's to invoke.
    """
    before = conn.execute(f"SELECT v FROM {table} WHERE k='state'").fetchone()
    conn.execute("BEGIN")
    held = conn.in_transaction
    seen = conn.execute(f"SELECT v FROM {table} WHERE k='state'").fetchone()
    decided = "1" if seen and seen[0] == "0" else "unexpected"
    conn.execute(f"UPDATE {table} SET v='{decided}' WHERE k='state'")
    inside = conn.execute(f"SELECT v FROM {table} WHERE k='state'").fetchone()
    conn.rollback()
    after = conn.execute(f"SELECT v FROM {table} WHERE k='state'").fetchone()
    interactive = bool(held) and inside != before and after == before

    conn.execute("BEGIN")
    conn.execute(f"INSERT INTO {table} VALUES ('outbox', '1', 'r1')")
    try:
        conn.execute(f"INSERT INTO {table} VALUES ('state', '9', 'r9')")
        doomed = "was accepted"
    except Exception as refused:  # noqa: BLE001 - the refusal is the measurement
        doomed = f"raised {type(refused).__name__}"
        conn.rollback()
    orphans = conn.execute(f"SELECT count(*) FROM {table} WHERE k='outbox'").fetchone()[
        0
    ]
    atomic = orphans == 0

    conn.execute("BEGIN")
    conn.execute(f"INSERT INTO {table} VALUES ('outbox2', '1', 'r1')")
    with contextlib.suppress(Exception):
        conn.execute(f"INSERT INTO {table} VALUES ('state', '9', 'r9')")
    conn.commit()
    survives = conn.execute(
        f"SELECT count(*) FROM {table} WHERE k='outbox2'"
    ).fetchone()[0]

    unit = (
        f"two keys written in one transaction with the second doomed by the primary "
        f"key ({doomed}); after the rollback the sibling row is "
        f"{'gone' if atomic else 'still there'} ({orphans} row(s))"
    )
    caveat = (
        f"the sharp edge, measured rather than assumed: a failed statement does not "
        f"roll the unit back by itself — committing anyway leaves {survives} sibling "
        f"row(s) behind. The guarantee is real and it is the caller's to invoke"
    )
    return (
        _real("cross_aggregate_atomicity", atomic, f"{unit}. {caveat}"),
        _real(
            "durable_outbox",
            atomic,
            f"the sibling above is an outbox row in all but name: {unit}",
        ),
        _real(
            "interactive_transaction",
            interactive,
            f"BEGIN opened a unit (in_transaction={held}), a read inside it returned "
            f"{before!r}, Python chose {decided!r} from that, the write was visible "
            f"inside the same unit as {inside!r}, and a rollback restored {after!r}. "
            f"**This reverses the answer the archived client's shape implied**: that "
            f"client had batch() and no transaction handle, so the old reasoning was "
            f"'the atomic unit is one request, therefore nothing can be held open'. "
            f"This client holds one open",
        ),
    )


def _turso_reach_answers(conn: Any, table: str) -> tuple[Answer, ...]:
    """One round trip, and a real second OS process against the same database."""
    started = time.perf_counter()
    conn.execute("SELECT 1").fetchall()
    elapsed = (time.perf_counter() - started) * 1000

    child = subprocess.run(  # noqa: S603 - our own interpreter, our own source
        [sys.executable, "-c", _CHILD.format(table=table)],
        capture_output=True,
        text=True,
        timeout=_CHILD_TIMEOUT,
        check=False,
    )
    seen = conn.execute(f"SELECT v FROM {table} WHERE k='state'").fetchone()
    shared = child.returncode == 0 and seen is not None and seen[0] == "child"
    crossing = (
        f"a second OS process connected to the same URL, read the row this process "
        f"had committed, wrote to it, and this process now reads {seen!r} "
        f"(child exit {child.returncode})"
    )
    return (
        _real(
            "remote",
            True,
            f"a SELECT 1 round trip took {elapsed:.0f}ms; every statement crosses a "
            f"socket, so a read-modify-write loop pays this per step",
        ),
        _real("multi_machine", True, f"addressed by URL, not by a path: {crossing}"),
        _real("multi_process", shared, crossing),
        _real(
            "offline_capable",
            False,
            "that socket is the only way to reach it; there is no local replica in "
            "this configuration, so with the network gone there is nothing to read",
        ),
    )


def _turso_fencing_answer(conn: Any, table: str) -> Answer:
    """A compare-and-swap on a revision column, and its row count."""
    cur = conn.cursor()
    cur.execute(f"UPDATE {table} SET v='z' WHERE k='state' AND rev='wrong'")
    stale = cur.rowcount
    cur.execute(f"UPDATE {table} SET v='z' WHERE k='state' AND rev='r0'")
    fresh = cur.rowcount
    conn.commit()
    return _real(
        "fencing",
        "cross-process" if stale == 0 and fresh == 1 else "none",
        f"an UPDATE carrying a stale revision matched {stale} row(s) and the same "
        f"UPDATE carrying the current one matched {fresh}; the comparison is made by "
        f"the service, so it excludes any writer anywhere rather than any writer in "
        f"this process",
    )


def _turso_size_answer(conn: Any, table: str) -> Answer:
    """Write values of increasing size until one is refused."""
    accepted = 0
    for size in _SIZES:
        try:
            conn.execute(
                f"INSERT OR REPLACE INTO {table} VALUES (?, ?, ?)",
                (f"big-{size}", "x" * size, "r"),
            )
            conn.commit()
        except Exception as refused:  # noqa: BLE001 - a refusal is the answer
            return _real(
                "max_document_bytes",
                accepted or None,
                f"{size} bytes was refused ({type(refused).__name__}); {accepted} "
                f"bytes was accepted immediately before it",
            )
        accepted = size
    return _real(
        "max_document_bytes",
        None,
        f"nothing refused a value up to {accepted} bytes, the largest this probe "
        f"attempted — no cap was observed in the range walked, which is not the same "
        f"as no cap existing",
    )


def _turso_schema_answer(conn: Any, table: str) -> Answer:
    """Store a payload announcing a version and see whether anything objects."""
    conn.execute(
        f"INSERT OR REPLACE INTO {table} VALUES ('v1', '{{\"schema_version\": 1}}', 'r')"
    )
    conn.commit()
    stored = conn.execute(f"SELECT v FROM {table} WHERE k='v1'").fetchone()
    return _real(
        "versioned_migrations",
        False,
        f"a payload announcing its own schema version was stored and read back "
        f"unchanged ({stored[0] if stored else None!r}); the table carries the columns "
        f"it was created with and nothing declares a version for the service to enforce",
    )


def _supabase_answers() -> tuple[Answer, ...]:
    """Supabase Postgres over psycopg.

    # TRANSITIONAL(T11): never executed — `psycopg` is not installed and is not
    # declared by any first-party package. As above: documented surface, not a
    # measured one, and the first real run should expect to correct it.
    """
    import psycopg

    table = f"fun25_probe_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(os.environ["SUPABASE_DB_URL"]) as conn:
        conn.execute(f"CREATE TABLE {table} (k text primary key, v text, rev text)")

        started = time.perf_counter()
        conn.execute("SELECT 1")
        elapsed = (time.perf_counter() - started) * 1000

        held = False
        try:
            with conn.transaction():
                conn.execute(f"INSERT INTO {table} (k, v, rev) VALUES ('a', '1', 'r1')")
                seen = conn.execute(f"SELECT v FROM {table} WHERE k = 'a'").fetchone()
                held = seen is not None
                raise _RollbackError
        except _RollbackError:
            pass
        rolled_back = (
            conn.execute(f"SELECT count(*) FROM {table}").fetchone() or (0,)
        )[0] == 0

        conn.execute(f"INSERT INTO {table} (k, v, rev) VALUES ('a', '1', 'r1')")
        stale = conn.execute(
            f"UPDATE {table} SET v = '2' WHERE k = 'a' AND rev = 'wrong'"
        )
        fenced = stale.rowcount == 0

        accepted = 0
        refused_at: int | None = None
        refusal: object = None
        for size in _SIZES:
            try:
                conn.execute(
                    f"INSERT INTO {table} (k, v, rev) VALUES (%s, %s, 'r')",
                    (f"big-{size}", "x" * size),
                )
            except Exception as bounced:  # noqa: BLE001 - a refusal is the answer
                refused_at, refusal = size, bounced
                break
            accepted = size
        conn.execute(f"DROP TABLE {table}")

    unit = (
        f"a transaction was opened, a row inserted, the row read back inside it "
        f"({'visible' if held else 'not visible'}), a Python decision taken, and the "
        f"transaction rolled back — afterwards the table held "
        f"{'no rows' if rolled_back else 'the row'}"
    )
    size_detail = (
        f"{refused_at} bytes was refused ({refusal}); {accepted} bytes was accepted "
        "immediately before it"
        if refused_at is not None
        else f"nothing refused a value up to {accepted} bytes, the largest attempted"
    )
    return (
        _real("interactive_transaction", held and rolled_back, unit),
        _real("cross_aggregate_atomicity", rolled_back, unit),
        _real("durable_outbox", rolled_back, f"follows from the unit above: {unit}"),
        _real(
            "fencing",
            "cross-process" if fenced else "none",
            "an UPDATE carrying a stale revision affected "
            f"{'no rows' if fenced else 'a row'}; the check is the server's",
        ),
        _real("remote", True, f"a SELECT 1 round trip took {elapsed:.0f}ms"),
        _real("multi_machine", True, "addressed by a connection string, not a path"),
        _real("multi_process", True, "any process holding the DSN can connect"),
        _real("offline_capable", False, "the connection is the only way to reach it"),
        _real(
            "max_document_bytes", None if refused_at is None else accepted, size_detail
        ),
        _real(
            "versioned_migrations",
            False,
            "the table carries the columns it was created with; Postgres has a "
            "schema but nothing here declares a *version* for it to enforce",
        ),
    )


class _RollbackError(Exception):
    """Leaves the transaction above without committing it."""


def _column(backend: Backend, gap: Gap) -> Reading:
    """Ten measured cells, or ten stated reasons there are none."""
    if gap.blocked:
        return reading(backend.label, [], why=gap.reason)
    answers = _turso_answers() if backend is TURSO else _supabase_answers()
    return reading(backend.label, answers)


def turso_column() -> Reading:
    return _column(TURSO, TURSO_GAP)


def supabase_column() -> Reading:
    return _column(SUPABASE, SUPABASE_GAP)


def tier_c_columns() -> tuple[Reading, Reading]:
    """The seventh column and the eighth, in the order `spec.md` names them."""
    return turso_column(), supabase_column()


def test_no_tier_c_column_is_measured_while_its_credentials_are_absent() -> None:
    """5.1's done-when: an explicit reason each, decided from this environment.

    The first version of this test asserted the reasons *about the host* — that
    neither client was importable — which is true in CI and false under the
    runner's overlay. What the done-when needs is that each column carries its
    reasons, and which causes those reasons name is read from the environment
    rather than from what happens to be installed here.
    """
    for gap, column in (
        (TURSO_GAP, turso_column()),
        (SUPABASE_GAP, supabase_column()),
    ):
        assert len(column.answers) == 10
        if not gap.blocked:
            continue  # a client *and* an account: the skip-gated test measures
        assert len(column.unmeasured) == 10
        assert [answer.detail for answer in column.answers] == [gap.reason] * 10
        assert gap.reason.startswith("NOT MEASURED (")
        assert "does not fall back to a fake" in gap.reason


def test_neither_client_is_declared_by_a_first_party_package() -> None:
    """The project fact the host check was groping for, said about the project.

    Both clients are reachable on the runner's host through `run-probe.sh`'s
    ephemeral overlay, so "importable here" would say nothing about what this
    project depends on — and the overlay is deliberate: declaring an archived
    client would commit the repository to it. Read from the manifests, this
    holds in all three environments this file runs in: CI, a bare host, and the
    runner's host with the overlay on it.
    """
    root = Path(__file__).resolve().parents[2]
    manifests = [
        root / "pyproject.toml",
        *sorted(root.glob("plugins/*/*/pyproject.toml")),
    ]
    assert len(manifests) > 1, "no first-party manifest was read, so nothing checked"

    for backend in (TURSO, SUPABASE):
        declaring = [
            str(path.relative_to(root))
            for path in manifests
            if backend.distribution in path.read_text(encoding="utf-8")
        ]
        assert declaring == [], (
            f"{backend.distribution} is declared by {declaring}. The probe reaches "
            f"it through an ephemeral overlay instead, so that the project does not "
            f"depend on it — see the matrix's Tier C section."
        )


def test_nothing_local_stands_in_for_either_service() -> None:
    """Stdlib `sqlite3` is not libSQL, and no file is the Turso service.

    The temptation is real and cheap — this host has a working SQLite — and
    taking it would produce a green run of the column Tier A already holds.

    Credentials absent is asserted **without consulting the gap**, and that is
    the point: a substitution that also retired the client check (the natural
    wiring: "no client, use a local engine, so stop calling it blocked") would
    take any test that trusted `gap.blocked` down with it. This one asks the
    environment directly, so no local engine can reach a measured cell here.
    """
    for backend, column in (
        (TURSO, turso_column()),
        (SUPABASE, supabase_column()),
    ):
        if not missing_env(*backend.variables):
            continue  # a credentialed host measures these; the skips below cover that
        assert [answer for answer in column.answers if answer.is_measured] == []
        assert {answer.value for answer in column.answers} == {None}


def test_the_two_causes_are_never_collapsed_into_one() -> None:
    """A missing dependency and a missing account are different findings.

    One is unblocked by a decision this ticket may not take, the other by an
    account; a matrix that said only "unavailable" would leave a reader unable
    to tell which, and both apply here at once.
    """
    both = gap_for(TURSO, client_absent=True, absent_variables=TURSO.variables)
    assert both.blocked
    assert "client absent, no credentials" in both.reason
    assert "TURSO_DATABASE_URL, TURSO_AUTH_TOKEN" in both.reason

    client_only = gap_for(TURSO, client_absent=True, absent_variables=())
    assert client_only.reason.startswith("NOT MEASURED (client absent)")
    assert "TURSO_DATABASE_URL" not in client_only.reason

    credentials_only = gap_for(
        SUPABASE, client_absent=False, absent_variables=("SUPABASE_DB_URL",)
    )
    assert credentials_only.reason.startswith("NOT MEASURED (no credentials)")
    assert "psycopg" not in credentials_only.reason

    ready = gap_for(SUPABASE, client_absent=False, absent_variables=())
    assert not ready.blocked


@requires_turso
def test_turso_is_measured_when_client_and_credentials_arrive() -> None:
    """Skipped until a libSQL client *and* Turso credentials are both present.

    The client arrives through the runner's ephemeral overlay rather than a
    declaration; the credentials are the part only an account can supply.
    """
    column = turso_column()
    assert column.unmeasured == ()
    assert {answer.evidence for answer in column.answers} == {REAL_SERVICE}


@requires_supabase
def test_supabase_is_measured_when_client_and_credentials_arrive() -> None:
    """Skipped until a psycopg client *and* `SUPABASE_DB_URL` are both present."""
    column = supabase_column()
    assert column.unmeasured == ()
    assert {answer.evidence for answer in column.answers} == {REAL_SERVICE}
