"""The sentences a row prints, derived from what it measured.

Three rows made a claim in fixed prose beside an assertion that did not carry
it, which is the one way this instrument could publish its own sentence instead
of the service's answer:

- **B2** printed "confidence never exceeded max(probabilities) in this run"
  while asserting only that the two ever *differed*: a run whose confidence was
  the larger number would have printed that sentence beside a negative gap.
- **B3** is named for two properties — the key order is neither the request's
  nor stable across identical calls — and asserted one. `len(matching) <
  len(orders)` holds the first and says nothing about the second: a service
  answering in one fixed, non-request order satisfies it while being perfectly
  stable.
- **E16** counted "… shapes over 5 non-422 refusals" over a sample containing
  `E1`, a 422. The count of shapes (3) was right; the adjective was not, and
  nothing in the run could catch it, because the statuses were never read.

**F4** is the fourth, and the fault is a scope rather than a sentence. The row
counts the round trips and `429` refusals a run met, and `client.py` keeps both
counters in process-local lists: under `pytest -n auto` every xdist worker holds
its own copy and plays only the share of the items the scheduler gave it, so a
worker's number counts the harness. The row is therefore a claim about one
**serial run** — the mode is in the label — and a distributed session reports
the cell as unmeasured with that reason instead of filling it. Only a serial run
can be asked the question the row exists to answer: what this account's budget
did to this matrix.

Each claim is a function of the measurement it describes, and each row asserts
the same input it printed, so a sentence cannot outlive the assertion under it.
`test_gating.py` falsifies every one of them offline.

They live here rather than beside their rows because a measurement module gates
itself at import — `require_env` and `require_endpoint` run in its body — so an
offline falsifier cannot import one without a credential and a socket.
`conftest.py` keeps this file out of the measurement collection for the same
reason it keeps the transport out: this is a part of the instrument, not a row
of the matrix.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Final

#: What row E16 parses, chosen to span the envelopes that row names: `E1` is the
#: request-shape 422 (`detail` as a list of paths), `E4` the tagged union 400
#: (`detail` as an object), `E8` and `E11` the 401s (`type` + `error`, the
#: credential and the model resolver), `E9` the upstream 400 (`error` alone).
#: The label is built from the statuses the run met for these, so it can neither
#: call them all non-422 — `E1` is a 422 — nor count a set it did not parse.
REFUSAL_SAMPLE: Final[tuple[str, ...]] = ("E1", "E4", "E8", "E9", "E11")

#: The session row F4's count is a claim about: one process playing the whole
#: matrix, so `client.py`'s round-trip and refusal lists hold the run and not a
#: slice of it. The label carries the mode because the number is only the run's
#: in that one — "the run" beside a number the scheduler sized is the same
#: over-claim as a fixed sentence beside an assertion that does not carry it.
SERIAL_MODE: Final[str] = "a serial run"

#: The variable xdist sets in each worker process it starts, and nowhere else.
#: `tests/conftest.py::_timing_instrumentation` reads the same one to name the
#: sources of timing distortion, so this asks the repository's own question in
#: the repository's own way.
WORKER_ENV: Final[str] = "PYTEST_XDIST_WORKER"

#: How many workers there are, which xdist publishes only in a worker process
#: and only in a recent one. Read because it distinguishes the two distributed
#: sessions that matter here: `-n 1` is one process playing every item, so its
#: counters are the run's, while `-n auto` is several and each holds a slice.
WORKERS_ENV: Final[str] = "PYTEST_XDIST_WORKER_COUNT"


def load_label() -> str:
    """Row F4's name: the mode the count is a claim about, stated in the label."""
    return f"load refusals met by {SERIAL_MODE}"


def distributed_reason(worker: str | None, workers: str | None = None) -> str | None:
    """Why F4 leaves its cell unmeasured in this session, or `None` when it can.

    `worker` is the xdist worker id this process was handed, or `None` in a
    session that is not distributed; `workers` is how many workers xdist says
    there are, when it says. The counters F4 reads are process-local, so the
    row's number is the run's in a session that plays the whole matrix in one
    process — a plain run, or `-n 1`, whose one worker does every item — and is a
    slice of it in a session that spreads the matrix over workers: under `-n
    auto`, which is what CI's full tier runs, each worker collects this whole
    directory and plays its own subset, holding a slice of the round trips whose
    size the scheduler chose. Nothing in the item's own process can turn a slice
    into the run's total, and a number that counts the harness under a label that
    says "the run" is the defect this module exists to prevent; the row is
    withheld instead, and the reason names the command that can measure it.

    An unreadable worker count is read as distributed. Refusing to report is
    recoverable — the reason says which command fills the cell — while reporting
    a slice as the run is exactly what this instrument exists to catch, so the
    ambiguity resolves that way.

    The mode is decided here and nowhere else: `conftest.py` applies this to the
    item, `load_label` names the same mode in the cell it would fill, and the
    falsifiers assert both, so the claim and the session cannot drift apart
    without a test failing.
    """
    if not worker:
        return None
    if workers is not None and workers.strip() == "1":
        return None
    where = (
        f"{workers} xdist workers, this one {worker!r}"
        if workers
        else f"xdist worker {worker!r}, with the worker count this xdist does not publish"
    )
    return (
        f"Jev / System One: NOT MEASURED (distributed session) — this session "
        f"ran the probe over {where}, and `F4` counts the round trips and load "
        f"refusals of {SERIAL_MODE} in the one process that made them. Every "
        f"worker holds its own counters and plays the share of the items it was "
        f"given, so a worker's number counts the harness and not the run. "
        f"Measure this cell serially: "
        f"`uv run pytest -q -m jev_probe -p no:randomly`."
    )


def exceeded_max_probability(gaps: Iterable[float]) -> list[float]:
    """The gaps below zero: the answers where `confidence` was the larger number.

    `gaps` is `max(probabilities) − confidence` per answer. Row B2's sentence
    says which way the two fall, and this list decides it: empty means the
    confidence never exceeded the largest probability, non-empty means it did.
    The sentence and the assertion both read this function, so a run that
    exceeded cannot print the sentence that says it never did — which is exactly
    what a fixed sentence beside `assert len(differ) > 0` allowed.
    """
    return [gap for gap in gaps if gap < 0]


def confidence_claim(gaps: Sequence[float]) -> str:
    """Row B2's clause about `confidence` against `max(probabilities)`.

    Two sentences, and the gaps choose: one says the confidence never exceeded
    the largest probability, the other names the exceedance and how far it went.
    Nothing else is printed in that position.
    """
    over = exceeded_max_probability(gaps)
    if not over:
        return "confidence never exceeded max(probabilities) in this run"
    return (
        f"confidence exceeded max(probabilities) in {len(over)}/{len(gaps)} "
        f"answers, by up to {abs(min(over)):.4g}"
    )


def distinct_key_orders(orders: Iterable[Sequence[str]]) -> list[tuple[str, ...]]:
    """The distinct `probabilities` key orders, in the order they first arrived.

    Row B3 is named for two properties: the order is neither the request's nor
    stable across identical calls. This is the second — one entry means every
    identical call came back in one order, which is the stable case the row
    claims not to see — and the row asserts this list is longer than one.
    """
    distinct: list[tuple[str, ...]] = []
    for order in orders:
        seen = tuple(order)
        if seen not in distinct:
            distinct.append(seen)
    return distinct


def matching_key_orders(
    orders: Iterable[Sequence[str]], requested: Sequence[str]
) -> list[tuple[str, ...]]:
    """The answers whose key order is the request's, key for key.

    The first half of row B3's claim, and the half the row already asserted: at
    least one answer must arrive in an order other than the one the request
    sent, or the row's "not in request order" would be unmeasured.
    """
    wanted = list(requested)
    return [order for order in orders if list(order) == wanted]


def key_order_claim(orders: Sequence[Sequence[str]], requested: Sequence[str]) -> str:
    """Row B3's value: how many orders over how many answers, and how many matched."""
    distinct = distinct_key_orders(orders)
    matching = matching_key_orders(orders, requested)
    return (
        f"{len(distinct)} distinct orders over {len(orders)} answers; "
        f"{len(matching)} matched the request order"
    )


def refusal_shape_claim(
    envelopes: Mapping[str, Sequence[str]], statuses: Mapping[str, int]
) -> str:
    """Row E16's value: distinct envelope shapes over refusals, by status met.

    `envelopes` maps a case id to the field names the service returned, and
    `statuses` the status the run met for it. Both the shape count and the
    statuses come from the run, so the label states what was parsed: a hard-coded
    "5 non-422 refusals" beside a sample containing a 422 is a sentence no
    measurement could confirm, and none did.
    """
    shapes = {tuple(shape) for shape in envelopes.values()}
    spread = " · ".join(
        f"{count} × {status}"
        for status, count in sorted(Counter(statuses[key] for key in envelopes).items())
    )
    return f"{len(shapes)} shapes over {len(envelopes)} refusals: {spread}"
