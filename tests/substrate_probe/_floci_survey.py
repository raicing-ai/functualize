"""Does floci implement the two wire-protocol capabilities at all? (FUN-25 task 1.1)

`StoreProfile`'s two hardest questions — `cross_aggregate_atomicity` and
`fencing` — are answered on AWS by two specific calls: `PutObject` carrying
`If-None-Match` / `If-Match`, and DynamoDB's `TransactWriteItems`. Whether the
floci emulator implements them decides whether floci can back a
`measured (emulator)` row for those questions or only for the boring ones (does
a key round-trip, does a delete delete).

This is a **survey, not a test.** It asserts nothing about floci's behaviour: a
negative answer is a finding to report, not a failure to fix. The only thing it
asserts is that it produced a verdict for each capability — the instrument
worked. Each verdict is one of:

``implemented``
    The condition was not merely accepted, it was **enforced**: the write that
    should have been refused was refused, and the write that should have been
    allowed went through.
``not implemented``
    Includes the dangerous middle case — an endpoint that *accepts* the
    conditional header and then ignores it. At the call site that is
    indistinguishable from success, which is why every capability below is
    probed by forcing its condition to fail and checking that the write was
    actually refused.
``not reachable``
    The question could not be put at all: the client has no such parameter, the
    resource never came up. Reported, never guessed around.

Run it::

    docker run -d --name floci -p 4566:4566 floci/floci:latest
    AWS_ENDPOINT_URL=http://localhost:4566 \
        uv run pytest -s tests/substrate_probe/_floci_survey.py

`-s` because the verdict is printed. Without a reachable endpoint the module
skips at import time, naming the endpoint it wanted. It does **not** fall back
to a fake — `plugins/credentials/functualize-aws/tests/test_integration_floci.py:17-19`,
whose emulator idiom, `docker run` invocation and reachability probe this module
reuses rather than reinvents:

    "It does *not* fall back to a fake: a green run that silently tested
     nothing is worse than a skip that says so."
"""

from __future__ import annotations

import contextlib
import os
import socket
import time
import uuid
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

import pytest

Answer = Literal["implemented", "not implemented", "not reachable"]

_ENDPOINT = os.environ.get("AWS_ENDPOINT_URL", "")


def _reachable(endpoint: str) -> bool:
    """A TCP connect, not an API call — lifted from the prior art at :41-64."""
    if not endpoint:
        return False
    parsed = urlparse(endpoint)
    if parsed.hostname is None:
        return False
    try:
        with socket.create_connection(
            (parsed.hostname, parsed.port or 443), timeout=1.5
        ):
            return True
    except OSError:
        return False


pytest.importorskip("boto3")

if not _reachable(_ENDPOINT):
    pytest.skip(
        f"No AWS emulator reachable at AWS_ENDPOINT_URL={_ENDPOINT!r}. Set it "
        "(e.g. http://localhost:4566) and run `docker run -d --name floci -p "
        "4566:4566 floci/floci:latest`. This survey does not fall back to a "
        "fake: an emulator that is not there answers nothing.",
        allow_module_level=True,
    )


@dataclass(frozen=True, slots=True)
class Verdict:
    """One capability's answer, plus the evidence that produced it."""

    capability: str
    answer: Answer
    detail: str


def _survey_s3_conditional_writes(client: Any) -> Verdict:
    """Is a `PutObject` precondition enforced, or merely accepted?

    Four probes, in order: create-if-absent must succeed; the same
    create-if-absent must then be **refused**; a compare-and-swap against a
    stale ETag must be refused; a compare-and-swap against the current ETag must
    succeed. Anything less than all four is `not implemented`, because a
    substrate would build its fencing on the refusal.
    """
    from botocore.exceptions import ClientError, ParamValidationError

    capability = "S3 conditional writes (PutObject If-None-Match / If-Match)"
    bucket = f"fun25-probe-{uuid.uuid4().hex[:12]}"
    key = "fencing-probe"
    steps: list[str] = []

    client.create_bucket(Bucket=bucket)
    try:
        try:
            created = client.put_object(
                Bucket=bucket, Key=key, Body=b"v1", IfNoneMatch="*"
            )
        except ParamValidationError as exc:
            return Verdict(
                capability,
                "not reachable",
                "this botocore has no IfNoneMatch parameter on PutObject, so "
                f"the question cannot be put to any endpoint from here: {exc}",
            )
        except ClientError as exc:
            return Verdict(
                capability,
                "not implemented",
                "create-if-absent was rejected on an absent key: "
                f"{exc.response['Error']['Code']}",
            )
        steps.append("create-if-absent on an absent key: accepted")

        try:
            client.put_object(Bucket=bucket, Key=key, Body=b"v2", IfNoneMatch="*")
        except ClientError as exc:
            steps.append(
                "create-if-absent on a present key: refused "
                f"({exc.response['Error']['Code']} "
                f"{exc.response['ResponseMetadata']['HTTPStatusCode']})"
            )
        else:
            body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
            return Verdict(
                capability,
                "not implemented",
                "the header is accepted and then ignored: a second "
                "create-if-absent on a present key succeeded and the stored "
                f"body is now {body!r}. " + "; ".join(steps),
            )

        etag = created["ETag"]
        try:
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=b"v3",
                IfMatch='"00000000000000000000000000000000"',
            )
        except ClientError as exc:
            steps.append(
                "compare-and-swap against a stale ETag: refused "
                f"({exc.response['Error']['Code']} "
                f"{exc.response['ResponseMetadata']['HTTPStatusCode']})"
            )
        else:
            return Verdict(
                capability,
                "not implemented",
                "If-Match is accepted and then ignored: a write against a "
                "stale ETag succeeded. " + "; ".join(steps),
            )

        try:
            client.put_object(Bucket=bucket, Key=key, Body=b"v4", IfMatch=etag)
        except ClientError as exc:
            return Verdict(
                capability,
                "not implemented",
                "a compare-and-swap against the *current* ETag was refused "
                f"({exc.response['Error']['Code']}), so the precondition is "
                "not usable for a read-modify-write. " + "; ".join(steps),
            )
        steps.append("compare-and-swap against the current ETag: accepted")

        final = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        steps.append(f"stored body after the accepted swap: {final!r}")
        return Verdict(capability, "implemented", "; ".join(steps))
    finally:
        _drain_bucket(client, bucket)


def _drain_bucket(client: Any, bucket: str) -> None:
    """Leave the emulator as we found it; never let cleanup decide a verdict."""
    with contextlib.suppress(Exception):
        listing = client.list_objects_v2(Bucket=bucket)
        for obj in listing.get("Contents", []):
            client.delete_object(Bucket=bucket, Key=obj["Key"])
        client.delete_bucket(Bucket=bucket)


def _survey_dynamodb_transact_write_items(client: Any) -> Verdict:
    """Is `TransactWriteItems` all-or-nothing, or does a doomed item leak?

    Two probes: a transaction whose conditions all hold must commit both items;
    a transaction with one violated condition must cancel **and leave neither
    item written**. A backend that writes the sibling anyway has the call but
    not the guarantee, and `cross_aggregate_atomicity` is exactly that
    guarantee.
    """
    from botocore.exceptions import ClientError

    capability = "DynamoDB TransactWriteItems"
    table = f"fun25-probe-{uuid.uuid4().hex[:12]}"
    steps: list[str] = []

    client.create_table(
        TableName=table,
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    try:
        if not _await_active(client, table):
            return Verdict(
                capability,
                "not reachable",
                f"table {table} never reached ACTIVE, so the transaction "
                "could not be attempted",
            )

        try:
            client.transact_write_items(
                TransactItems=[
                    _conditional_put(table, "alpha", "1"),
                    _conditional_put(table, "beta", "1"),
                ]
            )
        except ClientError as exc:
            return Verdict(
                capability,
                "not implemented",
                "a transaction whose conditions all hold was rejected: "
                f"{exc.response['Error']['Code']} — "
                f"{exc.response['Error'].get('Message', '')}",
            )
        steps.append("two conditional puts, all conditions holding: committed")

        if not (_present(client, table, "alpha") and _present(client, table, "beta")):
            return Verdict(
                capability,
                "not implemented",
                "the transaction reported success but the items are not "
                "readable afterwards. " + "; ".join(steps),
            )

        try:
            client.transact_write_items(
                TransactItems=[
                    _conditional_put(table, "gamma", "1"),
                    _conditional_put(table, "alpha", "2"),
                ]
            )
        except ClientError as exc:
            reasons = [
                reason.get("Code")
                for reason in exc.response.get("CancellationReasons", [])
            ]
            steps.append(
                "a transaction with one violated condition: cancelled "
                f"({exc.response['Error']['Code']}, reasons={reasons})"
            )
        else:
            return Verdict(
                capability,
                "not implemented",
                "a transaction containing a violated condition committed "
                "anyway — the call exists, the guarantee does not. " + "; ".join(steps),
            )

        leaked = _present(client, table, "gamma")
        clobbered = _value(client, table, "alpha") != "1"
        if leaked or clobbered:
            return Verdict(
                capability,
                "not implemented",
                "the cancelled transaction was not all-or-nothing: "
                f"sibling item written={leaked}, existing item modified="
                f"{clobbered}. " + "; ".join(steps),
            )
        steps.append(
            "after cancellation neither the sibling item was written nor the "
            "existing item modified: all-or-nothing holds"
        )
        return Verdict(capability, "implemented", "; ".join(steps))
    finally:
        _drop_table(client, table)


def _conditional_put(table: str, pk: str, value: str) -> dict[str, Any]:
    return {
        "Put": {
            "TableName": table,
            "Item": {"pk": {"S": pk}, "v": {"S": value}},
            "ConditionExpression": "attribute_not_exists(pk)",
        }
    }


def _await_active(client: Any, table: str, *, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.describe_table(TableName=table)["Table"]["TableStatus"]
        if status == "ACTIVE":
            return True
        time.sleep(0.2)
    return False


def _present(client: Any, table: str, pk: str) -> bool:
    return "Item" in client.get_item(TableName=table, Key={"pk": {"S": pk}})


def _value(client: Any, table: str, pk: str) -> str | None:
    item = client.get_item(TableName=table, Key={"pk": {"S": pk}}).get("Item", {})
    value = item.get("v", {}).get("S")
    return str(value) if value is not None else None


def _drop_table(client: Any, table: str) -> None:
    with contextlib.suppress(Exception):
        client.delete_table(TableName=table)


def _emulator_client(service: str) -> Any:
    """floci accepts any credentials; boto3 still insists on some."""
    import boto3

    return boto3.client(
        service,
        endpoint_url=_ENDPOINT,
        region_name="us-east-1",
        aws_access_key_id="probe",
        aws_secret_access_key="probe",  # gitleaks:allow
    )


def test_the_floci_survey_answers_both_capabilities(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ask both questions, print both answers, assert only that they were asked.

    Deliberately free of any assertion about *what* floci answers: task 1.1's
    gate is "passes or skips, never fails", because "floci does not implement
    conditional writes" is a result this ticket must report, not a regression
    this ticket must fix.
    """
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")

    verdicts = (
        _survey_s3_conditional_writes(_emulator_client("s3")),
        _survey_dynamodb_transact_write_items(_emulator_client("dynamodb")),
    )

    lines = [f"floci capability survey — endpoint {_ENDPOINT}"]
    for verdict in verdicts:
        lines.append(f"  {verdict.capability}: {verdict.answer.upper()}")
        lines.append(f"      {verdict.detail}")
    report = "\n".join(lines)
    with capsys.disabled():
        print(f"\n{report}\n")

    assert len(verdicts) == 2
    for verdict in verdicts:
        assert verdict.answer in ("implemented", "not implemented", "not reachable")
        assert verdict.detail, f"{verdict.capability} produced no evidence"
