"""Offline tests for the three comparators.

Every frontier case drives a fake runner: no process is spawned, nothing is
sent over the network, nothing sleeps.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from functualize.plugin import (
    ChoiceRequest,
    DecisionFailure,
    DecisionProvider,
    DecisionUnavailableError,
)
from tests.hermetic_eval import comparators

FIXTURES = Path(__file__).parent / "fixtures"

MEANINGS = {
    "deterministic": "a fixed rule or lookup answers it; no model needed",
    "cheap_model": "a short, low-risk text task a small model can do",
    "frontier_agent": "multi-step reasoning or tool use is required",
    "human_review": "risky, ambiguous, or needs a person's judgement",
}

INSTRUCTIONS = "Choose how this request should be handled."
STATE = "Refund my order 8831 — the box arrived empty."

EXPECTED_PROMPT = (
    "You route requests. Answer only with the structured output: the option you"
    " choose and a probability for every option. Do not run commands.\n\n"
    f"{INSTRUCTIONS}\n\nOptions:\n"
    "- deterministic: a fixed rule or lookup answers it; no model needed\n"
    "- cheap_model: a short, low-risk text task a small model can do\n"
    "- frontier_agent: multi-step reasoning or tool use is required\n"
    "- human_review: risky, ambiguous, or needs a person's judgement\n\n"
    f"Text to route:\n<<<\n{STATE}\n>>>\n\n"
    "Choose one option and give a probability for every option; the"
    " probabilities sum to 1."
)

SUCCESS_EVENTS = (FIXTURES / "codex_success.jsonl").read_text(encoding="utf-8")
SUCCESS_LAST = (FIXTURES / "codex_success_last.json").read_text(encoding="utf-8")
USAGE_LIMIT_EVENTS = (FIXTURES / "codex_usage_limit.jsonl").read_text(encoding="utf-8")


def _request(state: str = STATE) -> ChoiceRequest:
    return ChoiceRequest(state=state, instructions=INSTRUCTIONS, options=MEANINGS)


class FakeRunner:
    """A runner that records its calls and replays canned output."""

    def __init__(
        self,
        *,
        stdout: str = "",
        returncode: int = 0,
        stderr: str = "",
        last: str | None = None,
        timeout: bool = False,
        version: str = "codex-cli 0.156.1",
    ) -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr
        self.last = last
        self.timeout = timeout
        self.version = version
        self.calls: list[tuple[list[str], str, float]] = []

    def __call__(
        self, argv: list[str], cwd: str, timeout: float
    ) -> tuple[int, str, str]:
        self.calls.append((argv, cwd, timeout))
        if argv[1:] == ["--version"]:
            return 0, f"{self.version}\n", ""
        if self.timeout:
            raise comparators.TimeoutExpired(argv, timeout)
        if self.last is not None:
            (Path(cwd).parent / "frontier-last.json").write_text(
                self.last, encoding="utf-8"
            )
        return self.returncode, self.stdout, self.stderr


def _router(
    tmp_path: Path, runner: FakeRunner, **kwargs: Any
) -> comparators.FrontierRouter:
    return comparators.FrontierRouter(
        cwd=str(tmp_path / "frontier-cwd"), run=runner, **kwargs
    )


def _expected_argv(tmp_path: Path) -> list[str]:
    return [
        "codex",
        "exec",
        "--json",
        "--output-schema",
        str(tmp_path / "frontier-schema.json"),
        "-o",
        str(tmp_path / "frontier-last.json"),
        "-m",
        "gpt-6-astra",
        "-c",
        'model_reasoning_effort="medium"',
        "--ephemeral",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "--ignore-rules",
        "-s",
        "read-only",
        "-C",
        str(tmp_path / "frontier-cwd"),
        EXPECTED_PROMPT,
    ]


def test_identity_sha256_is_canonical_and_sensitive() -> None:
    digest = comparators.identity_sha256({"b": 1, "a": 2})
    assert digest == comparators.identity_sha256({"a": 2, "b": 1})
    assert len(digest) == 64
    assert digest != comparators.identity_sha256({"a": 2, "b": 3})


def test_the_probe_recorded_the_measured_usage_shape() -> None:
    usage = json.loads(SUCCESS_EVENTS.strip().splitlines()[-1])["usage"]
    for key in (
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
    ):
        assert isinstance(usage[key], int)


def test_frontier_argv_is_exact_and_the_version_is_read_once(tmp_path: Path) -> None:
    runner = FakeRunner(stdout=SUCCESS_EVENTS, last=SUCCESS_LAST)
    router = _router(tmp_path, runner)
    router.choose(_request())
    router.choose(_request())

    expected = _expected_argv(tmp_path)
    assert [call[0] for call in runner.calls] == [
        ["codex", "--version"],
        expected,
        expected,
    ]
    assert runner.calls[1][1:] == (str(tmp_path / "frontier-cwd"), 180.0)
    schema = json.loads((tmp_path / "frontier-schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["choice"]["enum"] == list(MEANINGS)
    assert schema["properties"]["probabilities"]["required"] == list(MEANINGS)
    assert router.calls[-1].cli_version == "codex-cli 0.156.1"


def test_frontier_identity_holds_placeholders(tmp_path: Path) -> None:
    router = _router(tmp_path, FakeRunner())
    identity = router.identity()
    assert identity["comparator"] == "frontier"
    assert identity["model"] == "gpt-6-astra"
    assert identity["schema_builder"] == "v1"
    argv = identity["argv"]
    assert argv[4] == "SCHEMA_PATH"
    assert argv[6] == "LAST_PATH"
    assert argv[18] == "CWD"
    assert argv[19] == "PROMPT"
    assert (
        identity["prompt_template_sha256"]
        == hashlib.sha256(comparators.PROMPT_TEMPLATE.encode("utf-8")).hexdigest()
    )


def test_frontier_success_fixture_maps_to_a_result(tmp_path: Path) -> None:
    runner = FakeRunner(stdout=SUCCESS_EVENTS, last=SUCCESS_LAST)
    router = _router(tmp_path, runner)
    result = router.choose(_request())

    payload = json.loads(SUCCESS_LAST)
    assert result.value == payload["choice"] == "human_review"
    assert result.provider == "frontier"
    assert result.model == "gpt-6-astra"
    assert dict(result.distribution or {}) == payload["probabilities"]
    assert result.confidence is None
    usage = json.loads(SUCCESS_EVENTS.strip().splitlines()[-1])["usage"]
    assert result.provenance.input_tokens == usage["input_tokens"]
    assert result.provenance.output_tokens == usage["output_tokens"]
    assert result.provenance.requested_model == "gpt-6-astra"
    assert result.provenance.latency_seconds >= 0.0

    call = router.calls[-1]
    assert call.model is None
    assert call.model_mismatch is False
    assert (
        call.usage is not None and call.usage["output_tokens"] == usage["output_tokens"]
    )


def test_a_named_model_is_recorded_and_a_mismatch_flagged(tmp_path: Path) -> None:
    stdout = '{"type":"thread.started","model":"gpt-6-mini"}\n' + SUCCESS_EVENTS
    router = _router(tmp_path, FakeRunner(stdout=stdout, last=SUCCESS_LAST))
    result = router.choose(_request())
    assert result.model == "gpt-6-mini"
    assert router.calls[-1].model_mismatch is True


def test_usage_limit_maps_to_rate_limited(tmp_path: Path) -> None:
    now = datetime(2026, 10, 4, 22, 4, 48, tzinfo=timezone(timedelta(hours=2)))
    router = _router(
        tmp_path,
        FakeRunner(stdout=USAGE_LIMIT_EVENTS, returncode=1, stderr="boom"),
        now=lambda: now,
    )
    with pytest.raises(DecisionUnavailableError) as caught:
        router.choose(_request())
    error = caught.value
    assert error.kind is DecisionFailure.RATE_LIMITED
    assert error.retry_after == 4632.0
    assert error.retry_after is not None
    assert error.status is None


def test_another_failure_message_maps_to_refused(tmp_path: Path) -> None:
    stdout = '{"type":"turn.failed","error":{"message":"stream closed early"}}\n'
    router = _router(tmp_path, FakeRunner(stdout=stdout, returncode=1))
    with pytest.raises(DecisionUnavailableError) as caught:
        router.choose(_request())
    assert caught.value.kind is DecisionFailure.REFUSED
    assert "stream closed early" in caught.value.detail


def test_a_non_zero_exit_without_a_message_maps_to_refused(tmp_path: Path) -> None:
    router = _router(tmp_path, FakeRunner(returncode=1, stderr="  denied  "))
    with pytest.raises(DecisionUnavailableError) as caught:
        router.choose(_request())
    assert caught.value.kind is DecisionFailure.REFUSED
    assert caught.value.detail == "denied"


@pytest.mark.parametrize(
    "last",
    [
        None,
        "not json",
        json.dumps({"choice": "other", "probabilities": dict.fromkeys(MEANINGS, 0.25)}),
        json.dumps(
            {
                "choice": "human_review",
                "probabilities": {**dict.fromkeys(MEANINGS, 0.25), "human_review": 1.2},
            }
        ),
    ],
)
def test_malformed_answers_map_to_malformed(tmp_path: Path, last: str | None) -> None:
    runner = FakeRunner(stdout=SUCCESS_EVENTS, last=last)
    router = _router(tmp_path, runner)
    with pytest.raises(DecisionUnavailableError) as caught:
        router.choose(_request())
    assert caught.value.kind is DecisionFailure.MALFORMED
    assert router.calls != []


def test_a_timeout_maps_to_unreachable(tmp_path: Path) -> None:
    router = _router(tmp_path, FakeRunner(timeout=True))
    with pytest.raises(DecisionUnavailableError) as caught:
        router.choose(_request())
    assert caught.value.kind is DecisionFailure.UNREACHABLE
    assert caught.value.detail == "timeout after 180.0s"


def test_deterministic_rules_are_one_hot_and_uniform_on_a_miss() -> None:
    baseline = comparators.DeterministicBaseline()
    refund = baseline.choose(_request("Refund my order 8831"))
    assert refund.value == "human_review"
    assert refund.distribution == {
        "deterministic": 0.0,
        "cheap_model": 0.0,
        "frontier_agent": 0.0,
        "human_review": 1.0,
    }
    hours = baseline.choose(_request("What are your opening hours?"))
    assert hours.value == "deterministic"
    assert hours.distribution == {
        "deterministic": 1.0,
        "cheap_model": 0.0,
        "frontier_agent": 0.0,
        "human_review": 0.0,
    }
    miss = baseline.choose(_request("hello there"))
    assert miss.value == "human_review"
    assert dict(miss.distribution or {}) == dict.fromkeys(MEANINGS, 0.25)
    assert miss.model == "rules-v1"
    assert miss.provider == "deterministic"
    assert miss.confidence is None


def test_deterministic_decisions_are_identical_across_calls() -> None:
    baseline = comparators.DeterministicBaseline()
    request = _request("Please summarize this thread")
    decisions = {
        (
            result.value,
            result.provider,
            result.model,
            tuple(sorted((result.distribution or {}).items())),
            result.confidence,
        )
        for result in (baseline.choose(request) for _ in range(100))
    }
    assert len(decisions) == 1


def test_deterministic_identity_is_stable_across_instances() -> None:
    first = comparators.DeterministicBaseline().identity()
    second = comparators.DeterministicBaseline().identity()
    assert first == second
    assert first["comparator"] == "deterministic"
    assert len(str(first["rules_sha256"])) == 64


def test_hermetic_identity_names_the_plugin_and_the_model() -> None:
    identity = comparators.hermetic_identity()
    assert identity == {
        "comparator": "hermetic",
        "provider": "jev",
        "model": "jev-1.13-free",
        "endpoint": "https://opencode.ai/zen/v1/systemone",
        "plugin": "functualize-decision-jev",
        "plugin_version": identity["plugin_version"],
    }
    assert isinstance(identity["plugin_version"], str) and identity["plugin_version"]


def test_every_comparator_satisfies_the_provider_port() -> None:
    assert isinstance(comparators.DeterministicBaseline(), DecisionProvider)
    assert isinstance(_router(Path("/tmp/nothing"), FakeRunner()), DecisionProvider)
    assert isinstance(comparators.hermetic(), DecisionProvider)
