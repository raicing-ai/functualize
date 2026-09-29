"""The decision vocabulary — a proposed choice, and the port that proposes it.

Values and one Protocol, nothing else: a provider answers a ``ChoiceRequest``
with a ``DecisionResult`` carrying a **candidate**, never a verdict. Whether a
candidate is acted on is the gate's declared rule, so the result has no
``accepted`` field and no boolean of any kind — a provider cannot say "yes" on
the workflow's behalf by shape alone.

``distribution`` and ``confidence`` are recorded separately on purpose. The
distribution is the provider's probability per option; ``confidence`` is the
provider's own scalar and is **not** ``max(distribution)``. Neither is checked
to sum to one: the wire reports two decimals, so a faithful record of it can
sum to 0.99 or 1.01.

Nothing here performs I/O and nothing here depends on a particular provider;
the imports are the standard library only.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Generic, Protocol, TypeVar, runtime_checkable

__all__ = [
    "ChoiceRequest",
    "DecisionProvenance",
    "DecisionProvider",
    "DecisionResult",
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


# TRANSITIONAL(decision-provider-seam/T9): no production caller until the
# plugin registers the decision strategy
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
