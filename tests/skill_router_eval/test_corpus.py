"""The corpus contract: a labelled line, a fixed shape, and an unbreakable freeze."""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import pytest

from tests.skill_router_eval import replay
from tests.skill_router_eval.catalog import (
    NONE,
    OPTIONS,
    catalog_sha256,
    derive_catalog,
    option_meanings,
)
from tests.skill_router_eval.comparators import identity_sha256
from tests.skill_router_eval.corpus import (
    DECLARED,
    INSTRUMENT_FILES,
    REPEATS,
    SEED,
    TIME_BOX_HOURS,
    VERDICT,
    CorpusError,
    check_disjoint_from_tasks,
    check_lock,
    check_seeded_labels,
    check_v1_shape,
    load_corpus,
    write_lock,
)

CATALOG = derive_catalog()
SELECTION = {
    "field": "skill",
    "instructions": "Choose the one functualize skill.",
    "options": option_meanings(CATALOG),
    "accept_at": 0.70,
    "min_margin": 0.10,
    "fallback": None,
}
RULE_DIGEST = "sha256:" + "a" * 64
INSTRUMENT_DIGEST = "b" * 64
IDENTITIES = {"deterministic": "c" * 64, "hermetic": "d" * 64}


def _scenario(**overrides: object) -> dict[str, object]:
    scenario: dict[str, object] = {
        "id": "k01",
        "state": "func: command not found after pip install",
        "expected": "functualize-cli",
        "stratum": "clear",
        "rationale": "Installing and locating the func tool (rubric §3).",
        "origin": "new",
    }
    scenario.update(overrides)
    return scenario


def _lines(scenarios: list[dict[str, object]]) -> list[str]:
    return [json.dumps(scenario) for scenario in scenarios]


def _corpus(tmp_path: Path, scenarios: list[dict[str, object]]) -> Path:
    path = tmp_path / "scenarios.jsonl"
    path.write_text("\n".join(_lines(scenarios)) + "\n", encoding="utf-8")
    return path


def _version_dir(tmp_path: Path, count: int = 2) -> Path:
    directory = tmp_path / "v1"
    directory.mkdir()
    scenarios = [_scenario(id=f"k{index:02d}") for index in range(1, count + 1)]
    (directory / "scenarios.jsonl").write_text(
        "\n".join(_lines(scenarios)) + "\n", encoding="utf-8"
    )
    return directory


def _freeze(directory: Path) -> Path:
    write_lock(
        directory,
        CATALOG,
        IDENTITIES,
        selection=SELECTION,
        rule_digest=RULE_DIGEST,
        instrument_sha256=INSTRUMENT_DIGEST,
        frozen_at="2026-10-31T00:00:00Z",
    )
    return directory / "corpus.lock.json"


def _v1_lines() -> list[dict[str, object]]:
    """40 scenarios: 8 per option, 5 clear and 3 borderline inside each."""
    lines: list[dict[str, object]] = []
    for index in range(1, 41):
        option = OPTIONS[((index - 1) // 8) % len(OPTIONS)]
        position = (index - 1) % 8
        lines.append(
            _scenario(
                id=f"k{index:02d}",
                state=f"request number {index} about {option}",
                expected=option,
                stratum="clear" if position < 5 else "borderline",
                rationale=f"Clause {option} applies (rubric §{(index % 7) + 1}).",
            )
        )
    return lines


# --------------------------------------------------------------------------
# Declaration
# --------------------------------------------------------------------------


def test_the_declared_constants_are_the_ones_the_finding_rests_on() -> None:
    assert SEED == 20261013
    assert REPEATS == 5
    assert TIME_BOX_HOURS == 72
    assert dict(DECLARED) == {"accept_at": 0.70, "min_margin": 0.10}
    assert dict(VERDICT) == {"min_lead": 0.05, "max_unsafe_none": 0}
    with pytest.raises(TypeError):
        DECLARED["accept_at"] = 0.9  # type: ignore[index]


def test_the_instrument_lists_ten_files_sorted_and_omits_what_only_derives() -> None:
    assert len(INSTRUMENT_FILES) == 10
    assert list(INSTRUMENT_FILES) == sorted(INSTRUMENT_FILES)
    assert "tests/skill_router_eval/metrics.py" not in INSTRUMENT_FILES
    assert "tests/skill_router_eval/report.py" not in INSTRUMENT_FILES
    assert "evals/suites/skill-router.yaml" in INSTRUMENT_FILES


# --------------------------------------------------------------------------
# A scenario line
# --------------------------------------------------------------------------


def test_a_well_formed_corpus_loads_in_file_order(tmp_path: Path) -> None:
    path = _corpus(
        tmp_path,
        [
            _scenario(id="k01"),
            _scenario(id="k02", expected=NONE, origin="triggering:3"),
        ],
    )

    scenarios = load_corpus(path)

    assert [scenario.id for scenario in scenarios] == ["k01", "k02"]
    assert scenarios[1].expected == NONE
    assert scenarios[1].origin == "triggering:3"
    assert scenarios[0].rationale.endswith("(rubric §3).")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"state": ""}, "state must be 1-600 characters"),
        ({"state": "  leading"}, "leading or trailing whitespace"),
        ({"state": "x" * 601}, "state must be 1-600 characters"),
        ({"expected": "functualize-both"}, "expected must be one of"),
        ({"stratum": "hard"}, "stratum must be one of"),
        ({"rationale": "Because."}, "must cite LABELING.md"),
        ({"origin": "triggering:0"}, "origin must be"),
        ({"origin": "seeded:4"}, "origin must be"),
    ],
)
def test_a_line_that_breaks_the_contract_is_refused_by_line_number(
    tmp_path: Path, overrides: dict[str, object], message: str
) -> None:
    path = _corpus(tmp_path, [_scenario(), _scenario(id="k02", **overrides)])

    with pytest.raises(CorpusError) as raised:
        load_corpus(path)

    assert str(raised.value).startswith("line 2:")
    assert message in str(raised.value)


def test_the_keys_must_be_exactly_the_six_in_order(tmp_path: Path) -> None:
    payload = _scenario()
    reordered = {
        key: payload[key]
        for key in ("state", "id", "expected", "stratum", "rationale", "origin")
    }
    path = _corpus(tmp_path, [reordered])

    with pytest.raises(CorpusError, match=r"line 1: keys must be"):
        load_corpus(path)


def test_an_extra_key_is_refused(tmp_path: Path) -> None:
    path = _corpus(tmp_path, [_scenario(difficulty=3)])

    with pytest.raises(CorpusError, match=r"line 1: keys must be"):
        load_corpus(path)


def test_a_duplicate_id_is_refused(tmp_path: Path) -> None:
    path = _corpus(tmp_path, [_scenario(), _scenario()])

    with pytest.raises(CorpusError, match=r"line 2: duplicate id 'k01'"):
        load_corpus(path)


def test_a_line_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "scenarios.jsonl"
    path.write_text('["k01"]\n', encoding="utf-8")

    with pytest.raises(CorpusError, match=r"line 1: not a JSON object"):
        load_corpus(path)


def test_a_line_that_is_not_json_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "scenarios.jsonl"
    path.write_text(json.dumps(_scenario()) + "\nnot json\n", encoding="utf-8")

    with pytest.raises(CorpusError, match=r"line 2: not a JSON object"):
        load_corpus(path)


# --------------------------------------------------------------------------
# The version 1 shape
# --------------------------------------------------------------------------


def test_the_v1_shape_accepts_eight_per_option_and_five_three_per_stratum(
    tmp_path: Path,
) -> None:
    check_v1_shape(load_corpus(_corpus(tmp_path, _v1_lines())))


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda lines: lines[:-1], "expected 40 scenarios, found 39"),
        (
            lambda lines: [dict(lines[0], id="k41"), *lines[1:]],
            "scenario ids must be k01..k40 in file order",
        ),
        (
            lambda lines: [*lines[1:], dict(lines[0], id="k41")],
            "scenario ids must be k01..k40 in file order",
        ),
        (
            lambda lines: [
                *lines[:8],
                dict(lines[8], expected="functualize"),
                *lines[9:],
            ],
            "expected 8 functualize scenarios, found 9",
        ),
        (
            lambda lines: [
                dict(lines[0], stratum="borderline"),
                *lines[1:],
            ],
            "expected 5 clear and 3 borderline functualize scenarios, found 4 clear",
        ),
    ],
)
def test_the_v1_shape_names_the_count_it_lost(
    tmp_path: Path, mutate, message: str
) -> None:
    lines = mutate(_v1_lines())
    path = _corpus(tmp_path, lines)

    with pytest.raises(CorpusError, match=message):
        check_v1_shape(load_corpus(path))


# --------------------------------------------------------------------------
# The seeded half
# --------------------------------------------------------------------------


def _triggering(tmp_path: Path, expects: list[str]) -> Path:
    path = tmp_path / "triggering.yaml"
    body = "\n".join(
        "  - description: case\n    vars:\n      expect: " + expect
        for expect in expects
    )
    path.write_text(f"tests:\n{body}\n", encoding="utf-8")
    return path


def _seeded(count: int = 21) -> list[dict[str, object]]:
    return [
        _scenario(id=f"k{index:02d}", origin=f"triggering:{index}")
        for index in range(1, count + 1)
    ]


def test_a_seeded_corpus_must_agree_with_its_cases(tmp_path: Path) -> None:
    cases = _triggering(tmp_path, ["functualize-cli"] * 21)

    check_seeded_labels(load_corpus(_corpus(tmp_path, _seeded())), cases)


def test_the_seeded_count_is_exactly_the_triggering_cases(tmp_path: Path) -> None:
    cases = _triggering(tmp_path, ["functualize-cli"] * 21)

    with pytest.raises(CorpusError, match="expected 21 triggering origins, found 20"):
        check_seeded_labels(load_corpus(_corpus(tmp_path, _seeded(count=20))), cases)


def test_a_reused_origin_is_refused(tmp_path: Path) -> None:
    cases = _triggering(tmp_path, ["functualize-cli"] * 21)
    lines = _seeded()
    lines[1] = dict(lines[1], origin="triggering:1")

    with pytest.raises(CorpusError, match="origin 'triggering:1' is already used"):
        check_seeded_labels(load_corpus(_corpus(tmp_path, lines)), cases)


def test_an_origin_past_the_last_case_is_refused(tmp_path: Path) -> None:
    cases = _triggering(tmp_path, ["functualize-cli"] * 20)

    with pytest.raises(CorpusError, match=r"origin 'triggering:21' has no case"):
        check_seeded_labels(load_corpus(_corpus(tmp_path, _seeded())), cases)


def test_a_drifted_label_is_refused(tmp_path: Path) -> None:
    cases = _triggering(tmp_path, ["functualize-cli"] * 21)
    lines = _seeded()
    lines[4] = dict(lines[4], expected="none")

    with pytest.raises(
        CorpusError,
        match=r"k05: origin 'triggering:5' is labelled 'none', that case expects",
    ):
        check_seeded_labels(load_corpus(_corpus(tmp_path, lines)), cases)


# --------------------------------------------------------------------------
# Disjointness from the downstream tasks
# --------------------------------------------------------------------------


def _tasks(tmp_path: Path, tasks: list[str]) -> Path:
    path = tmp_path / "skill-router.yaml"
    body = "\n".join(
        f"  - description: case\n    vars:\n      task: >-\n        {task}"
        for task in tasks
    )
    path.write_text(f"tests:\n{body}\n", encoding="utf-8")
    return path


def test_a_state_equal_to_a_task_prompt_is_refused(tmp_path: Path) -> None:
    suite = _tasks(tmp_path, ["Add a job called notify that posts a webhook."])
    scenarios = load_corpus(
        _corpus(
            tmp_path,
            [
                _scenario(state="Add a job called notify that posts a webhook."),
                _scenario(id="k02", state="func: command not found"),
            ],
        )
    )

    with pytest.raises(CorpusError, match="k01: state is a downstream task prompt"):
        check_disjoint_from_tasks(scenarios, suite)


def test_a_corpus_disjoint_from_the_tasks_passes(tmp_path: Path) -> None:
    suite = _tasks(tmp_path, ["Add a job called notify that posts a webhook."])
    scenarios = load_corpus(
        _corpus(tmp_path, [_scenario(state="func: command not found")])
    )

    check_disjoint_from_tasks(scenarios, suite)


# --------------------------------------------------------------------------
# The lock
# --------------------------------------------------------------------------


def test_a_lock_round_trips_and_pins_the_whole_question(tmp_path: Path) -> None:
    directory = _version_dir(tmp_path)
    lock_path = _freeze(directory)

    lock = check_lock(
        directory,
        CATALOG,
        IDENTITIES,
        rule_digest=RULE_DIGEST,
        instrument_sha256=INSTRUMENT_DIGEST,
    )

    assert lock.version == "v1"
    assert lock.count == 2
    assert lock.seed == SEED
    assert lock.repeats == REPEATS
    assert lock.time_box_hours == TIME_BOX_HOURS
    assert dict(lock.per_option) == {
        option: (2 if option == "functualize-cli" else 0) for option in OPTIONS
    }
    assert dict(lock.per_stratum) == {"clear": 2, "borderline": 0}
    assert dict(lock.declared) == dict(DECLARED)
    assert dict(lock.verdict) == dict(VERDICT)
    assert dict(lock.comparators) == IDENTITIES
    assert lock.catalog_sha256 == catalog_sha256(CATALOG)
    assert dict(lock.catalog)["skills"][0]["name"] == "functualize"
    assert lock.selection["rule_digest"] == RULE_DIGEST
    assert lock.selection["fallback"] is None
    assert dict(lock.instrument) == {
        "files": list(INSTRUMENT_FILES),
        "sha256": INSTRUMENT_DIGEST,
    }
    assert lock.frozen_at == "2026-10-31T00:00:00Z"

    on_disk = json.loads(lock_path.read_text(encoding="utf-8"))
    assert list(on_disk) == [
        "version",
        "scenarios_sha256",
        "count",
        "per_option",
        "per_stratum",
        "seed",
        "repeats",
        "time_box_hours",
        "catalog",
        "catalog_sha256",
        "comparators",
        "selection",
        "instrument",
        "declared",
        "verdict",
        "frozen_at",
    ]
    assert list(on_disk["selection"]) == [
        "field",
        "instructions",
        "options",
        "accept_at",
        "min_margin",
        "fallback",
        "rule_digest",
    ]


def test_a_second_freeze_is_refused(tmp_path: Path) -> None:
    directory = _version_dir(tmp_path)
    lock_path = _freeze(directory)

    with pytest.raises(CorpusError, match="frozen once"):
        _freeze(directory)
    assert lock_path.read_text(encoding="utf-8").count("rule_digest") == 1


def test_a_selection_block_with_the_wrong_keys_is_refused(tmp_path: Path) -> None:
    directory = _version_dir(tmp_path)

    with pytest.raises(CorpusError, match="selection must hold exactly"):
        write_lock(
            directory,
            CATALOG,
            IDENTITIES,
            selection={"field": "skill"},
            rule_digest=RULE_DIGEST,
            instrument_sha256=INSTRUMENT_DIGEST,
            frozen_at="2026-10-31T00:00:00Z",
        )


def test_a_missing_lock_is_refused(tmp_path: Path) -> None:
    directory = _version_dir(tmp_path)

    with pytest.raises(CorpusError, match="missing lock file"):
        check_lock(
            directory,
            CATALOG,
            IDENTITIES,
            rule_digest=RULE_DIGEST,
            instrument_sha256=INSTRUMENT_DIGEST,
        )


def test_a_changed_scenario_file_is_refused(tmp_path: Path) -> None:
    directory = _version_dir(tmp_path)
    _freeze(directory)
    scenarios_path = directory / "scenarios.jsonl"
    scenarios_path.write_text(
        scenarios_path.read_text(encoding="utf-8").replace("not found", "missing"),
        encoding="utf-8",
    )

    with pytest.raises(CorpusError, match="scenarios.jsonl changed since the freeze"):
        check_lock(
            directory,
            CATALOG,
            IDENTITIES,
            rule_digest=RULE_DIGEST,
            instrument_sha256=INSTRUMENT_DIGEST,
        )


def test_a_changed_count_is_refused(tmp_path: Path) -> None:
    directory = _version_dir(tmp_path)
    lock_path = _freeze(directory)
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    payload["count"] = 40
    lock_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(CorpusError, match="lock counts 40 scenarios, file holds 2"):
        check_lock(
            directory,
            CATALOG,
            IDENTITIES,
            rule_digest=RULE_DIGEST,
            instrument_sha256=INSTRUMENT_DIGEST,
        )


def test_a_changed_catalog_is_refused(tmp_path: Path) -> None:
    directory = _version_dir(tmp_path)
    _freeze(directory)
    reworded = dataclasses.replace(CATALOG[0], description="Something else.")

    with pytest.raises(CorpusError, match="catalog changed since the freeze"):
        check_lock(
            directory,
            (reworded, *CATALOG[1:]),
            IDENTITIES,
            rule_digest=RULE_DIGEST,
            instrument_sha256=INSTRUMENT_DIGEST,
        )


def test_a_changed_selection_rule_is_refused(tmp_path: Path) -> None:
    directory = _version_dir(tmp_path)
    _freeze(directory)

    with pytest.raises(CorpusError, match="selection rule changed since the freeze"):
        check_lock(
            directory,
            CATALOG,
            IDENTITIES,
            rule_digest="sha256:" + "e" * 64,
            instrument_sha256=INSTRUMENT_DIGEST,
        )


def test_a_changed_instrument_is_refused(tmp_path: Path) -> None:
    directory = _version_dir(tmp_path)
    _freeze(directory)

    with pytest.raises(CorpusError, match="instrument changed since the freeze"):
        check_lock(
            directory,
            CATALOG,
            IDENTITIES,
            rule_digest=RULE_DIGEST,
            instrument_sha256="f" * 64,
        )


def test_a_moved_comparator_identity_is_refused(tmp_path: Path) -> None:
    directory = _version_dir(tmp_path)
    _freeze(directory)

    with pytest.raises(
        CorpusError, match="comparator 'deterministic' identity changed"
    ):
        check_lock(
            directory,
            CATALOG,
            {**IDENTITIES, "deterministic": "0" * 64},
            rule_digest=RULE_DIGEST,
            instrument_sha256=INSTRUMENT_DIGEST,
        )


# --------------------------------------------------------------------------
# The rubric that produced the labels
# --------------------------------------------------------------------------

LABELING = Path(__file__).resolve().parent / "corpus" / "v1" / "LABELING.md"


def _sections() -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = ""
    for line in LABELING.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current:
            sections[current].append(line)
    return sections


def test_the_rubric_has_seven_clauses_in_order() -> None:
    assert list(_sections()) == [
        "§1 functualize",
        "§2 functualize-app",
        "§3 functualize-cli",
        "§4 functualize-skill",
        "§5 none",
        "§6 tie-breaks",
        "§7 two-skill requests",
    ]


def test_each_option_clause_quotes_the_catalog_meaning_verbatim() -> None:
    sections = _sections()
    meanings = option_meanings(CATALOG)

    for number, option in enumerate(OPTIONS, start=1):
        body = sections[f"§{number} {option}"]
        quoted = [line[2:] for line in body if line.startswith("> ")]
        assert " ".join(quoted) == meanings[option]


def test_the_tie_break_clause_covers_every_option() -> None:
    body = " ".join(_sections()["§6 tie-breaks"])

    for option in OPTIONS:
        assert f"`{option}`" in body


def test_the_two_skill_clause_sends_those_requests_elsewhere() -> None:
    body = " ".join(_sections()["§7 two-skill requests"])

    assert "not labelled" in body
    assert "TWO_SKILL.md" in body


# --------------------------------------------------------------------------
# The drafted corpus, over the file that ships
# --------------------------------------------------------------------------

VERSION = Path(__file__).resolve().parent / "corpus" / "v1"
SCENARIOS = VERSION / "scenarios.jsonl"
TWO_SKILL = VERSION / "TWO_SKILL.md"
TRIGGERING = (
    Path(__file__).resolve().parents[2] / "evals" / "suites" / "triggering.yaml"
)
SUITE = Path(__file__).resolve().parents[2] / "evals" / "suites" / "skill-router.yaml"


def _shipped() -> list:
    return list(load_corpus(SCENARIOS))


def test_the_drafted_corpus_has_the_version_1_shape() -> None:
    scenarios = _shipped()

    check_v1_shape(scenarios)
    assert len({scenario.state for scenario in scenarios}) == len(scenarios)


def test_every_seeded_scenario_keeps_its_source_label() -> None:
    check_seeded_labels(_shipped(), TRIGGERING)


def test_no_drafted_state_is_a_downstream_task_prompt() -> None:
    check_disjoint_from_tasks(_shipped(), SUITE)


def _two_skill_entries() -> list[str]:
    entries: list[str] = []
    current: list[str] | None = None
    for line in TWO_SKILL.read_text(encoding="utf-8").splitlines():
        if line.startswith("### "):
            if current is not None:
                entries.append(" ".join(current))
            current = []
        elif current is not None:
            current.append(line)
    if current is not None:
        entries.append(" ".join(current))
    return entries


def test_every_two_skill_entry_names_two_distinct_options() -> None:
    entries = _two_skill_entries()

    assert len(entries) >= 3
    for entry in entries:
        needed = entry.split("**Needs:**", 1)[1].split("**Why not one:**", 1)[0]
        named = re.findall(r"`([^`]+)`", needed)
        assert len(named) == 2, entry
        assert len(set(named)) == 2, entry
        for option in named:
            assert option in OPTIONS, entry


def test_no_two_skill_request_sits_in_the_corpus() -> None:
    states = {scenario.state for scenario in _shipped()}

    for entry in _two_skill_entries():
        request = entry.split("**Request:**", 1)[1].split("**Needs:**", 1)[0]
        numbers = re.findall(r'"([^"]+)"', request)
        assert numbers, entry
        assert " ".join(" ".join(numbers).split()) not in states


def test_v1_lock_matches_corpus_catalog_and_comparators(tmp_path: Path) -> None:
    """The freeze is only worth having if today's tree still reproduces it.

    Every argument is re-derived from the working tree, exactly as ``select``
    and ``replay`` do before a measurement, so a reworded ``SKILL.md``, a moved
    threshold, an edited instruction or a different comparator identity fails
    here instead of silently measuring a different question.
    """
    factories = replay.resolve_factories(None)
    identities = {
        name: identity_sha256(factories[name](VERSION)[1])
        for name in replay.COMPARATORS
    }
    rule_digest = replay.probe_rule_digest(CATALOG, tmp_path / "project")
    lock = check_lock(
        VERSION,
        CATALOG,
        identities,
        rule_digest=str(rule_digest),
        instrument_sha256=replay.instrument_sha256(replay.REPO_ROOT),
    )

    assert lock.count == 40
    assert lock.repeats == 5
    assert lock.seed == 20261013
    assert set(lock.comparators) == set(replay.COMPARATORS)
