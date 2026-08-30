"""One declaration per capability — the registry entry (D-4, ADR-014).

Adding a capability used to mean editing the same fact in four places, two of
which failed **silently**:

===  ====================================================  ======================================
  #  Site                                                  Missed ⇒
===  ====================================================  ======================================
  1  ``_engine/capabilities/<new>.py``                     —
  2  ``executor._per_invocation_types()``                  the parameter resolves to nothing, **no error**
  3  ``executor._create_per_invocation_cap()``, a 129-line  falls through to ``type_()`` — a bare
     ``if/elif`` ladder over concrete types                 construction that may or may not work
  4  ``_primitives/capability_names``                      the parameter becomes a **CLI flag**; on
                                                            warm boot the job dies with
                                                            ``Missing argument 'SH'``
  5  a ``_bind_*`` method and its call site inside          the capability is injected and **inert**
     ``_execute_lifecycle`` (only for capabilities
     needing data the pre-flight produces)
===  ====================================================  ======================================

Sites 2, 4 and 5 are not hypothetical: they are defect D8 of the
``pipeline-readiness`` branch (``Shell`` and ``Stdout`` missing from one list)
and the standing risk in the ``Sources`` two-phase bind. That branch fixed three
instances of the pattern without changing the pattern.

A :class:`CapabilitySpec` is written beside the capability it describes, and
sites 2, 3 and 5 are derived from it. ``needs_preflight_bind`` in particular
turns the ``Sources`` bind from *"remember to call ``_bind_sources``"* into a
declared property of the capability.

Site 4 is the one that cannot derive, and ``registry.py`` explains why and what
is done about it instead.

Modelled on NestJS custom providers (``{provide, useFactory, scope}``) plus
``Scope.REQUEST``, which is the same problem — "this thing is constructed per
invocation, here is how" — solved declaratively.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["CapabilityContext", "CapabilitySpec"]


@dataclass(frozen=True)
class CapabilityContext:
    """Everything a capability factory is allowed to read.

    One argument bundle for **every** factory, which is what lets the ladder
    collapse into a lookup: a dispatch table cannot have per-branch signatures.

    ``engine`` is the ``JobExecutionEngine``. The factories reach their inputs
    through it exactly as the ladder reached them through ``self`` — no
    factory gained access to anything it did not already have.
    """

    engine: Any
    context: Any
    #: The live per-invocation map, still being filled. ``TTY`` takes it and
    #: resolves ``RunContext`` from it lazily, so declaration order does not
    #: matter — which is why it is passed rather than read back from
    #: ``context.capabilities``.
    caps: dict[type, Any]


@dataclass(frozen=True)
class CapabilitySpec:
    """How one injected capability is named, built, and bound.

    Attributes:
        name: The annotation's type name, as a **string**. This is what the
            layers that may not import the capability match on — see
            ``_primitives/capability_names``.
        type: The annotation's type, or None when it is not a static type.
            ``JobConfigView`` is the only such case: it is resolved by identity
            against ``engine._config_view_type``, a value known at boot.
        factory: Builds the instance, given a :class:`CapabilityContext`. None
            when the engine constructs it somewhere else in the lifecycle
            (``RunContext``, at step 5) or by identity (``JobConfigView``).
        per_invocation: True when a fresh instance is built for every
            invocation through the factory path.
        preflight_bind: How to complete an instance once the pre-flight
            decision exists, or None when it is complete on creation.

            DI resolves before the pre-flight runs — it must, because the
            pre-flight's args hash reads ``context.injected`` — so a capability
            carrying pre-flight data cannot be finished when it is created.
            Declaring the second phase here is what stops it being a call
            somebody has to remember: the executor completes every spec that
            declares one, and a capability that declares none costs nothing.

            Before this, the second phase was a single hard-coded line inside
            ``_execute_lifecycle``. Losing it gave every job an empty source
            map with no error anywhere — the "wired but inert" failure
            ``contributor/guides/wiring-discipline.md`` exists for — and a
            second capability of the same shape would have had to remember it
            again.

            Called as ``preflight_bind(instance, decision)``. ``decision`` is
            the ``PreflightDecision``, or None when there was nothing to
            pre-flight.
    """

    name: str
    type: type | None = None
    factory: Callable[[CapabilityContext], Any] | None = None
    per_invocation: bool = True
    preflight_bind: Callable[[Any, Any], None] | None = None

    @property
    def needs_preflight_bind(self) -> bool:
        """True when this capability is injected empty and completed later."""
        return self.preflight_bind is not None
