"""The three comparators the evaluation measures.

Imports public ``functualize`` modules only. ``subprocess`` appears in this
module alone — the frontier comparator's one CLI call; nothing here spawns
anything at import time.

Constructing any comparator spawns nothing. Only ``FrontierRouter.choose`` and
the hermetic provider's ``choose`` perform work, and both perform at most one
round trip.
"""

from __future__ import annotations

import importlib.metadata
import json
import re
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from functualize.plugin import (
    ChoiceRequest,
    DecisionFailure,
    DecisionProvenance,
    DecisionProvider,
    DecisionResult,
    DecisionUnavailableError,
)

__all__ = [
    "RULES",
    "DeterministicBaseline",
    "FrontierCall",
    "FrontierRouter",
    "TimeoutExpired",
    "build_schema",
    "canonical_schema",
    "hermetic",
    "hermetic_identity",
    "identity_sha256",
]

#: A runner: ``(argv, cwd, timeout_seconds) -> (returncode, stdout, stderr)``.
Runner = Callable[[list[str], str, float], "tuple[int, str, str]"]

#: The deterministic baseline's rules, in priority order. First match wins.
RULES: tuple[tuple[str, str], ...] = (
    (
        "human_review",
        r"\b(refund|chargeback|lawsuit|legal|lawyer|fraud|hacked|password"
        r"|delete my account|threat|harm|medical|emergency|complaint)\b",
    ),
    (
        "deterministic",
        r"\b(opening hours|business hours|what time|order status"
        r"|status of (my )?order|tracking number|price of|how much (is|does)"
        r"|store address|phone number|reset link)\b",
    ),
    (
        "cheap_model",
        r"\b(summari[sz]e|rewrite|rephrase|translate|shorten"
        r"|fix (the )?(grammar|typos?)|draft a (short )?(reply|email|message)"
        r"|classify|tag)\b",
    ),
    (
        "frontier_agent",
        r"\b(investigate|analy[sz]e|debug|migrate|root cause|step[- ]by[- ]step"
        r"|multi-?step|design|research|plan)\b",
    ),
)

_HUMAN_REVIEW = "human_review"
_RULES_MODEL = "rules-v1"
_CODEX = "codex"
_DEFAULT_MODEL = "gpt-6-astra"
_DEFAULT_EFFORT = "medium"
_DEFAULT_TIMEOUT = 180.0

#: The ``try again at`` clock time a spent usage window reports, in the host's
#: local zone.
_RETRY_AT = re.compile(r"try again at (\d{1,2}):(\d{2}) ?([AP]M)")


def identity_sha256(identity: Mapping[str, object]) -> str:
    """The canonical digest a lock stores for a comparator identity."""
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


class DeterministicBaseline:
    """The rules baseline: one regex pass over the state, no model."""

    name: str = "deterministic"

    def choose(self, request: ChoiceRequest) -> DecisionResult[str]:
        started = time.monotonic()
        value = _first_rule(request.state)
        if value is None:
            chosen = _HUMAN_REVIEW
            share = 1.0 / len(request.options)
            distribution = dict.fromkeys(request.options, share)
        else:
            chosen = value
            distribution = {
                option: (1.0 if option == value else 0.0) for option in request.options
            }
        elapsed = time.monotonic() - started
        return DecisionResult(
            value=chosen,
            provider=self.name,
            model=_RULES_MODEL,
            provenance=DecisionProvenance(_RULES_MODEL, latency_seconds=elapsed),
            distribution=distribution,
            confidence=None,
        )

    def identity(self) -> dict[str, object]:
        rules = json.dumps(RULES).encode("utf-8")
        return {"comparator": self.name, "rules_sha256": sha256(rules).hexdigest()}


def _first_rule(state: str) -> str | None:
    for value, pattern in RULES:
        if re.search(pattern, state, re.IGNORECASE):
            return value
    return None


def hermetic() -> DecisionProvider:
    """The hermetic comparator: the Jev decision plugin, constructed lazily."""
    from functualize_decision_jev._provider import JevConfig, JevDecisionProvider

    return JevDecisionProvider(
        JevConfig(
            model="jev-1.13-free", endpoint="https://opencode.ai/zen/v1/systemone"
        )
    )


def hermetic_identity() -> dict[str, object]:
    """The hermetic comparator's identity, without constructing the provider."""
    return {
        "comparator": "hermetic",
        "provider": "jev",
        "model": "jev-1.13-free",
        "endpoint": "https://opencode.ai/zen/v1/systemone",
        "plugin": "functualize-decision-jev",
        "plugin_version": importlib.metadata.version("functualize-decision-jev"),
    }


@dataclass
class FrontierCall:
    """One frontier ``choose()``: what the CLI was, and what it cost."""

    cli_version: str | None
    model: str | None
    model_mismatch: bool
    usage: dict[str, int] | None


class FrontierRouter:
    """The frontier comparator: one ``codex exec`` round trip per ``choose``."""

    name: str = "frontier"

    def __init__(
        self,
        *,
        cwd: str,
        model: str = _DEFAULT_MODEL,
        effort: str = _DEFAULT_EFFORT,
        timeout_seconds: float = _DEFAULT_TIMEOUT,
        run: Runner | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._cwd = str(cwd)
        self._model = model
        self._effort = effort
        self._timeout = float(timeout_seconds)
        self._run: Runner = run if run is not None else _default_run
        self._now: Callable[[], datetime] = (
            now if now is not None else (lambda: datetime.now().astimezone())
        )
        self._cli_version: str | None = None
        self._schema_path = Path(self._cwd).parent / "frontier-schema.json"
        self._last_path = Path(self._cwd).parent / "frontier-last.json"
        self.calls: list[FrontierCall] = []

    def choose(self, request: ChoiceRequest) -> DecisionResult[str]:
        if self._cli_version is None:
            try:
                _, version, _ = self._run(
                    [_CODEX, "--version"], self._cwd, self._timeout
                )
            except TimeoutExpired as exc:
                # B-8: a timeout anywhere in the call, the version probe
                # included, is a recorded failed comparison — never an escape.
                raise self._timeout_failure() from exc
            self._cli_version = version.strip()
        prompt = _render_prompt(request)
        argv = self.argv(prompt)
        if not self._schema_path.exists():
            self._schema_path.write_bytes(canonical_schema(request.options))
        self._last_path.unlink(missing_ok=True)
        started = time.monotonic()
        try:
            code, stdout, stderr = self._run(argv, self._cwd, self._timeout)
        except TimeoutExpired as exc:
            raise self._timeout_failure() from exc
        elapsed = time.monotonic() - started
        usage, named_model = _parse_events(stdout)
        call = FrontierCall(
            cli_version=self._cli_version,
            model=named_model,
            model_mismatch=named_model is not None and named_model != self._model,
            usage=usage,
        )
        self.calls.append(call)

        message = _failure_message(stdout)
        if message is not None or code != 0:
            text = message if message is not None else stderr
            if message is not None and "usage limit" in message.lower():
                raise DecisionUnavailableError(
                    kind=DecisionFailure.RATE_LIMITED,
                    provider=self.name,
                    retry_after=_retry_after(self._now(), message),
                    detail=message,
                )
            raise DecisionUnavailableError(
                kind=DecisionFailure.REFUSED,
                provider=self.name,
                detail=text.strip()[:300],
            )

        payload = self._read_last()
        if payload is None:
            raise DecisionUnavailableError(
                kind=DecisionFailure.MALFORMED,
                provider=self.name,
                detail="the CLI wrote no parseable answer",
            )
        choice = payload.get("choice")
        probabilities = payload.get("probabilities")
        if not isinstance(choice, str) or choice not in request.options:
            raise DecisionUnavailableError(
                kind=DecisionFailure.MALFORMED,
                provider=self.name,
                detail=f"choice {choice!r} is not an offered option",
            )
        distribution = _distribution(probabilities, request.options)
        if distribution is None:
            raise DecisionUnavailableError(
                kind=DecisionFailure.MALFORMED,
                provider=self.name,
                detail="the answer does not carry a probability for every option",
            )
        return DecisionResult(
            value=choice,
            provider=self.name,
            model=named_model if named_model is not None else self._model,
            provenance=DecisionProvenance(
                self._model,
                latency_seconds=elapsed,
                input_tokens=_token(usage, "input_tokens"),
                output_tokens=_token(usage, "output_tokens"),
            ),
            distribution=distribution,
            confidence=None,
        )

    def _timeout_failure(self) -> DecisionUnavailableError:
        """The failure a timeout maps to, its call recorded (C-3, B-8)."""
        self.calls.append(
            FrontierCall(
                cli_version=self._cli_version,
                model=None,
                model_mismatch=False,
                usage=None,
            )
        )
        return DecisionUnavailableError(
            kind=DecisionFailure.UNREACHABLE,
            provider=self.name,
            detail=f"timeout after {self._timeout}s",
        )

    def _read_last(self) -> dict[str, Any] | None:
        try:
            payload = json.loads(self._last_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def argv(self, prompt: str) -> list[str]:
        return [
            _CODEX,
            "exec",
            "--json",
            "--output-schema",
            str(self._schema_path),
            "-o",
            str(self._last_path),
            "-m",
            self._model,
            "-c",
            f'model_reasoning_effort="{self._effort}"',
            "--ephemeral",
            "--skip-git-repo-check",
            "--ignore-user-config",
            "--ignore-rules",
            "-s",
            "read-only",
            "-C",
            self._cwd,
            prompt,
        ]

    def identity(self) -> dict[str, object]:
        from tests.hermetic_eval._router import load_router

        argv = self.argv("PROMPT")
        argv[_SCHEMA_INDEX] = "SCHEMA_PATH"
        argv[_LAST_INDEX] = "LAST_PATH"
        argv[_CWD_INDEX] = "CWD"
        # B-6 pins the gate's options to ROUTER's, so the schema those options
        # build is the schema every cell emitted — hashing its canonical bytes
        # makes a schema change move this digest and refuse the old lock (B-5).
        options = dict(load_router().ROUTER.options)
        return {
            "comparator": self.name,
            "cli": _CODEX,
            "model": self._model,
            "effort": self._effort,
            "argv": argv,
            "prompt_template_sha256": sha256(
                PROMPT_TEMPLATE.encode("utf-8")
            ).hexdigest(),
            "schema_sha256": sha256(canonical_schema(options)).hexdigest(),
        }


#: Where the run-directory paths sit in :meth:`FrontierRouter.argv`, so the
#: identity can replace them with placeholders without rebuilding the list.
_SCHEMA_INDEX = 4
_LAST_INDEX = 6
_CWD_INDEX = 18

#: The prompt the frontier CLI is asked with; ``option_lines`` is one
#: ``- {option}: {meaning}`` line per option in declared order.
PROMPT_TEMPLATE = (
    "You route requests. Answer only with the structured output: the option you"
    " choose and a probability for every option. Do not run commands.\n\n"
    "{instructions}\n\nOptions:\n{option_lines}\n\nText to route:\n<<<\n{state}\n"
    ">>>\n\nChoose one option and give a probability for every option; the"
    " probabilities sum to 1."
)


def build_schema(options: Mapping[str, str]) -> dict[str, Any]:
    """The structured-output schema the frontier CLI is asked for (C-3)."""
    names = list(options)
    return {
        "type": "object",
        "properties": {
            "choice": {"type": "string", "enum": names},
            "probabilities": {
                "type": "object",
                "properties": {name: {"type": "number"} for name in names},
                "required": names,
                "additionalProperties": False,
            },
        },
        "required": ["choice", "probabilities"],
        "additionalProperties": False,
    }


def canonical_schema(options: Mapping[str, str]) -> bytes:
    """The exact bytes a ``choose`` writes to the schema file.

    One serialization serves both the emitted file and the identity's
    ``schema_sha256``, so the digest the lock pins is the request contract the
    CLI actually received.
    """
    return json.dumps(build_schema(options)).encode("utf-8")


def _render_prompt(request: ChoiceRequest) -> str:
    option_lines = "\n".join(
        f"- {option}: {meaning}" for option, meaning in request.options.items()
    )
    return PROMPT_TEMPLATE.format(
        instructions=request.instructions,
        option_lines=option_lines,
        state=request.state,
    )


def _default_run(argv: list[str], cwd: str, timeout: float) -> tuple[int, str, str]:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return completed.returncode, completed.stdout, completed.stderr


#: The runner's timeout exception, re-exported so callers need not import
#: ``subprocess`` themselves.
TimeoutExpired = subprocess.TimeoutExpired


def _parse_events(stdout: str) -> tuple[dict[str, int] | None, str | None]:
    """The usage block and the answering model, when the stream names them."""
    usage: dict[str, int] | None = None
    model: str | None = None
    for event in _events(stdout):
        block = event.get("usage")
        if isinstance(block, dict):
            counts = {
                str(key): value
                for key, value in block.items()
                if isinstance(value, int) and not isinstance(value, bool)
            }
            usage = counts
        named = event.get("model")
        if isinstance(named, str) and named:
            model = named
    return usage, model


def _failure_message(stdout: str) -> str | None:
    """The message of the stream's ``error``/``turn.failed`` event, if any."""
    for event in _events(stdout):
        if event.get("type") == "turn.failed":
            error = event.get("error")
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                return error["message"]
        if event.get("type") == "error" and isinstance(event.get("message"), str):
            return event["message"]
    return None


def _events(stdout: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _retry_after(now: datetime, message: str) -> float | None:
    """Seconds from ``now`` to the message's ``try again at`` clock time."""
    match = _RETRY_AT.search(message)
    if match is None:
        return None
    hour = int(match.group(1)) % 12
    if match.group(3).upper() == "PM":
        hour += 12
    target = now.replace(hour=hour, minute=int(match.group(2)), second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def _distribution(
    probabilities: object, options: Mapping[str, str]
) -> dict[str, float] | None:
    if not isinstance(probabilities, Mapping):
        return None
    distribution: dict[str, float] = {}
    for option in options:
        value = probabilities.get(option)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not 0.0 <= float(value) <= 1.0:
            return None
        distribution[option] = float(value)
    return distribution


def _token(usage: dict[str, int] | None, key: str) -> int | None:
    if usage is None:
        return None
    return usage.get(key)
