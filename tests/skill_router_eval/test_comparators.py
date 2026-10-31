"""The comparators: a table written before the corpus, and the real router."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest

from functualize.plugin import ChoiceRequest
from tests.hermetic_eval.comparators import FrontierRouter, hermetic_identity
from tests.skill_router_eval.catalog import (
    NONE,
    OPTIONS,
    derive_catalog,
    option_meanings,
)
from tests.skill_router_eval.comparators import (
    KEYWORDS,
    MAX_TURNS_SUBTYPE,
    NATIVE_CONFIG,
    KeywordTable,
    NativeOverrideError,
    NativeRouter,
    identity_sha256,
)
from tests.skill_router_eval.selection import ESCALATED, SELECT_INSTRUCTIONS

ENTRIES = derive_catalog()
OPTIONS_MAP = option_meanings(ENTRIES)
FIXTURE = Path(__file__).with_name("fixtures") / "native_responses.json"
CASES = json.loads(FIXTURE.read_text())["cases"]

def request(state: str) -> ChoiceRequest:
    return ChoiceRequest(
        state=state, instructions=SELECT_INSTRUCTIONS, options=OPTIONS_MAP
    )

class Fake:
    """A ``call_api`` that replays one fixture response and records its argv."""

    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    def __call__(self, prompt: str, options: dict, context: dict) -> dict[str, Any]:
        self.calls.append((prompt, options, context))
        return copy.deepcopy(self.response)

# --------------------------------------------------------------------------
# The keyword table
# --------------------------------------------------------------------------


def test_the_table_is_priority_ordered_and_case_insensitive() -> None:
    assert len({option for option, _ in KEYWORDS}) == 4
    for option, pattern in KEYWORDS:
        assert option in OPTIONS
        assert pattern

    table = KeywordTable()
    lowered = table.choose(request("FUNC: COMMAND NOT FOUND"))
    raised = table.choose(request("func: command not found"))
    assert lowered.value == raised.value == "functualize-cli"
    assert dict(lowered.distribution) == dict(raised.distribution)


def test_the_first_matching_rule_wins() -> None:
    both = "after writing a SKILL.md, func: command not found"
    matching = [
        option
        for option, pattern in KEYWORDS
        if re.search(pattern, both, re.IGNORECASE)
    ]
    chosen = KeywordTable().choose(request(both))

    assert set(matching) == {"functualize-cli", "functualize-skill"}
    assert chosen.value == KEYWORDS[0][0]
    assert chosen.value == "functualize-cli"


def test_a_match_is_one_hot_at_full_confidence() -> None:
    result = KeywordTable().choose(request("func: command not found"))

    assert result.value == "functualize-cli"
    assert result.provider == "deterministic"
    assert result.model == "keywords-v1"
    assert result.distribution["functualize-cli"] == 1.0
    assert sum(result.distribution.values()) == pytest.approx(1.0)
    assert result.provenance.requested_model == "keywords-v1"


def test_no_match_is_none_at_a_share_of_every_option() -> None:
    result = KeywordTable().choose(request("what is the capital of France"))

    assert result.value == NONE
    assert list(result.distribution) == list(OPTIONS)
    assert set(result.distribution.values()) == {0.20}
    assert result.confidence is None


def test_the_table_is_deterministic_over_a_hundred_calls() -> None:
    table = KeywordTable()
    matched = [table.choose(request("func: command not found")) for _ in range(100)]
    unmatched = [table.choose(request("write me a haiku")) for _ in range(100)]

    def fingerprint(result: Any) -> tuple[Any, ...]:
        return (
            result.value,
            result.provider,
            result.model,
            tuple(sorted(result.distribution.items())),
        )

    assert len({fingerprint(result) for result in matched}) == 1
    assert len({fingerprint(result) for result in unmatched}) == 1
    assert len({result.provenance.latency_seconds for result in matched}) > 1


def test_the_identity_names_the_table_it_ran() -> None:
    identity = KeywordTable().identity()
    table = json.dumps([list(rule) for rule in KEYWORDS]).encode("utf-8")

    assert identity["comparator"] == "deterministic"
    assert set(identity) == {"comparator", "keywords_sha256"}
    assert identity["keywords_sha256"] == hashlib.sha256(table).hexdigest()
    assert identity_sha256(identity) == identity_sha256(KeywordTable().identity())

# --------------------------------------------------------------------------
# The native adapter
# --------------------------------------------------------------------------


def test_the_config_is_the_pinned_probe() -> None:
    assert dict(NATIVE_CONFIG) == {
        "model": "claude-sonnet-5",
        "max_turns": 3,
        "timeout_s": 180,
        "sandbox": "host",
    }
    with pytest.raises(TypeError):
        NATIVE_CONFIG["model"] = "something-else"  # type: ignore[index]
    assert MAX_TURNS_SUBTYPE == "error_max_turns"


def test_the_fixture_covers_every_branch_of_the_adapter() -> None:
    assert [case["name"] for case in CASES] == [
        "selected_app",
        "no_selection",
        "max_turns",
        "run_error",
        "api_error",
        "setup_error",
        "unknown_skill",
        "legacy_top_level",
    ]


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_the_adapter_reads_the_providers_real_shapes(case: dict[str, Any]) -> None:
    fake = Fake(case["response"])
    cell = NativeRouter(call_api=fake, environ={}).select("func: command not found")
    expect = case["expect"]

    assert cell.route == expect["route"]
    assert (cell.failed is None) == (expect["failed"] is None)
    if expect["failed"] is not None:
        assert dict(cell.failed) == expect["failed"]
    assert cell.selected == expect["selected"]
    assert cell.error == expect["error"]
    assert cell.model == expect["model"]
    assert cell.cost_usd == expect["cost_usd"]
    assert cell.latency_seconds >= 0.0


def test_the_fake_receives_the_state_and_the_pinned_config() -> None:
    fake = Fake(CASES[0]["response"])
    NativeRouter(call_api=fake, environ={}).select("func: command not found")

    assert len(fake.calls) == 1
    prompt, options, context = fake.calls[0]
    assert prompt == "func: command not found"
    assert options == {"config": dict(NATIVE_CONFIG)}
    assert options["config"]["max_turns"] == 3
    assert context == {}


def test_a_failed_run_keeps_the_cost_it_spent() -> None:
    failing = next(case for case in CASES if case["name"] == "run_error")
    cell = NativeRouter(call_api=Fake(failing["response"]), environ={}).select("x")

    assert cell.route == ESCALATED
    assert cell.cost_usd == 0.031


def test_a_setup_failure_has_no_cost() -> None:
    failing = next(case for case in CASES if case["name"] == "setup_error")
    cell = NativeRouter(call_api=Fake(failing["response"]), environ={}).select("x")

    assert cell.failed is not None
    assert cell.failed["kind"] == "setup_error"
    assert cell.cost_usd is None


def test_a_top_level_selection_never_becomes_a_route() -> None:
    legacy = next(case for case in CASES if case["name"] == "legacy_top_level")
    cell = NativeRouter(call_api=Fake(legacy["response"]), environ={}).select("x")

    assert cell.route == ESCALATED
    assert cell.route != "functualize-app"
    assert cell.selected is None


def test_constructing_a_comparator_spawns_nothing() -> None:
    calls: list[Any] = []

    def call_api(*args: Any) -> dict[str, Any]:
        calls.append(args)
        return {}

    def runner(*args: Any) -> tuple[int, str, str]:
        calls.append(args)
        return 0, "", ""

    NativeRouter(call_api=call_api, environ={})
    FrontierRouter(cwd=str(FIXTURE.parent), run=runner)
    assert calls == []


@pytest.mark.parametrize(
    ("name", "value"),
    [("FZ_EVAL_MODEL", "claude-other"), ("FZ_EVAL_SANDBOX", "docker")],
)
def test_an_override_is_refused_before_the_fake_is_called(
    name: str, value: str
) -> None:
    fake = Fake(CASES[0]["response"])

    with pytest.raises(NativeOverrideError) as caught:
        NativeRouter(call_api=fake, environ={name: value})

    assert name in str(caught.value)
    assert value in str(caught.value)
    assert fake.calls == []


@pytest.mark.parametrize(
    ("name", "value"),
    [("FZ_EVAL_MODEL", "claude-sonnet-5"), ("FZ_EVAL_SANDBOX", "host")],
)
def test_the_pinned_value_is_not_an_override(name: str, value: str) -> None:
    router = NativeRouter(call_api=Fake({}), environ={name: value})

    assert router.name == "native"


def test_the_identity_is_the_provider_and_its_bytes() -> None:
    identity = NativeRouter(call_api=lambda *_a: {}, environ={}).identity()
    provider = Path(__file__).resolve().parents[2] / "evals/providers/claude_router.py"

    assert identity["comparator"] == "native"
    assert identity["provider"] == "evals/providers/claude_router.py"
    assert identity["config"] == dict(NATIVE_CONFIG)
    assert identity["tools"] == ["Skill", "Read", "Glob", "Grep"]
    assert identity["env_overrides"] == "refused"
    assert identity["provider_sha256"] == hashlib.sha256(
        provider.read_bytes()
    ).hexdigest()

# --------------------------------------------------------------------------
# The Phase 3 comparators, reused rather than re-implemented
# --------------------------------------------------------------------------


def test_the_hermetic_and_frontier_comparators_are_phase_threes() -> None:
    import tests.hermetic_eval.comparators as phase_three

    assert FrontierRouter is phase_three.FrontierRouter
    assert identity_sha256 is phase_three.identity_sha256
    assert hermetic_identity()["comparator"] == "hermetic"
