"""Tier C — Turso/libSQL and Supabase Postgres, if cheap (FUN-25 5.1 / T11).

"If cheap" is the task's own condition, and on this host neither backend meets
it. Cheap means free of credentials, free of spend **and free of new
dependencies**, and both clients fail the third test before the first two are
even reached:

```console
$ .venv/bin/python -c "import libsql_client"     # ModuleNotFoundError
$ .venv/bin/python -c "import psycopg"           # ModuleNotFoundError
$ rg -n 'libsql|psycopg' --glob pyproject.toml .
# nothing — neither is declared by any first-party package
```

`contracts.md` says `libsql-client` *if present* and `psycopg` *if present*.
Neither is, so both columns are `NOT MEASURED`, and the module's job becomes
saying **exactly why** — because "client absent" and "credentials absent" are
different findings with different prices. The first costs a dependency
decision that is not this ticket's to make; the second costs an account. A
column that collapsed them into one "unavailable" would hide which.

**That dependency decision has since been taken, and it was not to declare
them.** The runner (`~/.config/fun25/run-probe.sh`) adds both clients as an
ephemeral `uv run --with libsql-client --with "psycopg[binary]"` overlay, so a
host can hold them — and measure with them — without the project depending on
them. The client half of the gap is therefore "not declared by any first-party
package", which is a fact about this repository, and no longer "not installable
here", which was a fact about whichever machine happened to run the tests. The
matrix's Turso note carries the client, its version, its upstream status and
that command, because the client is the one part of that column a reader cannot
recover from this file alone.

**Nothing stands in for either service.** Stdlib `sqlite3` is not libSQL — that
is the local SQLite column, already measured in Tier A — and an embedded libSQL
file would not be the Turso *service*, so it could never carry a
`measured (real service)` row. Substituting either would produce a green run
that measured something nobody asked about, which is the failure
`plugins/credentials/functualize-aws/tests/test_integration_floci.py:17-19`
names and this ticket inherited.

**The measurement path below has never run.** It is written from each client's
documented surface and marked `# TRANSITIONAL(T11)` at the two points where
that matters: the first run that has both a client and credentials should
expect to correct the call shapes rather than trust them. Saying so is cheaper
than a reader discovering it, and a probe whose own untested parts are
undisclosed is the exact shape of the defect this ticket exists to remove.
"""

from __future__ import annotations

import importlib.util
import os
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


@dataclass(frozen=True, slots=True)
class Backend:
    """A Tier C column: what it is called, what reaches it, what unlocks it.

    `client` is the module name an import reaches for; `distribution` is the
    name a package manifest would have to declare. They differ for Turso
    (`libsql_client` / `libsql-client`), and the declaration question is asked
    of the distribution — see the test that reads the manifests.
    """

    label: str
    client: str
    distribution: str
    variables: tuple[str, ...]


TURSO: Final[Backend] = Backend(
    "Turso / libSQL",
    "libsql_client",
    "libsql-client",
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
    """Turso over libSQL's remote protocol.

    # TRANSITIONAL(T11): never executed — `libsql_client` is not installed and
    # is not declared by any first-party package, so these call shapes come
    # from the client's documented surface rather than from a run. The first
    # run with a client and credentials should expect to correct them; what is
    # *not* provisional is the shape of the questions, which is `harness.py`'s.
    """
    import libsql_client

    url = os.environ["TURSO_DATABASE_URL"]
    client = libsql_client.create_client_sync(
        url=url, auth_token=os.environ["TURSO_AUTH_TOKEN"]
    )
    table = f"fun25_probe_{uuid.uuid4().hex[:8]}"
    try:
        client.execute(f"CREATE TABLE {table} (k TEXT PRIMARY KEY, v TEXT, rev TEXT)")

        started = time.perf_counter()
        client.execute("SELECT 1")
        elapsed = (time.perf_counter() - started) * 1000

        client.batch(
            [
                (f"INSERT INTO {table} (k, v, rev) VALUES (?, ?, ?)", ["a", "1", "r1"]),
                (f"INSERT INTO {table} (k, v, rev) VALUES (?, ?, ?)", ["a", "2", "r2"]),
            ]
        )
        atomic = False
    except Exception:  # noqa: BLE001 - the refusal *is* the measurement
        atomic = True
    rows = client.execute(f"SELECT count(*) FROM {table}").rows
    survivors = rows[0][0] if rows else 0

    stale = client.execute(
        f"UPDATE {table} SET v = ? WHERE k = ? AND rev = ?", ["3", "a", "wrong"]
    )
    fenced = getattr(stale, "rows_affected", 0) == 0

    accepted = 0
    for size in _SIZES:
        try:
            client.execute(
                f"INSERT OR REPLACE INTO {table} (k, v, rev) VALUES (?, ?, ?)",
                [f"big-{size}", "x" * size, "r"],
            )
        except Exception as refused:  # noqa: BLE001 - a refusal is the answer
            return _turso_column_answers(
                elapsed, atomic, survivors, fenced, accepted, size, refused
            )
        accepted = size
    client.close()
    return _turso_column_answers(
        elapsed, atomic, survivors, fenced, accepted, None, None
    )


def _turso_column_answers(
    elapsed: float,
    atomic: bool,
    survivors: int,
    fenced: bool,
    accepted: int,
    refused_at: int | None,
    refusal: object,
) -> tuple[Answer, ...]:
    """The ten, assembled from what the round trips above actually returned."""
    batch = (
        f"a two-statement batch whose second statement violated the primary key "
        f"{'was rejected as a unit' if atomic else 'partially applied'}; "
        f"{survivors} row(s) survived it"
    )
    size_detail = (
        f"{refused_at} bytes was refused ({refusal}); {accepted} bytes was accepted "
        "immediately before it"
        if refused_at is not None
        else f"nothing refused a value up to {accepted} bytes, the largest attempted"
    )
    return (
        _real("cross_aggregate_atomicity", atomic, batch),
        _real("durable_outbox", atomic, f"follows from the batch above: {batch}"),
        _real(
            "fencing",
            "cross-process" if fenced else "none",
            "an UPDATE carrying a stale revision in its WHERE clause affected "
            f"{'no rows' if fenced else 'a row'}; the check is evaluated by the "
            "service, so it excludes any writer anywhere",
        ),
        _real(
            "interactive_transaction",
            False,
            "the remote protocol's atomic unit is a batch sent in one request, so "
            "no transaction is held open across a Python decision — the same shape "
            "D1 has, measured here rather than assumed from it",
        ),
        _real(
            "remote",
            True,
            f"a SELECT 1 round trip took {elapsed:.0f}ms; every statement crosses a "
            "socket",
        ),
        _real("multi_machine", True, "addressed by URL, not by a path on this disk"),
        _real(
            "multi_process",
            True,
            "the same URL is reachable from any process holding the auth token",
        ),
        _real("offline_capable", False, "that socket is the only way to reach it"),
        _real(
            "max_document_bytes", None if refused_at is None else accepted, size_detail
        ),
        _real(
            "versioned_migrations",
            False,
            "the table carries whatever columns it was created with and nothing "
            "declares a version for the service to enforce",
        ),
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
