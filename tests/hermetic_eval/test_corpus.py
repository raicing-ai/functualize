"""Offline tests for the corpus loader, the lock file and the cell order."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests.hermetic_eval import corpus
from tests.hermetic_eval.comparators import (
    DeterministicBaseline,
    FrontierRouter,
    hermetic_identity,
    identity_sha256,
)
from tests.hermetic_eval.corpus import (
    BOUNDARY,
    REPEATS,
    ROUTES,
    SEED,
    TIME_BOX_HOURS,
    CorpusError,
    Scenario,
)

#: The drafted corpus that ships with the instrument, found next to this test.
V1_SCENARIOS = (
    Path(corpus.__file__).resolve().parent / "corpus" / "v1" / "scenarios.jsonl"
)


def _line(
    scenario_id: str,
    state: str = "Where is my order?",
    expected: str = "deterministic",
    stratum: str = "clear",
    rationale: str = "§1 decides it",
) -> str:
    """Render one scenario line with the declared key order."""
    return json.dumps(
        {
            "id": scenario_id,
            "state": state,
            "expected": expected,
            "stratum": stratum,
            "rationale": rationale,
        }
    )


def _write(path: Path, lines: list[str]) -> Path:
    """Write scenario lines to a file, newline-terminated."""
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return path


def _v1_scenarios() -> list[Scenario]:
    """Build a shape-valid 40-scenario corpus: 10 per route, 6 clear + 4 borderline."""
    scenarios: list[Scenario] = []
    index = 1
    for route in ROUTES:
        for position in range(10):
            scenarios.append(
                Scenario(
                    id=f"s{index:02d}",
                    state=f"request number {index}",
                    expected=route,
                    stratum="clear" if position < 6 else "borderline",
                    rationale="§1 decides it",
                )
            )
            index += 1
    return scenarios


def test_load_corpus_reads_a_valid_file(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "scenarios.jsonl",
        [
            _line("s01"),
            _line("s02", state="Summarise this", expected="cheap_model"),
            _line(
                "s03", state="Refund my order", expected="human_review", stratum="clear"
            ),
        ],
    )
    scenarios = corpus.load_corpus(path)
    assert scenarios == (
        Scenario(
            "s01", "Where is my order?", "deterministic", "clear", "§1 decides it"
        ),
        Scenario("s02", "Summarise this", "cheap_model", "clear", "§1 decides it"),
        Scenario("s03", "Refund my order", "human_review", "clear", "§1 decides it"),
    )


@pytest.mark.parametrize(
    "line",
    [
        json.dumps(
            {
                "extra": "x",
                "id": "s01",
                "state": "Where is my order?",
                "expected": "deterministic",
                "stratum": "clear",
                "rationale": "§1 decides it",
            }
        ),
        json.dumps(
            {
                "id": "s01",
                "state": "Where is my order?",
                "expected": "deterministic",
                "stratum": "clear",
            }
        ),
        _line("s01", expected="other"),
        _line("s01", stratum="hard"),
        _line("s01", state="x" * 601),
        _line("s01", rationale=""),
    ],
    ids=[
        "extra-key",
        "missing-key",
        "bad-route",
        "bad-stratum",
        "long-state",
        "no-rationale",
    ],
)
def test_load_corpus_rejects_a_malformed_line(tmp_path: Path, line: str) -> None:
    path = _write(tmp_path / "scenarios.jsonl", [_line("s00"), line])
    with pytest.raises(CorpusError, match=r"^line 2:"):
        corpus.load_corpus(path)


def test_load_corpus_rejects_surrounding_whitespace(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "scenarios.jsonl", [_line("s01"), _line("s02", state=" pad ")]
    )
    with pytest.raises(CorpusError, match=r"^line 2: state must not have surrounding"):
        corpus.load_corpus(path)


def test_load_corpus_rejects_a_duplicate_id(tmp_path: Path) -> None:
    path = _write(tmp_path / "scenarios.jsonl", [_line("s01"), _line("s01")])
    with pytest.raises(CorpusError, match=r"^line 2: duplicate id"):
        corpus.load_corpus(path)


def test_corpus_sha256_hashes_the_raw_bytes(tmp_path: Path) -> None:
    path = _write(tmp_path / "scenarios.jsonl", [_line("s01")])
    assert corpus.corpus_sha256(path) == hashlib.sha256(path.read_bytes()).hexdigest()


def test_check_v1_shape_accepts_the_declared_shape() -> None:
    corpus.check_v1_shape(_v1_scenarios())


def test_check_v1_shape_rejects_a_short_corpus() -> None:
    with pytest.raises(CorpusError, match=r"^expected 40 scenarios"):
        corpus.check_v1_shape(_v1_scenarios()[:39])


def test_check_v1_shape_rejects_a_wrong_strata_split() -> None:
    scenarios = _v1_scenarios()
    scenarios[5] = Scenario(
        id="s06",
        state="request number 6",
        expected="deterministic",
        stratum="borderline",
        rationale="§1 decides it",
    )
    with pytest.raises(CorpusError, match=r"^expected 6 clear deterministic scenarios"):
        corpus.check_v1_shape(scenarios)


def test_v1_corpus_has_the_declared_shape() -> None:
    """The drafted corpus is loadable, C-1-shaped, and in id order."""
    scenarios = corpus.load_corpus(V1_SCENARIOS)
    corpus.check_v1_shape(scenarios)
    assert [scenario.id for scenario in scenarios] == [
        f"s{index:02d}" for index in range(1, 41)
    ]


def test_v1_lock_matches_corpus_and_comparators() -> None:
    """The frozen v1 lock still matches the scenario file and all three comparators."""
    lock = corpus.check_lock(
        V1_SCENARIOS.parent,
        {
            "deterministic": identity_sha256(DeterministicBaseline().identity()),
            "frontier": identity_sha256(FrontierRouter(cwd=".").identity()),
            "hermetic": identity_sha256(hermetic_identity()),
        },
    )
    assert lock.count == 40
    assert lock.repeats == 5
    assert lock.seed == 20261004


def test_write_lock_then_check_lock_round_trips(tmp_path: Path) -> None:
    version_dir = tmp_path / "v1"
    version_dir.mkdir()
    _write(version_dir / "scenarios.jsonl", [_line("s01"), _line("s02")])
    identities = {"deterministic": "a" * 64, "hermetic": "b" * 64}
    lock = corpus.write_lock(version_dir, identities, frozen_at="2026-10-04T20:00:00Z")
    assert lock == corpus.check_lock(version_dir, identities)
    assert lock.version == "v1"
    assert lock.count == 2
    assert lock.per_route == {"deterministic": 2}
    assert lock.seed == SEED
    assert lock.repeats == REPEATS
    assert lock.time_box_hours == TIME_BOX_HOURS
    assert dict(lock.boundary) == dict(BOUNDARY)
    on_disk = json.loads((version_dir / "corpus.lock.json").read_text(encoding="utf-8"))
    assert on_disk["comparators"] == identities


def test_write_lock_refuses_an_existing_lock(tmp_path: Path) -> None:
    version_dir = tmp_path / "v1"
    version_dir.mkdir()
    _write(version_dir / "scenarios.jsonl", [_line("s01")])
    corpus.write_lock(version_dir, {}, frozen_at="2026-10-04T20:00:00Z")
    with pytest.raises(CorpusError, match="already exists"):
        corpus.write_lock(version_dir, {}, frozen_at="2026-10-04T21:00:00Z")


def test_check_lock_rejects_a_missing_lock(tmp_path: Path) -> None:
    version_dir = tmp_path / "v1"
    version_dir.mkdir()
    _write(version_dir / "scenarios.jsonl", [_line("s01")])
    with pytest.raises(CorpusError, match="missing lock file"):
        corpus.check_lock(version_dir, {})


def test_check_lock_rejects_an_empty_frozen_at(tmp_path: Path) -> None:
    version_dir = tmp_path / "v1"
    version_dir.mkdir()
    _write(version_dir / "scenarios.jsonl", [_line("s01")])
    corpus.write_lock(version_dir, {}, frozen_at="")
    with pytest.raises(CorpusError, match="empty frozen_at"):
        corpus.check_lock(version_dir, {})


def test_check_lock_rejects_a_changed_scenario_file(tmp_path: Path) -> None:
    version_dir = tmp_path / "v1"
    version_dir.mkdir()
    path = _write(version_dir / "scenarios.jsonl", [_line("s01")])
    corpus.write_lock(version_dir, {}, frozen_at="2026-10-04T20:00:00Z")
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(CorpusError, match="changed since the freeze"):
        corpus.check_lock(version_dir, {})


def test_check_lock_rejects_a_changed_comparator_identity(tmp_path: Path) -> None:
    version_dir = tmp_path / "v1"
    version_dir.mkdir()
    _write(version_dir / "scenarios.jsonl", [_line("s01")])
    corpus.write_lock(
        version_dir, {"hermetic": "a" * 64}, frozen_at="2026-10-04T20:00:00Z"
    )
    with pytest.raises(CorpusError, match="comparator 'hermetic' identity changed"):
        corpus.check_lock(version_dir, {"hermetic": "b" * 64})


def test_ordered_cells_permutes_each_repeat_and_is_stable() -> None:
    cells = corpus.ordered_cells(["a", "b", "c"], seed=SEED, repeats=2)
    assert cells == corpus.ordered_cells(["a", "b", "c"], seed=SEED, repeats=2)
    assert len(cells) == 6
    assert [repeat for repeat, _ in cells] == [1, 1, 1, 2, 2, 2]
    for repeat in (1, 2):
        ids = [scenario_id for number, scenario_id in cells if number == repeat]
        assert sorted(ids) == ["a", "b", "c"]
