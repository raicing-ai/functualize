"""The selection corpus: one labelled request per line, and its freeze.

The corpus is a JSON Lines file: one scenario per line, each a JSON object with
exactly the keys ``id``, ``state``, ``expected``, ``stratum``, ``rationale`` and
``origin``, in that order. A frozen version directory also holds a lock that
pins everything that could move under a number: the scenario digest, the
catalog the options come from, the selection rule that produced the decisions,
the bytes of the instrument that measures, each comparator's identity, and the
verdict constants. A later run can then prove it measured the same question.

This module is pure bookkeeping: it reads files, validates them and freezes a
version. It never calls a comparator and never runs a model.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from tests.hermetic_eval.corpus import corpus_sha256, ordered_cells
from tests.skill_router_eval.catalog import (
    OPTIONS,
    Entry,
    catalog_json,
    catalog_sha256,
)

__all__ = [
    "DECLARED",
    "INSTRUMENT_FILES",
    "REPEATS",
    "SEED",
    "TIME_BOX_HOURS",
    "VERDICT",
    "CorpusError",
    "Lock",
    "Scenario",
    "check_disjoint_from_tasks",
    "check_lock",
    "check_seeded_labels",
    "check_v1_shape",
    "corpus_sha256",
    "load_corpus",
    "ordered_cells",
    "write_lock",
]

SEED = 20261013
"""Seed the measurement cell order is derived from."""

REPEATS = 5
"""How many times every scenario is routed per comparator."""

TIME_BOX_HOURS = 72
"""Wall-clock budget the measurement run declares for itself."""

DECLARED: Mapping[str, float] = MappingProxyType(
    {"accept_at": 0.70, "min_margin": 0.10}
)
"""The gate thresholds the finding is stated against, declared before measuring."""

VERDICT: Mapping[str, int | float] = MappingProxyType(
    {"min_lead": 0.05, "max_unsafe_none": 0}
)
"""The constants that turn an accuracy table into a verdict."""

INSTRUMENT_FILES: tuple[str, ...] = tuple(
    sorted(
        (
            "evals/providers/_harness.py",
            "evals/providers/claude_agent.py",
            "evals/providers/claude_router.py",
            "evals/suites/skill-router.yaml",
            "tests/skill_router_eval/catalog.py",
            "tests/skill_router_eval/comparators.py",
            "tests/skill_router_eval/corpus.py",
            "tests/skill_router_eval/replay.py",
            "tests/skill_router_eval/select.py",
            "tests/skill_router_eval/selection.py",
        )
    )
)
"""Every file whose code decides what a cell asks or how its answer is read.

``metrics.py`` and ``report.py`` are deliberately absent: they derive numbers
from ledgers already measured, and can be re-run without invalidating a corpus.
"""

_SCENARIO_KEYS: tuple[str, ...] = (
    "id",
    "state",
    "expected",
    "stratum",
    "rationale",
    "origin",
)
_STRATA: tuple[str, ...] = ("clear", "borderline")
_SELECTION_KEYS: tuple[str, ...] = (
    "field",
    "instructions",
    "options",
    "accept_at",
    "min_margin",
    "fallback",
)
_MAX_STATE_CHARS = 600
_V1_COUNT = 40
_V1_PER_OPTION = 8
_V1_CLEAR = 5
_SEEDED_CASES = 21
_RATIONALE_SECTIONS = tuple(f"§{number}" for number in range(1, 8))
_LOCK_NAME = "corpus.lock.json"
_SCENARIOS_NAME = "scenarios.jsonl"
_SEEDED_ORIGIN = re.compile(r"triggering:([1-9][0-9]*)\Z")


class CorpusError(ValueError):
    """The corpus, its shape, its labelling or its lock does not hold."""


@dataclass(frozen=True)
class Scenario:
    """One labelled request in the corpus."""

    id: str
    state: str
    expected: str
    stratum: str
    rationale: str
    origin: str


@dataclass(frozen=True)
class Lock:
    """The pinned identity of a frozen corpus version."""

    version: str
    scenarios_sha256: str
    count: int
    per_option: Mapping[str, int]
    per_stratum: Mapping[str, int]
    seed: int
    repeats: int
    time_box_hours: int
    catalog: Mapping[str, Any]
    catalog_sha256: str
    comparators: Mapping[str, str]
    selection: Mapping[str, Any]
    instrument: Mapping[str, Any]
    declared: Mapping[str, float | int]
    verdict: Mapping[str, float | int]
    frozen_at: str


def load_corpus(path: Path) -> tuple[Scenario, ...]:
    """Read a scenario file, validating every line.

    Raises:
        CorpusError: a line breaks the scenario contract; the message starts
            ``line <n>:``.
    """
    scenarios: list[Scenario] = []
    seen: set[str] = set()
    for number, raw in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), start=1
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
        raise CorpusError(f"line {number}: empty line")
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise CorpusError(f"line {number}: not a JSON object ({exc})") from exc
    if not isinstance(payload, dict):
        raise CorpusError(f"line {number}: not a JSON object")

    keys = list(payload)
    if keys != list(_SCENARIO_KEYS):
        raise CorpusError(
            f"line {number}: keys must be {list(_SCENARIO_KEYS)}, found {keys}"
        )

    identifier = payload["id"]
    if not isinstance(identifier, str) or not identifier:
        raise CorpusError(f"line {number}: id must be a non-empty string")

    state = payload["state"]
    if not isinstance(state, str):
        raise CorpusError(f"line {number}: state must be a string")
    if not state or len(state) > _MAX_STATE_CHARS:
        raise CorpusError(
            f"line {number}: state must be 1-{_MAX_STATE_CHARS} characters, "
            f"found {len(state)}"
        )
    if state != state.strip():
        raise CorpusError(f"line {number}: state has leading or trailing whitespace")

    expected = payload["expected"]
    if expected not in OPTIONS:
        raise CorpusError(
            f"line {number}: expected must be one of {list(OPTIONS)}, "
            f"found {expected!r}"
        )

    stratum = payload["stratum"]
    if stratum not in _STRATA:
        raise CorpusError(
            f"line {number}: stratum must be one of {list(_STRATA)}, "
            f"found {stratum!r}"
        )

    rationale = payload["rationale"]
    if not isinstance(rationale, str) or not rationale.strip():
        raise CorpusError(f"line {number}: rationale must be a non-empty string")
    if not any(section in rationale for section in _RATIONALE_SECTIONS):
        raise CorpusError(
            f"line {number}: rationale must cite LABELING.md §1-§7, "
            f"found {rationale!r}"
        )

    origin = payload["origin"]
    if origin != "new" and not _SEEDED_ORIGIN.match(str(origin)):
        raise CorpusError(
            f"line {number}: origin must be 'new' or 'triggering:<n>', "
            f"found {origin!r}"
        )

    return Scenario(
        id=identifier,
        state=state,
        expected=str(expected),
        stratum=str(stratum),
        rationale=rationale,
        origin=str(origin),
    )


def check_v1_shape(scenarios: Sequence[Scenario]) -> None:
    """Assert the version 1 shape: 40 scenarios, 8 per option, 5 clear / 3 borderline.

    Raises:
        CorpusError: naming the first violated count.
    """
    if len(scenarios) != _V1_COUNT:
        raise CorpusError(f"expected {_V1_COUNT} scenarios, found {len(scenarios)}")
    wanted_ids = [f"k{index:02d}" for index in range(1, _V1_COUNT + 1)]
    if [scenario.id for scenario in scenarios] != wanted_ids:
        raise CorpusError(f"scenario ids must be k01..k{_V1_COUNT:02d} in file order")

    per_option: Counter[str] = Counter(scenario.expected for scenario in scenarios)
    for option in OPTIONS:
        if per_option[option] != _V1_PER_OPTION:
            raise CorpusError(
                f"expected {_V1_PER_OPTION} {option} scenarios, "
                f"found {per_option[option]}"
            )
        strata: Counter[str] = Counter(
            scenario.stratum for scenario in scenarios if scenario.expected == option
        )
        # Five clear of eight leaves exactly three borderline, so the option
        # count above and this one pin both strata without a second branch
        # that could never fire.
        if strata["clear"] != _V1_CLEAR:
            raise CorpusError(
                f"expected {_V1_CLEAR} clear and {_V1_PER_OPTION - _V1_CLEAR} "
                f"borderline {option} scenarios, found {strata['clear']} clear "
                f"and {strata['borderline']} borderline"
            )


def check_seeded_labels(scenarios: Sequence[Scenario], triggering_yaml: Path) -> None:
    """Assert every seeded scenario kept the label its source case declares.

    The 21 ``triggering.yaml`` cases are the seeded half of the corpus, and a
    corpus drafted to agree with them is only worth measuring if it does: a
    seeded scenario whose label drifted would report a routing error that is an
    editing error.

    Raises:
        CorpusError: the count, an origin or a label disagrees with the suite.
    """
    path = Path(triggering_yaml)
    cases = yaml.safe_load(path.read_text(encoding="utf-8"))["tests"]
    seeded = [
        scenario
        for scenario in scenarios
        if _SEEDED_ORIGIN.match(scenario.origin) is not None
    ]
    if len(seeded) != _SEEDED_CASES:
        raise CorpusError(
            f"expected {_SEEDED_CASES} triggering origins, found {len(seeded)}"
        )

    seen: set[int] = set()
    for scenario in seeded:
        number = int(_SEEDED_ORIGIN.match(scenario.origin).group(1))
        if number in seen:
            raise CorpusError(
                f"{scenario.id}: origin {scenario.origin!r} is already used"
            )
        seen.add(number)
        if number > len(cases):
            raise CorpusError(
                f"{scenario.id}: origin {scenario.origin!r} has no case in "
                f"{path.name} ({len(cases)} cases)"
            )
        expected = cases[number - 1]["vars"]["expect"]
        if scenario.expected != expected:
            raise CorpusError(
                f"{scenario.id}: origin {scenario.origin!r} is labelled "
                f"{scenario.expected!r}, that case expects {expected!r}"
            )


def check_disjoint_from_tasks(
    scenarios: Sequence[Scenario], suite_yaml: Path
) -> None:
    """Assert no scenario's state is one of the downstream task prompts.

    A state copied from a task would measure the task's own prompt, not routing
    to it — and the two must stay separable for the token comparison to mean
    anything.

    Raises:
        CorpusError: a state equals a task prompt.
    """
    path = Path(suite_yaml)
    tasks = {
        _collapse(test["vars"]["task"])
        for test in yaml.safe_load(path.read_text(encoding="utf-8"))["tests"]
        if test.get("vars", {}).get("task")
    }
    for scenario in scenarios:
        if _collapse(scenario.state) in tasks:
            raise CorpusError(
                f"{scenario.id}: state is a downstream task prompt from {path.name}"
            )


def _collapse(text: str) -> str:
    return " ".join(text.split())


def write_lock(
    version_dir: Path,
    catalog: Sequence[Entry],
    identities: Mapping[str, str],
    *,
    selection: Mapping[str, Any],
    rule_digest: str,
    instrument_sha256: str,
    frozen_at: str,
) -> Lock:
    """Freeze a version directory, refusing to overwrite an existing lock.

    ``selection`` is the C-3 ``selection`` block without ``rule_digest``: the
    block the gate was configured from. It is written with its digest so a
    reader sees the rule without decoding the digest.

    Raises:
        CorpusError: a lock already exists, or ``selection`` is not that block.
    """
    directory = Path(version_dir)
    lock_path = directory / _LOCK_NAME
    if lock_path.exists():
        raise CorpusError(
            f"{lock_path} already exists; a corpus version is frozen once"
        )
    if list(selection) != list(_SELECTION_KEYS):
        raise CorpusError(
            f"selection must hold exactly {list(_SELECTION_KEYS)}, "
            f"found {list(selection)}"
        )

    scenarios_path = directory / _SCENARIOS_NAME
    scenarios = load_corpus(scenarios_path)
    per_option: Counter[str] = Counter(scenario.expected for scenario in scenarios)
    per_stratum: Counter[str] = Counter(scenario.stratum for scenario in scenarios)
    lock = Lock(
        version=directory.name,
        scenarios_sha256=corpus_sha256(scenarios_path),
        count=len(scenarios),
        per_option={option: per_option[option] for option in OPTIONS},
        per_stratum={stratum: per_stratum[stratum] for stratum in _STRATA},
        seed=SEED,
        repeats=REPEATS,
        time_box_hours=TIME_BOX_HOURS,
        catalog=catalog_json(catalog),
        catalog_sha256=catalog_sha256(catalog),
        comparators=dict(identities),
        selection={**dict(selection), "rule_digest": rule_digest},
        instrument={"files": list(INSTRUMENT_FILES), "sha256": instrument_sha256},
        declared=dict(DECLARED),
        verdict=dict(VERDICT),
        frozen_at=frozen_at,
    )
    lock_path.write_text(
        json.dumps(_lock_to_dict(lock), indent=2) + "\n", encoding="utf-8"
    )
    return lock


def check_lock(
    version_dir: Path,
    catalog: Sequence[Entry],
    identities: Mapping[str, str],
    *,
    rule_digest: str,
    instrument_sha256: str,
) -> Lock:
    """Verify a frozen version directory against what is about to measure it.

    Every argument is re-derived from the working tree, so this is the guard
    that makes "no tuning after the first measurement" mechanical: a reworded
    ``SKILL.md``, a changed instruction, a moved threshold, an edited provider or
    a different comparator identity is a different question, and the remedy is
    a new version.

    Raises:
        CorpusError: naming the first mismatch — missing lock, scenario digest,
            count, catalog digest, selection ``rule_digest``, instrument digest
            or comparator identity.
    """
    directory = Path(version_dir)
    lock_path = directory / _LOCK_NAME
    if not lock_path.exists():
        raise CorpusError(f"missing lock file {lock_path}")
    lock = _lock_from_dict(json.loads(lock_path.read_text(encoding="utf-8")))

    scenarios_path = directory / _SCENARIOS_NAME
    actual_digest = corpus_sha256(scenarios_path)
    if lock.scenarios_sha256 != actual_digest:
        raise CorpusError(
            f"{_SCENARIOS_NAME} changed since the freeze: "
            f"{actual_digest} != {lock.scenarios_sha256}"
        )
    count = len(load_corpus(scenarios_path))
    if lock.count != count:
        raise CorpusError(f"lock counts {lock.count} scenarios, file holds {count}")

    actual_catalog = catalog_sha256(catalog)
    if lock.catalog_sha256 != actual_catalog:
        raise CorpusError(
            f"catalog changed since the freeze: {actual_catalog} != "
            f"{lock.catalog_sha256}"
        )

    if lock.selection.get("rule_digest") != rule_digest:
        raise CorpusError(
            "selection rule changed since the freeze: "
            f"{rule_digest} != {lock.selection.get('rule_digest')}"
        )

    actual_instrument = lock.instrument.get("sha256")
    if actual_instrument != instrument_sha256:
        raise CorpusError(
            f"instrument changed since the freeze: {instrument_sha256} != "
            f"{actual_instrument}"
        )

    for name, digest in identities.items():
        if lock.comparators.get(name) != digest:
            raise CorpusError(
                f"comparator {name!r} identity changed: "
                f"{digest} != {lock.comparators.get(name)}"
            )
    return lock



def _lock_to_dict(lock: Lock) -> dict[str, Any]:
    """Render a lock as the JSON-ready object it is written from."""
    return {
        "version": lock.version,
        "scenarios_sha256": lock.scenarios_sha256,
        "count": lock.count,
        "per_option": dict(lock.per_option),
        "per_stratum": dict(lock.per_stratum),
        "seed": lock.seed,
        "repeats": lock.repeats,
        "time_box_hours": lock.time_box_hours,
        "catalog": dict(lock.catalog),
        "catalog_sha256": lock.catalog_sha256,
        "comparators": dict(lock.comparators),
        "selection": dict(lock.selection),
        "instrument": dict(lock.instrument),
        "declared": dict(lock.declared),
        "verdict": dict(lock.verdict),
        "frozen_at": lock.frozen_at,
    }


def _lock_from_dict(payload: Mapping[str, Any]) -> Lock:
    """Rebuild a lock from the parsed JSON object."""
    return Lock(
        version=str(payload["version"]),
        scenarios_sha256=str(payload["scenarios_sha256"]),
        count=int(payload["count"]),
        per_option=dict(payload["per_option"]),
        per_stratum=dict(payload["per_stratum"]),
        seed=int(payload["seed"]),
        repeats=int(payload["repeats"]),
        time_box_hours=int(payload["time_box_hours"]),
        catalog=dict(payload["catalog"]),
        catalog_sha256=str(payload["catalog_sha256"]),
        comparators=dict(payload["comparators"]),
        selection=dict(payload["selection"]),
        instrument=dict(payload["instrument"]),
        declared=dict(payload["declared"]),
        verdict=dict(payload["verdict"]),
        frozen_at=str(payload["frozen_at"]),
    )
