"""Cloudflare D1, over its REST API and nothing else (FUN-25 4.1 / T8).

D1 is the backend the research rates best of the six
(`durability-outsourcing/09-verdict.md`), and the two things it is rated on are
things nobody has measured: **how slow the REST API actually is from a
developer's machine**, and whether the documented **2 MB row cap** is real.
This module owns **open question 2**, so it records a latency *distribution* —
min, median, p95, max over repeated round trips — rather than a verdict.

**Transport is stdlib `urllib.request`, deliberately.** No first-party package
declares `httpx` (`rg '"httpx' pyproject.toml plugins/*/*/pyproject.toml`
returns nothing); it is present only transitively. Depending on it here would
add an undeclared dependency *and* put a client library's connection pooling,
retries and HTTP/2 negotiation inside a measurement whose whole subject is how
long one request takes. Removing the library is part of the instrument.

**What this host could measure, and what it does now.** When this module was written
there were no Cloudflare credentials here and every cell was
`NOT MEASURED (no credentials)` carrying the names of the variables that were
absent. *(2026-09-23: the credentials arrived, the paths below have run against
D1, and the column now carries **six measured cells and four stated as
unmeasured** — the reasons for those four are in `d1_column()`.)* Two things
about the first real run are worth keeping:

- **A refusal and a reset are different findings.** D1 answered `BEGIN` with
  `HTTP 400 code 7500` and its own message; an earlier run on the same statement
  died with a TCP reset. Only the first is an answer about D1, so `query()`
  returns a transport failure as a `Response` rather than raising, and the cells
  report it as `NOT MEASURED (transport)` instead of borrowing a refusal the
  service never gave.
- **The transport is bounded by statement**, not by a library's default:
  `query()` passes an explicit `timeout` to `urlopen`.

What *is* exercised without credentials is the instrument itself: the request
this module builds and the envelope it parses are asserted at the foot of the
file against a local stub. That stub answers no question and produces no
`Answer` — it is the difference between "the probe works" and "D1 does X", and
conflating those two is exactly what this ticket exists to stop.
"""

from __future__ import annotations

import json
import os
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import pytest

from tests.substrate_probe.conftest import missing_env
from tests.substrate_probe.harness import (
    Answer,
    Evidence,
    Reading,
    measured,
    not_measured,
    reading,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

#: The column, named as the matrix will name it.
D1: Final[str] = "Cloudflare D1"

REAL_SERVICE: Final[Evidence] = "measured (real service)"

#: Declared in `.env.example`; the token needs D1 Read + D1 Write.
CREDENTIALS: Final[tuple[str, ...]] = (
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_D1_DATABASE_ID",
    "CLOUDFLARE_API_TOKEN",
)

#: Read at import, before anything is built — the root `tests/conftest.py`
#: strips `FUNCTUALIZE_*` from an autouse fixture, which runs later, and a gate
#: that read the environment from inside a test would see a different one.
ABSENT: Final[tuple[str, ...]] = missing_env(*CREDENTIALS)

NO_CREDENTIALS: Final[str] = (
    "NOT MEASURED (no credentials) — "
    + ", ".join(ABSENT or CREDENTIALS)
    + " not set in the environment, so nothing was asked of D1. The probe does "
    "not fall back to a fake; the variable names are declared in .env.example."
)

_API: Final[str] = "https://api.cloudflare.com/client/v4"

#: Enough round trips for a p95 to mean something, few enough to stay polite on
#: a free-tier database.
_SAMPLES: Final[int] = 25

#: Sizes walked upward until one is refused. The 2 MB cap is a *claim* until a
#: write bounces off it, so the pair straddling it is what the answer rests on.
_SIZES: Final[tuple[int, ...]] = (
    64 * 1024,
    1024 * 1024,
    2 * 1024 * 1024 - 4096,
    2 * 1024 * 1024 + 4096,
    4 * 1024 * 1024,
)

#: The credential gate, decided **at module level** — `ABSENT` is read at import,
#: before any request is built, so collection cannot error and no client is
#: constructed on a host with no Cloudflare account (AC5).
#:
#: Applied to the measurement test rather than as a module-wide `pytestmark`,
#: which would also skip the three tests below that exist precisely for the
#: credential-less case: the column still has to *state* its ten unmeasured
#: cells, and the instrument still has to be shown to work. A module that
#: aborted its own import would leave `d1_column()` unimportable, and T12's
#: matrix would have no D1 column to print at all — "NOT MEASURED (no
#: credentials)" would survive only as a skip message in a log.
requires_credentials = pytest.mark.skipif(bool(ABSENT), reason=NO_CREDENTIALS)


@dataclass(frozen=True, slots=True)
class Response:
    """One REST round trip, and how long it took.

    A refused request and a request that never arrived are **different
    findings**, so they are different fields rather than different codes:
    `status` is the HTTP status when there was one, and `transport` says why the
    request never got that far — a reset, a timeout, a name that would not
    resolve. Folding the second into the first is how a probe records a service
    refusal it never received, and the operator saw both shapes on this API: a
    TCP reset on `BEGIN` one run, `HTTP 400` with the service's own message the
    next.
    """

    status: int | None
    body: dict[str, Any]
    seconds: float
    transport: str = ""

    @property
    def ok(self) -> bool:
        return self.status == 200 and bool(self.body.get("success"))

    @property
    def reached(self) -> bool:
        """Did the request get an HTTP answer at all?"""
        return not self.transport

    @property
    def error(self) -> str:
        if self.transport:
            return f"the request never reached D1: {self.transport}"
        errors = self.body.get("errors") or []
        return "; ".join(_described(error) for error in errors) or f"HTTP {self.status}"


def _described(error: Any) -> str:
    """One error envelope entry, with its code when it carries one.

    D1 answers `BEGIN` with `code 7500` and a message telling the caller to use
    the JavaScript transaction API instead. The code is kept because it is the
    part of that refusal a reader can look up.
    """
    if not isinstance(error, dict):
        return str(error)
    code, message = error.get("code"), str(error.get("message", error))
    return f"code {code}: {message}" if code is not None else message


def query(
    sql: str, params: Sequence[Any] = (), *, api: str = _API, timeout: float = 30.0
) -> Response:
    """One POST to D1's `/query`, timed from just before send to fully read.

    The clock covers exactly one request/response, because open question 2 is
    about what a caller waits for, not what a connection pool amortises.

    **A transport failure is a `Response`, not an exception.** A reset means D1
    was never asked anything, which is a different finding from D1 refusing —
    and it is the failure the operator observed on this endpoint, so a probe
    that raised there would lose the run rather than record the distinction.
    """
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    database = os.environ.get("CLOUDFLARE_D1_DATABASE_ID", "")
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    request = urllib.request.Request(  # noqa: S310 - https, built from a constant
        f"{api}/accounts/{account}/d1/database/{database}/query",
        data=json.dumps({"sql": sql, "params": list(params)}).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            raw, status = response.read(), response.status
    except urllib.error.HTTPError as refused:
        raw, status = refused.read(), refused.code
    except OSError as unreached:
        # `URLError` is an `OSError`, and so is a reset, a timeout and a DNS
        # failure. None of them is D1 answering.
        return Response(
            status=None,
            body={},
            seconds=time.perf_counter() - started,
            transport=f"{type(unreached).__name__}: {unreached}",
        )
    elapsed = time.perf_counter() - started
    try:
        body = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        body = {
            "success": False,
            "errors": [{"message": raw[:200].decode(errors="replace")}],
        }
    return Response(status=status, body=body, seconds=elapsed)


def summarise(samples: Sequence[float]) -> str:
    """A distribution, not a verdict — open question 2 asks for the numbers."""
    if not samples:
        return "no samples"
    ordered = sorted(samples)
    p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
    return (
        f"n={len(ordered)} min={ordered[0] * 1000:.0f}ms "
        f"median={statistics.median(ordered) * 1000:.0f}ms "
        f"p95={p95 * 1000:.0f}ms max={ordered[-1] * 1000:.0f}ms"
    )


def _latency_answers() -> tuple[Answer, ...]:
    """Round trips, timed. Every one of them crosses a network by construction."""
    responses = [query("SELECT 1") for _ in range(_SAMPLES)]
    distribution = summarise([response.seconds for response in responses])
    unreached = [response for response in responses if not response.reached]
    if unreached:
        distribution += (
            f" — {len(unreached)} of them never reached D1 "
            f"({unreached[0].transport}), and the timings above include those "
            f"attempts rather than hiding them"
        )
    return (
        measured(
            "remote",
            True,
            evidence=REAL_SERVICE,
            detail=(
                f"every operation is one HTTPS request to {_API}: {distribution}. "
                "Open question 2, answered with numbers — a 200-transition workflow "
                "that read-modify-writes in a loop pays this per transition"
            ),
        ),
        measured(
            "offline_capable",
            False,
            evidence=REAL_SERVICE,
            detail=(
                "the same round trips are the only way to reach it; there is no "
                "local copy to fall back to when the network is gone"
            ),
        ),
        measured(
            "multi_machine",
            True,
            evidence=REAL_SERVICE,
            detail=f"reached by URL rather than by a path: {distribution}",
        ),
        measured(
            "multi_process",
            True,
            evidence=REAL_SERVICE,
            detail="the same URL is reachable from any process that holds the token",
        ),
    )


def _interactive_transaction_answer() -> Answer:
    """Try to hold a transaction open across a round trip, and see what happens.

    The research says D1 has no `BEGIN`/`COMMIT` and that everything atomic must
    be one batch (`05-cloudflare.md` §A.3). That is a documented claim, so this
    sends the statement and records the refusal rather than citing the page.

    **A request that never arrived is not a refusal.** D1 answered `BEGIN` with
    `HTTP 400` and the service's own words on the measured run; an earlier run
    on the same statement died with a TCP reset instead. Only the first is an
    answer about D1, so the second is recorded as unmeasured for a transport
    reason rather than folded into the same cell.
    """
    opened = query("BEGIN")
    if not opened.reached:
        return not_measured(
            "interactive_transaction",
            f"NOT MEASURED (transport) — {opened.error}. A reset is not an answer "
            f"from the service: D1 was never asked, so this cell stays unmeasured "
            f"rather than borrowing the refusal a delivered `BEGIN` would produce",
        )
    return measured(
        "interactive_transaction",
        opened.ok,
        evidence=REAL_SERVICE,
        detail=(
            f"`BEGIN` sent over /query returned HTTP {opened.status}"
            + (f" — {opened.error}" if not opened.ok else " and was accepted")
            + ". A transaction that cannot be opened cannot be held across a "
            "Python decision; anything atomic has to be one batch request"
        ),
    )


def _document_size_answer() -> Answer:
    """Walk sizes upward until one is refused, and record the size that bounced.

    `05-cloudflare.md:113` records a 2 MB row cap from the limits page. This
    verifies it: the two sizes straddling 2 MB are in the walk, so the recorded
    answer is the byte count D1 actually refused, not the one it documents.

    **A refused write and an undelivered one are told apart here**, because
    reading a reset as a refusal would record a cap D1 never imposed.
    """
    created = query(
        "CREATE TABLE IF NOT EXISTS probe_sizes (k TEXT PRIMARY KEY, v TEXT)"
    )
    if not created.reached:
        return _unreached("max_document_bytes", created, "the setup write")
    accepted = 0
    for size in _SIZES:
        written = query(
            "INSERT OR REPLACE INTO probe_sizes (k, v) VALUES (?, ?)",
            ("probe", "x" * size),
        )
        if not written.reached:
            return _unreached("max_document_bytes", written, f"the {size} byte write")
        if not written.ok:
            return measured(
                "max_document_bytes",
                accepted or None,
                evidence=REAL_SERVICE,
                detail=(
                    f"{size} bytes was refused (HTTP {written.status} — "
                    f"{written.error}); {accepted} bytes was accepted immediately "
                    "before it, so the limit lies between them. Measured against "
                    "the service, not copied from the limits page"
                ),
            )
        accepted = size
    return measured(
        "max_document_bytes",
        None,
        evidence=REAL_SERVICE,
        detail=(
            f"nothing refused a write up to {accepted} bytes, the largest size "
            "this probe attempted — so no cap was observed in the range walked, "
            "which is not the same as no cap existing"
        ),
    )


def _unreached(field: str, response: Response, what: str) -> Answer:
    """A cell whose operation never reached D1, said as such."""
    return not_measured(
        field,
        f"NOT MEASURED (transport) — {what} never reached D1 "
        f"({response.transport}), so the walk stopped before anything was "
        f"refused: an undelivered request is not a cap D1 imposed",
    )


def _unasked(field: str, why: str) -> Answer:
    return not_measured(field, f"NOT MEASURED — {why}")


def d1_column() -> Reading:
    """D1's ten cells: measured over REST, or stated as unmeasured with a reason."""
    if ABSENT:
        return reading(D1, [], why=NO_CREDENTIALS)
    return reading(
        D1,
        [
            *_latency_answers(),
            _interactive_transaction_answer(),
            _document_size_answer(),
            _unasked(
                "cross_aggregate_atomicity",
                "D1's atomic unit is a `batch` request, which the /query endpoint "
                "this module speaks does not carry; measuring it needs the /batch "
                "surface and is not part of open question 2",
            ),
            _unasked(
                "fencing",
                "no lock primitive was exercised — D1 offers none, and a "
                "compare-and-swap built from `WHERE revision = ?` is FUN-17's "
                "design decision rather than a property of the service",
            ),
            _unasked(
                "durable_outbox",
                "follows from cross_aggregate_atomicity, which this module did "
                "not measure",
            ),
            _unasked(
                "versioned_migrations",
                "D1 has a migrations surface this probe did not exercise",
            ),
        ],
    )


@requires_credentials
def test_the_d1_column_is_measured_when_credentials_exist() -> None:
    """Open question 2's three deliverables, from one run against the service.

    Skipped without `CLOUDFLARE_*`, which is how a contributor with no
    Cloudflare account runs this suite green (AC5).
    """
    column = d1_column()

    assert column["remote"].value is True
    assert "median=" in column["remote"].detail, (
        "record the distribution, not a verdict"
    )
    assert column["interactive_transaction"].is_measured
    assert column["max_document_bytes"].is_measured
    assert all(
        answer.evidence == REAL_SERVICE
        for answer in column.answers
        if answer.is_measured
    )


@pytest.mark.skipif(
    not ABSENT, reason="credentials are present, so the column is measured"
)
def test_without_credentials_every_cell_states_why() -> None:
    """`NOT MEASURED` is an outcome this ticket reports; silence is not.

    Runs precisely when the measurement cannot, so the column is never simply
    missing from the matrix — all ten cells exist and each carries the names of
    the variables that were absent.
    """
    column = d1_column()

    assert len(column.answers) == 10
    assert len(column.unmeasured) == 10
    for answer in column.answers:
        assert answer.detail.startswith("NOT MEASURED (no credentials)")
        assert "CLOUDFLARE_API_TOKEN" in answer.detail


def test_the_instrument_builds_a_d1_request_and_parses_its_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The probe, not the backend — this asserts no cell and answers no question.

    A local stub is not a measurement and nothing here produces an `Answer`.
    What it does establish is that the one piece of this module a
    credential-less host can check really works: the URL, the bearer header and
    the JSON body are built as D1's REST API expects, an error envelope is read
    back rather than raised, and the elapsed time is a real measurement of the
    round trip. Without it every line above would be unexecuted code.
    """
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen: dict[str, Any] = {}

    class _Stub(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's name
            length = int(self.headers["Content-Length"])
            seen["path"] = self.path
            seen["auth"] = self.headers.get("Authorization")
            seen["body"] = json.loads(self.rfile.read(length))
            payload = json.dumps(
                {"success": False, "errors": [{"message": "no such table: nope"}]}
            ).encode()
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: Any) -> None:
            """Silence: the stub is plumbing, not output."""

    server = HTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=server.handle_request, daemon=True).start()
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CLOUDFLARE_D1_DATABASE_ID", "db")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token")

    host, port = server.server_address[0], server.server_address[1]
    response = query("SELECT ?", ("x",), api=f"http://{host}:{port}/client/v4")
    server.server_close()

    assert seen["path"] == "/client/v4/accounts/acct/d1/database/db/query"
    assert seen["auth"] == "Bearer token"
    assert seen["body"] == {"sql": "SELECT ?", "params": ["x"]}
    assert response.ok is False
    assert response.status == 400
    assert response.error == "no such table: nope"
    assert response.seconds > 0


def test_a_request_that_never_arrives_is_not_an_exception() -> None:
    """A reset is a `Response`, not a crash — the failure the operator hit.

    `BEGIN` died with a TCP reset on one run and returned `HTTP 400` on the next.
    Before this, the reset escaped `query()` as an exception and would have taken
    the whole run with it; a probe that loses the run cannot record which of the
    two happened, and they are not the same finding.
    """
    import socket

    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))  # bound, never listening: every connect fails
        port = closed.getsockname()[1]

    response = query("BEGIN", api=f"http://127.0.0.1:{port}/client/v4")

    assert response.reached is False
    assert response.ok is False
    assert response.status is None
    assert response.seconds > 0
    assert response.error.startswith("the request never reached D1:")


def test_an_undelivered_write_is_not_recorded_as_the_row_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The walk must not read a reset as a cap D1 imposed.

    The **second write in the walk** is the one that never arrives, so this
    exercises the in-loop branch rather than the setup check that runs before it
    — a distinction worth stating because the first version of this test tripped
    the setup check instead, and removing the branch it claimed to guard left it
    green. Before the guard, that write took the `not written.ok` branch and its
    size was recorded as the byte count D1 refused: a cap invented by a transport
    failure.
    """
    calls = {"n": 0}

    def half_delivered(sql: str, *args: object, **kwargs: object) -> Response:
        calls["n"] += 1
        if calls["n"] <= 2:  # the CREATE, then the smallest size: both delivered
            return Response(status=200, body={"success": True}, seconds=0.01)
        return Response(
            status=None,
            body={},
            seconds=0.01,
            transport="ConnectionResetError: connection reset by peer",
        )

    monkeypatch.setattr("tests.substrate_probe.d1.query", half_delivered)

    answer = _document_size_answer()

    assert not answer.is_measured
    assert "NOT MEASURED (transport)" in answer.detail
    assert answer.value is None, "an undelivered write was recorded as the cap"


def test_the_distribution_is_reported_as_numbers() -> None:
    """Open question 2 asks for a distribution; `summarise` is what writes one."""
    assert summarise([]) == "no samples"
    reported = summarise([0.050, 0.060, 0.070, 0.500])
    assert reported.startswith("n=4 min=50ms")
    assert "median=65ms" in reported
    assert "max=500ms" in reported
