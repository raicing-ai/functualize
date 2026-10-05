"""Corpus loading, shape checking, freezing and deterministic cell ordering.

The corpus is a JSON Lines file: one scenario per line, each line a JSON object
with exactly the keys ``id``, ``state``, ``expected``, ``stratum`` and
``rationale``, in that order. A frozen version directory also holds a lock file
that pins the scenario digest, the counts and the comparator identities, so a
later run can prove it measured the same corpus and the same comparators.

This module is pure bookkeeping: it reads files, validates them and orders the
measurement cells. It never calls a comparator.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

__all__ = [
    "BOUNDARY",
    "REPEATS",
    "ROUTES",
    "SEED",
    "TIME_BOX_HOURS",
    "CorpusError",
    "Lock",
    "Scenario",
    "check_lock",
    "check_v1_shape",
    "corpus_sha256",
    "load_corpus",
    "ordered_cells",
    "write_lock",
]

ROUTES: tuple[str, ...] = (
    "deterministic",
    "cheap_model",
    "frontier_agent",
    "human_review",
)
"""The four routes a scenario may be labelled with, in fixed reporting order."""

SEED = 20261004
"""Seed the measurement cell order is derived from."""

REPEATS = 5
"""How many times every scenario is routed per comparator."""

TIME_BOX_HOURS = 72
"""Wall-clock budget the measurement run declares for itself."""

BOUNDARY: Mapping[str, float] = MappingProxyType(
    {
        "min_support": 10,
        "min_distinct_scenarios": 4,
        "max_accuracy_gap": 0.05,
        "min_coverage": 0.25,
        "min_availability": 0.90,
        "declared_accept_at": 0.70,
        "declared_min_margin": 0.10,
    }
)
"""The boundary-constant bag the lock pins; read-only by construction."""

_SCENARIO_KEYS: tuple[str, ...] = ("id", "state", "expected", "stratum", "rationale")
_STRATA: tuple[str, ...] = ("clear", "borderline")
_MAX_STATE_CHARS = 600
_V1_COUNT = 40
_V1_PER_ROUTE = 10
_V1_CLEAR = 6
_V1_BORDERLINE = 4
_LOCK_NAME = "corpus.lock.json"
_SCENARIOS_NAME = "scenarios.jsonl"


class CorpusError(ValueError):
    """The corpus, its shape or its lock file does not hold."""


@dataclass(frozen=True)
class Scenario:
    """One labelled request in the corpus."""

    id: str
    state: str
    expected: str
    stratum: str
    rationale: str


@dataclass(frozen=True)
class Lock:
    """The pinned identity of a frozen corpus version."""

    version: str
    scenarios_sha256: str
    count: int
    per_route: Mapping[str, int]
    per_stratum: Mapping[str, int]
    seed: int
    repeats: int
    time_box_hours: int
    comparators: Mapping[str, str]
    boundary: Mapping[str, float]
    frozen_at: str


def load_corpus(path: Path) -> tuple[Scenario, ...]:
    """Read a scenario file, validating every line.

    Raises:
        CorpusError: the file holds a line that breaks the scenario contract;
            the message starts ``line <n>:``.
    """
    scenarios: list[Scenario] = []
    seen: set[str] = set()
    for number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        scenario = _parse_line(number, raw)
        if scenario.id in seen:
            raise CorpusError(f"line {number}: duplicate id {scenario.id!r}")
        seen.add(scenario.id)
        scenarios.append(scenario)
    return tuple(scenarios)


def _parse_line(number: int, raw: str) -> Scenario:
    """Validate one raw line and turn it into a scenario."""
    if not raw.strip():
        raise CorpusError(f"line {number}: blank line")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise CorpusError(f"line {number}: not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise CorpusError(f"line {number}: expected a JSON object")
    if tuple(payload) != _SCENARIO_KEYS:
        wanted = ", ".join(_SCENARIO_KEYS)
        raise CorpusError(
            f"line {number}: keys must be exactly {wanted}, in that order"
        )
    for key in _SCENARIO_KEYS:
        if not isinstance(payload[key], str):
            raise CorpusError(f"line {number}: {key} must be a string")

    scenario_id: str = payload["id"]
    state: str = payload["state"]
    expected: str = payload["expected"]
    stratum: str = payload["stratum"]
    rationale: str = payload["rationale"]

    if not scenario_id:
        raise CorpusError(f"line {number}: id must not be empty")
    if not state or len(state) > _MAX_STATE_CHARS:
        raise CorpusError(
            f"line {number}: state must be 1 to {_MAX_STATE_CHARS} characters"
        )
    if state != state.strip():
        raise CorpusError(f"line {number}: state must not have surrounding whitespace")
    if expected not in ROUTES:
        raise CorpusError(f"line {number}: expected must be one of {', '.join(ROUTES)}")
    if stratum not in _STRATA:
        raise CorpusError(f"line {number}: stratum must be one of {', '.join(_STRATA)}")
    if not rationale:
        raise CorpusError(f"line {number}: rationale must not be empty")
    return Scenario(
        id=scenario_id,
        state=state,
        expected=expected,
        stratum=stratum,
        rationale=rationale,
    )


def corpus_sha256(path: Path) -> str:
    """Return the SHA-256 hex digest of the file's raw bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_v1_shape(scenarios: Sequence[Scenario]) -> None:
    """Assert the version 1 corpus shape: 40 scenarios, 10 per route, 6/4 strata.

    Raises:
        CorpusError: naming the first violated count.
    """
    if len(scenarios) != _V1_COUNT:
        raise CorpusError(f"expected {_V1_COUNT} scenarios, found {len(scenarios)}")
    wanted_ids = [f"s{index:02d}" for index in range(1, _V1_COUNT + 1)]
    if [scenario.id for scenario in scenarios] != wanted_ids:
        raise CorpusError(f"scenario ids must be s01..s{_V1_COUNT:02d} in file order")
    per_route: Counter[str] = Counter(scenario.expected for scenario in scenarios)
    for route in ROUTES:
        if per_route[route] != _V1_PER_ROUTE:
            raise CorpusError(
                f"expected {_V1_PER_ROUTE} {route} scenarios, found {per_route[route]}"
            )
        strata: Counter[str] = Counter(
            scenario.stratum for scenario in scenarios if scenario.expected == route
        )
        if strata["clear"] != _V1_CLEAR:
            raise CorpusError(
                f"expected {_V1_CLEAR} clear {route} scenarios, found {strata['clear']}"
            )
        if strata["borderline"] != _V1_BORDERLINE:
            raise CorpusError(
                f"expected {_V1_BORDERLINE} borderline {route} scenarios, "
                f"found {strata['borderline']}"
            )


def write_lock(
    version_dir: Path,
    identities: Mapping[str, str],
    *,
    frozen_at: str,
) -> Lock:
    """Freeze a version directory, refusing to overwrite an existing lock.

    Raises:
        CorpusError: a lock already exists in ``version_dir``.
    """
    lock_path = version_dir / _LOCK_NAME
    if lock_path.exists():
        raise CorpusError(
            f"{lock_path} already exists; a corpus version is frozen once"
        )
    scenarios = load_corpus(version_dir / _SCENARIOS_NAME)
    lock = Lock(
        version=version_dir.name,
        scenarios_sha256=corpus_sha256(version_dir / _SCENARIOS_NAME),
        count=len(scenarios),
        per_route=dict(Counter(scenario.expected for scenario in scenarios)),
        per_stratum=dict(Counter(scenario.stratum for scenario in scenarios)),
        seed=SEED,
        repeats=REPEATS,
        time_box_hours=TIME_BOX_HOURS,
        comparators=dict(identities),
        boundary=dict(BOUNDARY),
        frozen_at=frozen_at,
    )
    lock_path.write_text(
        json.dumps(_lock_to_dict(lock), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return lock


def check_lock(version_dir: Path, identities: Mapping[str, str]) -> Lock:
    """Verify a frozen version directory against the comparators about to run.

    Raises:
        CorpusError: the lock is missing or empty-dated, the scenario digest or
            count no longer matches, or a comparator identity moved.
    """
    lock_path = version_dir / _LOCK_NAME
    if not lock_path.exists():
        raise CorpusError(f"missing lock file {lock_path}")
    lock = _lock_from_dict(json.loads(lock_path.read_text(encoding="utf-8")))
    if not lock.frozen_at:
        raise CorpusError("lock file has an empty frozen_at")
    actual_digest = corpus_sha256(version_dir / _SCENARIOS_NAME)
    if lock.scenarios_sha256 != actual_digest:
        raise CorpusError(
            f"{_SCENARIOS_NAME} changed since the freeze: "
            f"{actual_digest} != {lock.scenarios_sha256}"
        )
    count = len(load_corpus(version_dir / _SCENARIOS_NAME))
    if lock.count != count:
        raise CorpusError(f"lock counts {lock.count} scenarios, file holds {count}")
    for name, digest in identities.items():
        if lock.comparators.get(name) != digest:
            raise CorpusError(
                f"comparator {name!r} identity changed: "
                f"{digest} != {lock.comparators.get(name)}"
            )
    return lock


def ordered_cells(
    ids: Sequence[str],
    *,
    seed: int,
    repeats: int,
) -> list[tuple[int, str]]:
    """Return ``(repeat, scenario id)`` cells in the frozen measurement order."""
    return [
        (repeat, scenario_id)
        for repeat in range(1, repeats + 1)
        for scenario_id in random.Random(seed + repeat).sample(list(ids), k=len(ids))
    ]


def _lock_to_dict(lock: Lock) -> dict[str, Any]:
    """Render a lock as the JSON-ready object it is written from."""
    return {
        "version": lock.version,
        "scenarios_sha256": lock.scenarios_sha256,
        "count": lock.count,
        "per_route": dict(lock.per_route),
        "per_stratum": dict(lock.per_stratum),
        "seed": lock.seed,
        "repeats": lock.repeats,
        "time_box_hours": lock.time_box_hours,
        "comparators": dict(lock.comparators),
        "boundary": dict(lock.boundary),
        "frozen_at": lock.frozen_at,
    }


def _lock_from_dict(payload: Mapping[str, Any]) -> Lock:
    """Rebuild a lock from the parsed JSON object."""
    return Lock(
        version=str(payload["version"]),
        scenarios_sha256=str(payload["scenarios_sha256"]),
        count=int(payload["count"]),
        per_route=dict(payload["per_route"]),
        per_stratum=dict(payload["per_stratum"]),
        seed=int(payload["seed"]),
        repeats=int(payload["repeats"]),
        time_box_hours=int(payload["time_box_hours"]),
        comparators=dict(payload["comparators"]),
        boundary=dict(payload["boundary"]),
        frozen_at=str(payload["frozen_at"]),
    )
