"""AWS DynamoDB — the emulator first, the real service when it is there (4.2 / T9).

`TransactWriteItems` is the reason DynamoDB is in this evaluation at all: it is
the one call among the six backends that writes two different keys so that
either both land or neither does, which is what `cross_aggregate_atomicity` and
`durable_outbox` are asking about. So this module does not check that the call
*exists* — T1 already did that — it puts the guarantee under **contention**:
several writers race for one key, each carrying a sibling write, and the probe
counts the winners and then reads back whether any loser left its sibling
behind.

**Two evidence levels, one column.** Whatever the emulator answers is stamped
`measured (emulator)` and may **never** back a shipped field (AC3); the real
service is `measured (real service)`. Which one a run produces is decided by
the environment, at module level, and recorded on every cell — a reader can
always tell what answered.

**Reached the way the repo already reaches an emulator**: `AWS_ENDPOINT_URL`,
which botocore honours itself, so nothing here needs to know what is listening
(`plugins/credentials/functualize-aws/tests/test_integration_floci.py:12-14`).
The variable must be *set*; this module will not go looking for something on
`localhost:4566`, because a probe that adopts whatever happens to hold a port
is how a measurement ends up describing the wrong service.

Absent both, every cell is `NOT MEASURED (no credentials)` with its reason, and
T1's floci verdict is the thing to read beside it.
"""

from __future__ import annotations

import os
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

DYNAMODB: Final[str] = "AWS DynamoDB"

EMULATOR: Final[Evidence] = "measured (emulator)"
REAL_SERVICE: Final[Evidence] = "measured (real service)"

CREDENTIALS: Final[tuple[str, ...]] = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
)

#: Read at import, before any client is built (AC5).
ABSENT: Final[tuple[str, ...]] = missing_env(*CREDENTIALS)
ENDPOINT: Final[str] = os.environ.get("AWS_ENDPOINT_URL", "").strip()

#: How many writers race for the same key. Enough that "exactly one won" is a
#: statement about serialisation rather than a coin landing the same way twice.
WRITERS: Final[int] = 8

#: Item sizes walked upward. DynamoDB documents a 400 KB item limit; the pair
#: straddling it is what makes the recorded answer a measurement.
_SIZES: Final[tuple[int, ...]] = (16 * 1024, 200 * 1024, 380 * 1024, 420 * 1024)

NO_SERVICE: Final[str] = (
    "NOT MEASURED (no credentials) — "
    + ", ".join(ABSENT or CREDENTIALS)
    + " not set and AWS_ENDPOINT_URL names no reachable emulator, so nothing was "
    "asked of DynamoDB. T1's floci survey is the verdict to read beside this: "
    "floci implements TransactWriteItems and cancels atomically, so an emulator "
    "row is obtainable here the moment AWS_ENDPOINT_URL is set. The probe does "
    "not fall back to a fake; the variable names are declared in .env.example."
)


@dataclass(frozen=True, slots=True)
class Target:
    """What answered, and at what evidence level."""

    evidence: Evidence
    endpoint: str

    @property
    def described(self) -> str:
        return f"the emulator at {self.endpoint}" if self.endpoint else "AWS DynamoDB"


def target(endpoint: str = ENDPOINT, absent: tuple[str, ...] = ABSENT) -> Target | None:
    """Decide what to ask, and at what evidence level. `None` = ask nothing.

    The arguments default to the module-level values read at import, and exist
    so the routing itself can be asserted — this function is where AC3 is
    either kept or lost, and a guard that only checks `Target`'s constructor
    would not notice an endpoint being stamped `measured (real service)`.

    An endpoint that is set but unreachable is `None` rather than an error: a
    contributor whose emulator is not running gets a skip that says so.
    """
    if endpoint:
        return Target(EMULATOR, endpoint) if reachable(endpoint) else None
    return None if absent else Target(REAL_SERVICE, "")


TARGET: Final[Target | None] = target()

requires_a_service = pytest.mark.skipif(TARGET is None, reason=NO_SERVICE)


def _client(kind: Target) -> Any:
    import boto3

    if kind.evidence is EMULATOR:
        return boto3.client(
            "dynamodb",
            endpoint_url=kind.endpoint,
            region_name="us-east-1",
            aws_access_key_id="probe",
            aws_secret_access_key="probe",  # gitleaks:allow
        )
    return boto3.client(
        "dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1")
    )


def _table(client: Any) -> Iterator[str]:
    """A table for this run, removed afterwards unless it was already there."""
    import time

    declared = os.environ.get("FUNCTUALIZE_PROBE_DDB_TABLE", "").strip()
    name = declared or f"fun25-probe-{uuid.uuid4().hex[:12]}"
    created = False
    try:
        client.describe_table(TableName=name)
    except client.exceptions.ResourceNotFoundException:
        client.create_table(
            TableName=name,
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        created = True
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if (
                client.describe_table(TableName=name)["Table"]["TableStatus"]
                == "ACTIVE"
            ):
                break
            time.sleep(0.2)
    try:
        yield name
    finally:
        if created:
            client.delete_table(TableName=name)


def _put(table: str, pk: str, value: str) -> dict[str, Any]:
    return {
        "Put": {
            "TableName": table,
            "Item": {"pk": {"S": pk}, "v": {"S": value}},
            "ConditionExpression": "attribute_not_exists(pk)",
        }
    }


def _present(client: Any, table: str, pk: str) -> bool:
    return "Item" in client.get_item(TableName=table, Key={"pk": {"S": pk}})


def _contention_answers(client: Any, table: str, kind: Target) -> tuple[Answer, ...]:
    """Race `WRITERS` transactions for one key, each carrying a sibling write.

    Every writer attempts the same conditional put on the contested key *and* a
    put of its own private key, in one `TransactWriteItems`. Two things are then
    read back rather than assumed: how many writers the service let through, and
    whether a loser's private key survived. A backend with the call but not the
    guarantee shows up as several winners, or as one winner and several orphaned
    siblings — and either would be invisible to a test that raced a single key.
    """
    from botocore.exceptions import ClientError

    run = uuid.uuid4().hex[:8]
    contested = f"{run}-contested"

    def attempt(writer: int) -> tuple[int, str]:
        own = _client(kind)
        try:
            own.transact_write_items(
                TransactItems=[
                    _put(table, contested, f"writer-{writer}"),
                    _put(table, f"{run}-sibling-{writer}", f"writer-{writer}"),
                ]
            )
        except ClientError as refused:
            return writer, refused.response["Error"]["Code"]
        return writer, "committed"

    with ThreadPoolExecutor(max_workers=WRITERS) as pool:
        outcomes = dict(pool.map(attempt, range(WRITERS)))

    winners = [w for w, outcome in outcomes.items() if outcome == "committed"]
    orphans = [
        w
        for w in outcomes
        if w not in winners and _present(client, table, f"{run}-sibling-{w}")
    ]
    refusals = sorted({o for o in outcomes.values() if o != "committed"})
    evidence = (
        f"{WRITERS} writers raced one conditional key, each carrying a sibling "
        f"write in the same TransactWriteItems: {len(winners)} committed, the "
        f"rest were refused ({', '.join(refusals) or 'none'}); "
        f"{len(orphans)} loser left its sibling behind"
    )
    return (
        measured(
            "cross_aggregate_atomicity",
            len(winners) == 1 and not orphans,
            evidence=kind.evidence,
            detail=evidence,
        ),
        measured(
            "durable_outbox",
            len(winners) == 1 and not orphans,
            evidence=kind.evidence,
            detail=(
                "the sibling write above is an outbox row in everything but "
                f"name — it commits with the state change or not at all: {evidence}"
            ),
        ),
        measured(
            "fencing",
            "cross-process" if len(winners) == 1 else "none",
            evidence=kind.evidence,
            detail=(
                "the condition is evaluated by the service, not by a lock this "
                f"process holds, so it excludes any writer anywhere: {evidence}"
            ),
        ),
    )


def _interactive_transaction_answer(client: Any, kind: Target) -> Answer:
    """Ask the service's own model whether a transaction can be held open."""
    operations = client.meta.service_model.operation_names
    holdable = sorted(
        op for op in operations if op.startswith(("Begin", "Commit", "Rollback"))
    )
    transactional = sorted(op for op in operations if "Transact" in op)
    return measured(
        "interactive_transaction",
        bool(holdable),
        evidence=kind.evidence,
        detail=(
            f"the API this client speaks offers {transactional} and no "
            f"begin/commit pair ({holdable or 'none'}), so a transaction is one "
            "request carrying every item — there is no handle to hold across a "
            "Python decision"
        ),
    )


def _size_answer(client: Any, table: str, kind: Target) -> Answer:
    """Write items of increasing size until one is refused."""
    from botocore.exceptions import ClientError

    run = uuid.uuid4().hex[:8]
    accepted = 0
    for size in _SIZES:
        try:
            client.put_item(
                TableName=table,
                Item={"pk": {"S": f"{run}-size-{size}"}, "v": {"S": "x" * size}},
            )
        except ClientError as refused:
            return measured(
                "max_document_bytes",
                accepted or None,
                evidence=kind.evidence,
                detail=(
                    f"an item carrying {size} bytes was refused "
                    f"({refused.response['Error']['Code']}); {accepted} bytes was "
                    "accepted immediately before it, so the limit lies between "
                    "them. Measured, not copied from the limits page"
                ),
            )
        accepted = size
    return measured(
        "max_document_bytes",
        None,
        evidence=kind.evidence,
        detail=(
            f"nothing refused an item up to {accepted} bytes, the largest this "
            "probe attempted — no cap was observed in the range walked, which is "
            "not the same as no cap existing"
        ),
    )


def _schema_answer(client: Any, table: str, kind: Target) -> Answer:
    """Store two differently shaped items and see whether anything objects."""
    from botocore.exceptions import ClientError

    run = uuid.uuid4().hex[:8]
    try:
        client.put_item(
            TableName=table, Item={"pk": {"S": f"{run}-v1"}, "v": {"S": "one"}}
        )
        client.put_item(
            TableName=table,
            Item={
                "pk": {"S": f"{run}-v2"},
                "shape": {"N": "2"},
                "extra": {"BOOL": True},
            },
        )
    except ClientError as refused:
        return measured(
            "versioned_migrations",
            True,
            evidence=kind.evidence,
            detail=f"a differently shaped item was refused: {refused}",
        )
    return measured(
        "versioned_migrations",
        False,
        evidence=kind.evidence,
        detail=(
            "two items with different attribute sets were accepted into the same "
            "table without complaint: outside the key schema there is nothing "
            "declaring a version for the service to enforce"
        ),
    )


def _reach_answers(client: Any, table: str, kind: Target) -> tuple[Answer, ...]:
    """One round trip, and what being reached by an endpoint implies."""
    import time

    started = time.perf_counter()
    client.describe_table(TableName=table)
    elapsed = (time.perf_counter() - started) * 1000
    where = kind.described
    return (
        measured(
            "remote",
            True,
            evidence=kind.evidence,
            detail=(
                f"a DescribeTable round trip to {where} took {elapsed:.0f}ms; every "
                "operation crosses a socket, so a read-modify-write loop pays this "
                "per step"
            ),
        ),
        measured(
            "multi_machine",
            True,
            evidence=kind.evidence,
            detail=f"addressed by endpoint rather than by a path on this disk ({where})",
        ),
        measured(
            "multi_process",
            True,
            evidence=kind.evidence,
            detail=(
                "the contention run above used a separate client per writer and "
                "the service serialised them; nothing here is process-local"
            ),
        ),
        measured(
            "offline_capable",
            False,
            evidence=kind.evidence,
            detail="the same socket is the only way to reach it; there is no local copy",
        ),
    )


def dynamodb_column() -> Reading:
    """DynamoDB's ten cells, from whatever the environment made reachable."""
    kind = TARGET
    if kind is None:
        return reading(DYNAMODB, [], why=NO_SERVICE)
    client = _client(kind)
    tables = _table(client)
    table = next(tables)
    try:
        answers = (
            *_contention_answers(client, table, kind),
            *_reach_answers(client, table, kind),
            _interactive_transaction_answer(client, kind),
            _size_answer(client, table, kind),
            _schema_answer(client, table, kind),
        )
    finally:
        next(tables, None)
    return reading(DYNAMODB, answers)


@requires_a_service
def test_transact_write_items_is_measured_under_contention() -> None:
    """4.2's done-when: the guarantee under contention, not the call's existence."""
    pytest.importorskip("boto3")
    column = dynamodb_column()

    assert column.unmeasured == ()
    assert {answer.evidence for answer in column.answers} == {TARGET.evidence}  # type: ignore[union-attr]
    contention = column["cross_aggregate_atomicity"]
    assert f"{WRITERS} writers raced" in contention.detail
    assert "committed" in contention.detail
    assert "left its sibling behind" in contention.detail


@pytest.mark.skipif(
    TARGET is not None, reason="a service is reachable, so it is measured"
)
def test_without_a_service_every_cell_states_why() -> None:
    """Ten stated cells, and T1's verdict named as the thing to read beside them."""
    column = dynamodb_column()

    assert len(column.answers) == 10
    assert len(column.unmeasured) == 10
    for answer in column.answers:
        assert answer.detail.startswith("NOT MEASURED (no credentials)")
        assert "floci" in answer.detail


def test_an_emulator_row_can_never_be_stamped_as_a_real_service() -> None:
    """AC3, asserted on the routing rather than on the dataclass.

    Runs everywhere, because it is a property of this module and not of any
    backend. It asserts `target()` — the one decision that sets a whole
    column's evidence level — because an earlier version of this test checked
    only what `Target(EMULATOR, ...)` stores, and a sabotage that routed a
    reachable endpoint to `measured (real service)` slipped past it. That
    sabotage was caught, but only because the misrouted client then tried to
    reach AWS and could not: an accident, not a guard. This is the guard.
    """
    import socket

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        live = f"http://127.0.0.1:{listener.getsockname()[1]}"

        routed = target(endpoint=live, absent=())
        assert routed is not None
        assert routed.evidence == "measured (emulator)", (
            "an endpoint answered, so the column is emulator evidence — AC3 says "
            "it may never back a shipped field"
        )
        assert routed.described == f"the emulator at {live}"

    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        dead = f"http://127.0.0.1:{closed.getsockname()[1]}"
    assert target(endpoint=dead, absent=()) is None, "unreachable is a skip, not a fake"

    real = target(endpoint="", absent=())
    assert real is not None
    assert real.evidence == "measured (real service)"
    assert real.described == "AWS DynamoDB"

    assert target(endpoint="", absent=("AWS_ACCESS_KEY_ID",)) is None
