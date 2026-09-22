"""AWS S3 and Cloudflare R2 — one API, two endpoints (FUN-25 4.3 / T10).

This module owns **open question 1**, the single most important unknown in the
research (`durability-outsourcing/09-verdict.md:47-50`):

> **Is R2's conditional `PutObject` atomic under concurrent writers?**

Everything a future substrate would build on R2 — the compare-and-swap that
makes `fencing` mean anything, the revision check that stops a lost update —
rests on exactly one promise: when several writers send `If-None-Match: *` for
the same key at the same moment, **one** of them wins and the rest are refused.
S3 documents that promise. R2 speaks S3's API, which is not the same thing as
making S3's guarantees, and nobody has checked.

So the measurement is a race, not a round trip: `WRITERS` writers, one key, all
conditional, and the probe reports **the number that won**. Two winners is a
lost update in a system that thinks it cannot have one, and it is invisible to
any probe that writes once and reads back.

R2 is reached exactly as the repo already reaches an emulator — through an
endpoint override on the same boto3 client
(`plugins/credentials/functualize-aws/tests/test_integration_floci.py:12-14`) —
so S3 and R2 are the same code against different credentials. `.env.example`
gains `FUNCTUALIZE_PROBE_R2_*` beside the AWS names.

**What this host could measure:** S3's column, against floci, stamped
`measured (emulator)`. R2 has no emulator and no credentials here, so its
column — **including open question 1's own cell** — is
`NOT MEASURED (no R2 credentials)`, stated on every one of its ten cells rather
than left to prose. That is a legitimate outcome and it is the answer this
ticket carries forward: Q1 remains open, and what it would take to close it is
one R2 bucket.
"""

from __future__ import annotations

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import pytest

from tests.substrate_probe.conftest import missing_env, reachable
from tests.substrate_probe.harness import (
    Answer,
    Evidence,
    Reading,
    measured,
    reading,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

S3: Final[str] = "AWS S3"
R2: Final[str] = "Cloudflare R2"

EMULATOR: Final[Evidence] = "measured (emulator)"
REAL_SERVICE: Final[Evidence] = "measured (real service)"

#: Enough writers that "exactly one won" is a statement about serialisation
#: rather than a coin that landed the same way twice.
WRITERS: Final[int] = 8

#: Object sizes walked upward. S3's single-PUT limit is 5 GiB, which is not
#: walkable here, so the honest answer is "nothing refused what was attempted"
#: with the largest size named — never the documented number.
_SIZES: Final[tuple[int, ...]] = (64 * 1024, 1024 * 1024, 8 * 1024 * 1024)

AWS_CREDENTIALS: Final[tuple[str, ...]] = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
)
R2_CREDENTIALS: Final[tuple[str, ...]] = (
    "FUNCTUALIZE_PROBE_R2_ENDPOINT",
    "FUNCTUALIZE_PROBE_R2_ACCESS_KEY_ID",
    "FUNCTUALIZE_PROBE_R2_SECRET_ACCESS_KEY",
)

#: Read at import, before any client is built (AC5).
AWS_ABSENT: Final[tuple[str, ...]] = missing_env(*AWS_CREDENTIALS)
R2_ABSENT: Final[tuple[str, ...]] = missing_env(*R2_CREDENTIALS)
ENDPOINT: Final[str] = os.environ.get("AWS_ENDPOINT_URL", "").strip()

NO_S3: Final[str] = (
    "NOT MEASURED (no credentials) — "
    + ", ".join(AWS_ABSENT or AWS_CREDENTIALS)
    + " not set and AWS_ENDPOINT_URL names no reachable emulator, so nothing was "
    "asked of S3. The probe does not fall back to a fake; the variable names are "
    "declared in .env.example."
)
NO_R2: Final[str] = (
    "NOT MEASURED (no R2 credentials) — "
    + ", ".join(R2_ABSENT or R2_CREDENTIALS)
    + " not set, so **open question 1 is not answered**: whether R2's conditional "
    "PutObject is atomic under concurrent writers remains the research's largest "
    "open unknown. R2 has no emulator, and floci's answer is floci's, not R2's — "
    "so this cannot be borrowed from the S3 column. One R2 bucket closes it."
)


@dataclass(frozen=True, slots=True)
class Target:
    """Which store answered, reached how, and at what evidence level."""

    label: str
    evidence: Evidence
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str

    @property
    def described(self) -> str:
        return f"{self.label} at {self.endpoint}" if self.endpoint else self.label


def s3_target(
    endpoint: str = ENDPOINT, absent: tuple[str, ...] = AWS_ABSENT
) -> Target | None:
    """An emulator when one is reachable, the real service when credentials exist.

    Split out and given arguments so the routing can be asserted: this is where
    AC3 is kept or lost, and an emulator stamped `measured (real service)` would
    let a fake service back a shipped field.
    """
    if endpoint:
        if not reachable(endpoint):
            return None
        return Target(
            S3,
            EMULATOR,
            endpoint,
            "probe",
            "probe",
            _bucket("FUNCTUALIZE_PROBE_S3_BUCKET"),
        )
    if absent:
        return None
    return Target(
        S3,
        REAL_SERVICE,
        "",
        os.environ.get("AWS_ACCESS_KEY_ID", ""),
        os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
        _bucket("FUNCTUALIZE_PROBE_S3_BUCKET"),
    )


def r2_target(absent: tuple[str, ...] = R2_ABSENT) -> Target | None:
    """R2 is the same client against a different endpoint — and a real service.

    There is no emulator to fall back to, which is the whole difficulty of open
    question 1: absent credentials it stays unanswered rather than approximated.
    """
    if absent:
        return None
    return Target(
        R2,
        REAL_SERVICE,
        os.environ["FUNCTUALIZE_PROBE_R2_ENDPOINT"],
        os.environ["FUNCTUALIZE_PROBE_R2_ACCESS_KEY_ID"],
        os.environ["FUNCTUALIZE_PROBE_R2_SECRET_ACCESS_KEY"],
        _bucket("FUNCTUALIZE_PROBE_R2_BUCKET"),
    )


def _bucket(variable: str) -> str:
    return (
        os.environ.get(variable, "").strip() or f"fun25-probe-{uuid.uuid4().hex[:12]}"
    )


S3_TARGET: Final[Target | None] = s3_target()
R2_TARGET: Final[Target | None] = r2_target()

requires_s3 = pytest.mark.skipif(S3_TARGET is None, reason=NO_S3)
requires_r2 = pytest.mark.skipif(R2_TARGET is None, reason=NO_R2)


def _client(kind: Target) -> Any:
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=kind.endpoint or None,
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        aws_access_key_id=kind.access_key,
        aws_secret_access_key=kind.secret_key,
    )


def _bucket_for(client: Any, kind: Target) -> Iterator[str]:
    """A bucket for this run, emptied and removed unless it was already there."""
    created = False
    try:
        client.head_bucket(Bucket=kind.bucket)
    except Exception:  # noqa: BLE001 - any refusal means "not usable yet"
        client.create_bucket(Bucket=kind.bucket)
        created = True
    try:
        yield kind.bucket
    finally:
        if created:
            listing = client.list_objects_v2(Bucket=kind.bucket)
            for obj in listing.get("Contents", []):
                client.delete_object(Bucket=kind.bucket, Key=obj["Key"])
            client.delete_bucket(Bucket=kind.bucket)


def _contention_answers(kind: Target, bucket: str) -> tuple[Answer, ...]:
    """**Open question 1.** Race `WRITERS` conditional writers for one key.

    Every writer sends `PutObject` with `If-None-Match: *` for the same absent
    key, from its own client. The number that come back successful is the
    answer: one means the conditional write serialises and a compare-and-swap
    built on it is sound; more than one means two writers both believed they
    created the object, which is a lost update in a system that thinks it
    cannot have one.

    The key is read back afterwards so the recorded evidence names which
    writer's bytes actually survived — with two winners, that is the byte-level
    shape of the defect.
    """
    from botocore.exceptions import ClientError

    key = f"fun25-contention-{uuid.uuid4().hex[:8]}"

    def attempt(writer: int) -> tuple[int, str]:
        own = _client(kind)
        try:
            own.put_object(
                Bucket=bucket,
                Key=key,
                Body=f"writer-{writer}".encode(),
                IfNoneMatch="*",
            )
        except ClientError as refused:
            return writer, refused.response["Error"]["Code"]
        return writer, "created"

    with ThreadPoolExecutor(max_workers=WRITERS) as pool:
        outcomes = dict(pool.map(attempt, range(WRITERS)))

    winners = [w for w, outcome in outcomes.items() if outcome == "created"]
    refusals = sorted({o for o in outcomes.values() if o != "created"})
    client = _client(kind)
    survived = client.get_object(Bucket=bucket, Key=key)["Body"].read().decode()
    evidence = (
        f"{WRITERS} writers sent PutObject with If-None-Match: * for one absent "
        f"key against {kind.described}: **{len(winners)} won**, the rest were "
        f"refused ({', '.join(refusals) or 'none'}); the surviving object holds "
        f"{survived!r}"
    )
    atomic = len(winners) == 1
    return (
        measured(
            "fencing",
            "cross-process" if atomic else "none",
            evidence=kind.evidence,
            detail=(
                "the precondition is evaluated by the service rather than by a "
                f"lock this process holds, so it excludes any writer anywhere: "
                f"{evidence}"
            ),
        ),
        measured(
            "multi_process",
            atomic,
            evidence=kind.evidence,
            detail=(
                f"each writer above used its own client and the store serialised "
                f"them: {evidence}"
            ),
        ),
    )


def _atomicity_answers(client: Any, kind: Target) -> tuple[Answer, ...]:
    """Can two keys be written so that either both land or neither does?

    Answered from the API's own surface rather than a vendor page: the probe
    lists every operation this client can send and looks for one that writes
    more than one key as a unit. `DeleteObjects` deletes in bulk and reports
    per-key results, which is the opposite of all-or-nothing.
    """
    operations = sorted(client.meta.service_model.operation_names)
    multi_key_writes = [
        op for op in operations if op.startswith(("Transact", "BatchWrite", "BatchPut"))
    ]
    named = ", ".join(multi_key_writes) or "no Transact*/BatchWrite* operation"
    return (
        measured(
            "cross_aggregate_atomicity",
            bool(multi_key_writes),
            evidence=kind.evidence,
            detail=(
                f"of the {len(operations)} operations this API offers, none "
                f"writes two keys as one unit ({named}); the bulk call it does "
                "have, DeleteObjects, reports per-key results, which is the "
                "opposite of all-or-nothing"
            ),
        ),
        measured(
            "durable_outbox",
            bool(multi_key_writes),
            evidence=kind.evidence,
            detail=(
                "follows from the line above and was not assumed separately: with "
                "no two-key unit, a state change and the record that it happened "
                "cannot commit together — one of them lands first and a crash "
                "between them is observable"
            ),
        ),
        measured(
            "interactive_transaction",
            False,
            evidence=kind.evidence,
            detail=(
                "no begin/commit pair exists in the operation list above, so there "
                "is no transaction to hold open across a Python decision"
            ),
        ),
    )


def _size_answer(client: Any, kind: Target, bucket: str) -> Answer:
    """Write objects of increasing size until one is refused."""
    from botocore.exceptions import ClientError

    run = uuid.uuid4().hex[:8]
    accepted = 0
    for size in _SIZES:
        try:
            client.put_object(Bucket=bucket, Key=f"{run}-{size}", Body=b"x" * size)
        except ClientError as refused:
            return measured(
                "max_document_bytes",
                accepted or None,
                evidence=kind.evidence,
                detail=(
                    f"{size} bytes was refused ({refused.response['Error']['Code']}); "
                    f"{accepted} bytes was accepted immediately before it"
                ),
            )
        accepted = size
    return measured(
        "max_document_bytes",
        None,
        evidence=kind.evidence,
        detail=(
            f"nothing refused an object up to {accepted} bytes, the largest this "
            "probe attempted. The documented single-PUT limit is far above that "
            "and is deliberately **not** recorded here: it was not measured, and "
            "a vendor number in a measured cell is the thing this ticket exists "
            "to remove"
        ),
    )


def _schema_answer(client: Any, kind: Target, bucket: str) -> Answer:
    """Store two differently shaped payloads and see whether anything objects."""
    run = uuid.uuid4().hex[:8]
    client.put_object(Bucket=bucket, Key=f"{run}-a", Body=b'{"schema_version": 1}')
    client.put_object(Bucket=bucket, Key=f"{run}-b", Body=b"not json at all")
    stored = client.get_object(Bucket=bucket, Key=f"{run}-b")["Body"].read()
    return measured(
        "versioned_migrations",
        False,
        evidence=kind.evidence,
        detail=(
            f"a JSON document and {stored!r} were both stored under the same "
            "bucket without complaint: the store holds opaque bytes and has no "
            "schema whose version it could enforce"
        ),
    )


def _reach_answers(client: Any, kind: Target, bucket: str) -> tuple[Answer, ...]:
    """One round trip, and what being reached by an endpoint implies."""
    started = time.perf_counter()
    client.head_bucket(Bucket=bucket)
    elapsed = (time.perf_counter() - started) * 1000
    return (
        measured(
            "remote",
            True,
            evidence=kind.evidence,
            detail=(
                f"a HeadBucket round trip to {kind.described} took {elapsed:.0f}ms; "
                "every operation crosses a socket, so a read-modify-write loop "
                "pays this per step"
            ),
        ),
        measured(
            "multi_machine",
            True,
            evidence=kind.evidence,
            detail=f"addressed by endpoint, not by a path on this disk ({kind.described})",
        ),
        measured(
            "offline_capable",
            False,
            evidence=kind.evidence,
            detail="that socket is the only way to reach it; there is no local copy",
        ),
    )


def _column(kind: Target | None, label: str, why: str) -> Reading:
    """Ten cells from one store — or ten stated reasons there are none.

    S3 and R2 share this because they *are* the same API; what differs is the
    endpoint, the credentials and the evidence level, all carried by `Target`.
    No base class and nothing to subclass (`.spec/CONSTITUTION.md` →
    *Forbidden Patterns*): a backend here is a `Target` and a function.
    """
    if kind is None:
        return reading(label, [], why=why)
    client = _client(kind)
    buckets = _bucket_for(client, kind)
    bucket = next(buckets)
    try:
        answers = (
            *_contention_answers(kind, bucket),
            *_atomicity_answers(client, kind),
            *_reach_answers(client, kind, bucket),
            _size_answer(client, kind, bucket),
            _schema_answer(client, kind, bucket),
        )
    finally:
        next(buckets, None)
    return reading(label, answers)


def s3_column() -> Reading:
    return _column(S3_TARGET, S3, NO_S3)


def r2_column() -> Reading:
    return _column(R2_TARGET, R2, NO_R2)


@requires_s3
def test_a_conditional_put_serialises_concurrent_writers_on_s3() -> None:
    """The same race open question 1 asks of R2, asked of S3's implementation."""
    pytest.importorskip("boto3")
    column = s3_column()

    assert column.unmeasured == ()
    assert {answer.evidence for answer in column.answers} == {S3_TARGET.evidence}  # type: ignore[union-attr]
    assert "**1 won**" in column["fencing"].detail, (
        "a conditional put let two writers in"
    )
    assert column["fencing"].value == "cross-process"
    assert column["cross_aggregate_atomicity"].value is False


@requires_r2
def test_open_question_one_is_answered_against_r2() -> None:
    """R2's own answer — the only thing that closes open question 1.

    Skipped here and everywhere until someone supplies an R2 bucket: floci's
    answer is floci's, and S3's is S3's. Neither is R2's.
    """
    pytest.importorskip("boto3")
    column = r2_column()

    assert column.unmeasured == ()
    assert "won" in column["fencing"].detail
    assert {answer.evidence for answer in column.answers} == {REAL_SERVICE}


@pytest.mark.skipif(
    R2_TARGET is not None, reason="R2 credentials exist, so it is measured"
)
def test_open_question_one_is_stated_unanswered_on_every_r2_cell() -> None:
    """Never omitted. The most important unknown in the research says so itself.

    A question that disappears because nobody could run it is the failure this
    criterion exists to prevent, so the R2 column is ten cells wide even when
    every one of them is unmeasured, and each names what it would take.
    """
    column = r2_column()

    assert len(column.answers) == 10
    assert len(column.unmeasured) == 10
    for answer in column.answers:
        assert answer.detail.startswith("NOT MEASURED (no R2 credentials)")
        assert "open question 1" in answer.detail
    assert "floci's answer is floci's" in column["fencing"].detail


def test_an_endpoint_is_never_stamped_as_a_real_service() -> None:
    """AC3 on the routing, the guard T9's sabotage showed is worth having."""
    import socket

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        live = f"http://127.0.0.1:{listener.getsockname()[1]}"
        routed = s3_target(endpoint=live, absent=())
        assert routed is not None
        assert routed.evidence == "measured (emulator)"

    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        dead = f"http://127.0.0.1:{closed.getsockname()[1]}"
    assert s3_target(endpoint=dead, absent=()) is None

    assert s3_target(endpoint="", absent=("AWS_ACCESS_KEY_ID",)) is None
    real = s3_target(endpoint="", absent=())
    assert real is not None and real.evidence == "measured (real service)"

    assert r2_target(absent=("FUNCTUALIZE_PROBE_R2_ENDPOINT",)) is None
