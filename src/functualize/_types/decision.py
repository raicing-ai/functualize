"""The decision vocabulary — a proposed choice, and the port that proposes it.

Values and one Protocol, plus the declaration's JSON projection and its digest
— two pure functions — and nothing else: a provider answers a ``ChoiceRequest``
with a ``DecisionResult`` carrying a **candidate**, never a verdict. Whether a
candidate is acted on is the gate's declared rule, so the result has no
``accepted`` field and no boolean of any kind — a provider cannot say "yes" on
the workflow's behalf by shape alone.

``distribution`` and ``confidence`` are recorded separately on purpose. The
distribution is the provider's probability per option; ``confidence`` is the
provider's own scalar and is **not** ``max(distribution)``. Neither is checked
to sum to one: the wire reports two decimals, so a faithful record of it can
sum to 0.99 or 1.01.

``ChoiceDecision`` is the other side: what a workflow *declares* on a gate —
which field a decision fills, from which step's result, and the thresholds a
proposal must clear before the gate accepts it. The thresholds are the
workflow's, never the provider's.

Nothing here performs I/O and nothing here depends on a particular provider;
the imports are the standard library and ``FromStep``, another vocabulary
value.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Generic, Protocol, TypeVar, runtime_checkable

if TYPE_CHECKING:
    from functualize._types.from_job import FromStep

__all__ = [
    "ChoiceDecision",
    "ChoiceRequest",
    "DecisionProvenance",
    "DecisionProvider",
    "DecisionResult",
    "decision_digest",
    "decision_shape",
]

T = TypeVar("T")

#: A ``ChoiceRequest`` offers at least this many options — one option is not a
#: choice.
_MIN_OPTIONS = 2
#: ...and at most this many.
_MAX_OPTIONS = 32


def _check_unit_interval(name: str, value: float) -> None:
    # Written as a positive range test so NaN, which compares false with
    # everything, is refused rather than slipping through a pair of negations.
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must lie in [0, 1], got {value!r}")


@dataclass(frozen=True)
class DecisionProvenance:
    """Where a result came from: what was asked for, and what it cost."""

    requested_model: str  # what the caller asked for
    latency_seconds: float  # monotonic wall clock of the one round trip
    input_tokens: int | None = None  # the request's single usage block, when reported
    output_tokens: int | None = None


@dataclass(frozen=True)
class DecisionResult(Generic[T]):
    """One proposed candidate, as a provider reported it.

    ``distribution`` is copied into a read-only mapping on construction, so a
    caller mutating the dict it passed in cannot change a recorded result, and
    equality compares it as a mapping — key order never affects ``==``.
    """

    value: T  # the proposed candidate
    provider: str  # a stable provider name; never parsed
    model: str  # the model the provider says answered
    provenance: DecisionProvenance
    distribution: Mapping[T, float] | None = (
        None  # keyed by option; order is meaningless
    )
    confidence: float | None = None  # provider's own scalar; not max(distribution)

    def __post_init__(self) -> None:
        if self.distribution is not None:
            frozen: Mapping[T, float] = MappingProxyType(dict(self.distribution))
            object.__setattr__(self, "distribution", frozen)
            for option, probability in frozen.items():
                _check_unit_interval(f"distribution[{option!r}]", probability)
        if self.confidence is not None:
            _check_unit_interval("confidence", self.confidence)


@dataclass(frozen=True)
class ChoiceRequest:
    """A question with a closed set of answers.

    ``options`` maps each option to its meaning, and is stored as given.
    """

    state: str  # the text to decide about, as given
    instructions: str
    options: Mapping[str, str]  # option -> meaning; 2..32 entries, non-empty keys
    model: str | None = None  # None = the provider's configured default

    def __post_init__(self) -> None:
        count = len(self.options)
        if not _MIN_OPTIONS <= count <= _MAX_OPTIONS:
            raise ValueError(
                f"a ChoiceRequest needs {_MIN_OPTIONS} to {_MAX_OPTIONS} "
                f"options, got {count}"
            )
        if "" in self.options:
            raise ValueError("a ChoiceRequest option may not be the empty string")


@runtime_checkable
class DecisionProvider(Protocol):
    """The whole port a decision provider implements.

    Obligations on every implementation, which the Protocol cannot express:

    - ``choose`` either returns a ``DecisionResult`` whose ``value`` is a key
      of ``request.options``, or raises ``DecisionUnavailableError``
      (``functualize._types.errors``). It never returns an answer outside the
      options it was offered.
    - It performs **at most one** round trip per call. It never sleeps and
      never retries: a rate limit or an outage is reported, and what to do
      about it is the caller's decision, not the provider's.
    """

    @property
    def name(self) -> str: ...

    def choose(self, request: ChoiceRequest) -> DecisionResult[str]: ...


@dataclass(frozen=True)
class ChoiceDecision:
    """A gate's declared decision: who fills which field, and when it counts.

    Declared on ``Gate(decide=...)``. The gate hands the recorded result of
    ``state``'s step to a decision provider as the text to decide about, and
    accepts the proposed option only when its probability reaches
    ``accept_at`` and leads the runner-up by at least ``min_margin``; anything
    less blocks the gate for a person. Whether ``options`` match the awaited
    field is checked by the gate, which knows the field; this class checks its
    own ranges only.

    ``fallback`` names the option taken when no proposal clears the
    thresholds: the gate still completes, on the declared answer rather than a
    proposed one. A default on the decided field itself is the same outcome
    reached by accident, which is why the gate refuses it.
    """

    field: str  # the awaits field the decision fills
    instructions: str
    options: Mapping[str, str]  # option -> meaning
    state: FromStep  # the step whose recorded result is the text
    accept_at: float  # 0 < accept_at <= 1
    min_margin: float = 0.0  # 0 <= min_margin < 1
    model: str | None = None  # passed through to ChoiceRequest.model
    fallback: str | None = None  # one of options; taken when no proposal is accepted

    def __post_init__(self) -> None:
        # The declaration that was checked is the one evaluated and digested:
        # copy the options into a read-only mapping, so a caller mutating the
        # dict it passed in cannot change the keys or the meanings afterwards.
        object.__setattr__(
            self,
            "options",
            MappingProxyType({str(k): str(v) for k, v in self.options.items()}),
        )
        if self.fallback is not None and self.fallback not in self.options:
            raise ValueError(
                f"ChoiceDecision fallback {self.fallback!r} is not one of the "
                f"options {sorted(self.options)}"
            )
        # Positive range tests, so NaN is refused too.
        if not 0.0 < self.accept_at <= 1.0:
            raise ValueError(
                f"ChoiceDecision accept_at must lie in (0, 1], got {self.accept_at!r}"
            )
        if not 0.0 <= self.min_margin < 1.0:
            raise ValueError(
                f"ChoiceDecision min_margin must lie in [0, 1), got {self.min_margin!r}"
            )


def decision_shape(decide: ChoiceDecision) -> dict[str, Any]:
    """A gate's declared decision as JSON-safe values, for the cached shape.

    ``state`` is the step's *name* and ``options`` a plain dict, so the shape
    round-trips through JSON and a warm boot reads it without importing the
    module that declared the gate. The declared fallback joins the shape only
    when there is one, so every digest recorded before it existed is
    unchanged.
    """
    shape: dict[str, Any] = {
        "field": decide.field,
        "instructions": decide.instructions,
        "options": {str(k): str(v) for k, v in decide.options.items()},
        "state": decide.state.name,
        "accept_at": float(decide.accept_at),
        "min_margin": float(decide.min_margin),
        "model": decide.model,
    }
    if decide.fallback is not None:
        shape["fallback"] = decide.fallback
    return shape


def decision_digest(decide: ChoiceDecision) -> str:
    """The declared rule as one stable digest.

    Over the JSON projection with sorted keys, so two declarations a reader
    would call identical always digest identical — the same contract the graph
    digest gives the whole shape.
    """
    canonical = json.dumps(
        decision_shape(decide), sort_keys=True, separators=(",", ":")
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
