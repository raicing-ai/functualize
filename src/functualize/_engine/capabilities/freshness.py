"""Freshness capability — the verdict this job's own ``Fingerprint`` produced.

A job declares the inputs it depends on and the outputs it promises; the
pre-flight decides whether it is up to date — and the body was never told. When
the verdict said "fresh" the engine returned before the body ran, so a job that
wants to act on its own freshness (*"I am current — hand back the artifact I
already built"*) had no way to ask, and every such job restated its own
staleness test to work around the framework.

This is plumbing, not computation: nothing here decides anything, and nothing
here recomputes anything. The state, the key, the recorded value, the declared
sources and generates, and the resolved source map all come off the
:class:`~functualize._engine.preflight.PreflightDecision`, which already carried
them for the pre-flight's own use.

**The ordering that makes this delicate.** DI resolution runs *before* the
pre-flight, so at injection time the verdict does not exist and the instance is
injected empty. It is completed once the decision is in hand and before the body
is called — the same two-phase shape ``Sources`` has, and for the same reason.
That is exactly the shape ``contributor/guides/wiring-discipline.md`` warns
about — a capability that resolves and does nothing — which is why the
completion carries a sabotage check on both the cold and the warm path rather
than a unit test alone.

Reading the verdict does not oblige a job to skip, and the framework stores
nothing on the job's behalf: storing an artifact is the job's business, and this
capability is what lets a job get on with it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from functualize._engine.capabilities.spec import CapabilitySpec
from functualize._engine.guards import GuardState

__all__ = ["CAPABILITY", "Freshness", "FreshnessVerdict"]


@dataclass(frozen=True)
class FreshnessVerdict:
    """What the pre-flight decided about this run, and the inputs it decided on.

    It is the decision itself, not a summary of it: ``source_map`` is the very
    mapping ``Sources`` exposes, and the declared patterns are the ones the
    job's own ``Fingerprint`` named. A job asking "why am I fresh?" therefore
    gets one answer from one capability rather than two answers free to drift.

    Attributes:
        state: The pipeline outcome — ``SKIP_FRESH`` for a job whose declared
            inputs are current, ``RUN`` when they are not.
        key: The fingerprint key the decision was computed under, so a job can
            see which recorded run it is being compared against.
        recorded_value: What the previous run recorded, when the pre-flight read
            a record and the verdict was a skip.
        declared_sources: The input patterns as the job declared them.
        declared_generates: The output patterns as the job declared them.
        source_map: ``{path: {mtime, size, sha256}}`` for every match of the
            declared inputs — the decision's own mapping, bound by reference,
            so asking for it costs no second copy.
    """

    state: GuardState
    key: str
    recorded_value: Any | None
    declared_sources: tuple[str, ...]
    declared_generates: tuple[str, ...]
    source_map: Mapping[str, Mapping[str, Any]]

    @property
    def is_fresh(self) -> bool:
        """True when the engine decided this job's declared inputs are current.

        Only ``SKIP_FRESH`` answers True. A satisfied ``status`` guard is a
        different claim about a different thing ("already done"), and it is
        deliberately not folded in here — the two states are distinct for the
        same reason they are distinct in the guard pipeline.
        """
        return self.state is GuardState.SKIP_FRESH


class Freshness:
    """The verdict this job's own ``Fingerprint`` produced, for the job to act on.

    Declared as a job parameter, like every other capability::

        @job(cache=Fingerprint(sources=["src/**/*.py"]))
        def build(fresh: Freshness) -> str:
            verdict = fresh.verdict()
            if verdict is not None and verdict.is_fresh:
                return "artifact already current"
            return rebuild()

    :meth:`verdict` returns ``None`` when this job declares no ``Fingerprint`` —
    there was no decision, and a fabricated one would be a lie. A job that
    declares one gets the verdict whether or not the framework used it to skip.
    """

    __slots__ = ("_verdict",)

    def __init__(self, verdict: FreshnessVerdict | None = None) -> None:
        self._verdict = verdict

    def verdict(self) -> FreshnessVerdict | None:
        """The decision this run's pre-flight made, or None if none was made."""
        return self._verdict

    def _bind(self, decision: Any) -> None:
        """Fill in the verdict once the pre-flight has produced it.

        Private, and called from exactly one place: this capability's own
        declared completion, which the executor runs for every capability that
        declares one. The instance is injected before the pre-flight runs, so
        without this call every job sees no verdict and no error anywhere — the
        silent failure this capability's tests are built around.
        """
        if decision is None:
            self._verdict = None
            return
        self._verdict = FreshnessVerdict(
            state=decision.verdict.state,
            key=decision.key,
            recorded_value=decision.recorded_value,
            declared_sources=tuple(decision.declared_sources),
            declared_generates=tuple(decision.declared_generates),
            # The decision's own mapping, not a copy. A job asking why it is
            # fresh should not cost a second copy of every input it declared.
            source_map=decision.source_map,
        )


# ── Registry entry (ADR-014) ───────────────────────────────────────────────


def _bind_from_preflight(instance: Freshness, decision: Any) -> None:
    """Hand the pre-flight's decision to the injected instance.

    A job that declares no ``Fingerprint`` — or a run where the pre-flight had
    nothing to decide — gets no verdict at all, which is a different answer from
    a verdict of ``RUN``: one says "nothing was asked", the other "asked, and
    the answer is that this should run".
    """
    instance._bind(decision)


CAPABILITY = CapabilitySpec(
    name="Freshness",
    type=Freshness,
    # Deliberately empty, exactly as `Sources` is. DI resolves before the
    # pre-flight — it must, because the pre-flight's args hash reads
    # `context.injected` — so the decision does not exist yet and there is
    # nothing to hand over at this point.
    factory=lambda ctx: Freshness(),
    # ...which is why the second phase is declared rather than remembered. When
    # the completion was one call at one line in the executor, losing it gave
    # every job no verdict and no error anywhere; a second capability of the
    # same shape would have had to remember it again.
    preflight_bind=_bind_from_preflight,
)
