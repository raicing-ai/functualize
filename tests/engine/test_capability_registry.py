"""Adding a capability is one declaration (D-4, ADR-014).

It used to be four, two of which failed **silently**:

* omit ``_per_invocation_types()`` and the parameter resolves to nothing, with
  no error;
* omit ``_primitives/capability_names`` and the parameter becomes a **CLI
  flag** — the job runs cold and dies on its second invocation with
  ``Error: Missing argument 'SH'``;
* omit the ``if/elif`` branch in ``_create_per_invocation_cap`` and it falls
  through to a bare ``type_()``, which may or may not work;
* omit the ``_bind_*`` call and the capability is injected and **inert**.

The first two are defect D8 of the ``pipeline-readiness`` branch — `Shell` and
`Stdout` missing from one list. That branch fixed the instances without
changing the pattern.

These tests are about the *pattern*. The first proves a throwaway capability
works through the registry seam alone; the rest pin the properties that made
the old shape dangerous.
"""

from __future__ import annotations

import pytest

from functualize._engine.capabilities.registry import (
    CAPABILITY_SPECS,
    PER_INVOCATION_TYPES,
    SPEC_BY_TYPE,
    CapabilityContext,
    CapabilitySpec,
)
from functualize._primitives.capability_names import INJECTED_PARAM_TYPE_NAMES


def test_the_registry_and_the_low_layer_name_set_agree() -> None:
    """The one thing that cannot derive, so it is checked instead.

    ``_discovery`` consumes the name set and may not import ``_engine`` (peer
    layers are independent), so the strings cannot be computed from the specs.
    This is asserted here *and* at import of the registry module — the import
    check is the one that matters, because it fires on every run rather than
    only when somebody runs the suite.
    """
    assert {spec.name for spec in CAPABILITY_SPECS} == set(INJECTED_PARAM_TYPE_NAMES)


def test_the_import_time_invariant_actually_fires() -> None:
    """Prove the guard is a guard, not a comment.

    The check is the whole reason the string set is allowed to survive as a
    separate list, so "it would raise" is not good enough — it has to raise.
    """
    from functualize._engine.capabilities import registry

    original = registry.CAPABILITY_SPECS
    registry.CAPABILITY_SPECS = (*original, CapabilitySpec(name="Ghost"))
    try:
        with pytest.raises(RuntimeError, match="Ghost"):
            registry._check_name_agreement()
    finally:
        registry.CAPABILITY_SPECS = original


def test_every_per_invocation_spec_can_build_its_capability() -> None:
    """No spec may be declared per-invocation without a way to build it.

    This is site 2 of the old four: a type the resolution plan considered
    resolvable but the resolver could not construct resolved to nothing.
    """
    for spec in CAPABILITY_SPECS:
        if not spec.per_invocation:
            continue
        assert spec.type is not None, f"{spec.name} is per-invocation with no type"
        assert spec.factory is not None, (
            f"{spec.name} is per-invocation with no factory"
        )
        assert SPEC_BY_TYPE[spec.type] is spec


def test_the_type_set_the_engine_uses_is_the_registrys() -> None:
    """`_per_invocation_types()` derives; it does not restate."""
    from functualize._engine.executor import _per_invocation_types

    assert _per_invocation_types() == set(PER_INVOCATION_TYPES)


def test_an_unregistered_type_raises_rather_than_being_constructed() -> None:
    """The removed `type_()` fallback.

    A capability whose branch was never added used to be constructed with no
    arguments. Sometimes that produced a working object; sometimes an inert
    one; it never said which. A missing registration is now loud.
    """
    from functualize._engine.executor import JobExecutionEngine

    class Unregistered:
        pass

    engine = JobExecutionEngine.__new__(JobExecutionEngine)
    engine._config_view_type = None

    with pytest.raises(KeyError, match="CapabilitySpec"):
        engine._create_per_invocation_cap(Unregistered, context=None, caps={})


def test_the_two_phase_bind_is_declared_not_remembered() -> None:
    """`Sources` is the only capability completed after the pre-flight — today.

    The point is not the membership but that it is *readable*: the executor
    loops over the specs that declare a `preflight_bind` instead of calling one
    hard-coded function at one line. A second capability of this shape declares
    it and is found.
    """
    from functualize._engine.capabilities.sources import Sources

    declaring = {spec.name for spec in CAPABILITY_SPECS if spec.needs_preflight_bind}
    assert declaring == {"Sources"}
    assert SPEC_BY_TYPE[Sources].preflight_bind is not None


def test_a_declared_bind_is_invoked_with_the_preflight_decision() -> None:
    """The loop reaches a spec's own bind, not a hard-coded `Sources` call."""
    from functualize._engine.executor import JobExecutionEngine

    seen: list[object] = []

    class Probe:
        pass

    probe_spec = CapabilitySpec(
        name="Probe",
        type=Probe,
        factory=lambda ctx: Probe(),
        preflight_bind=lambda instance, decision: seen.append(decision),
    )

    from functualize._engine.capabilities import registry

    original = registry.CAPABILITY_SPECS
    registry.CAPABILITY_SPECS = (*original, probe_spec)
    try:

        class _Ctx:
            capabilities = {Probe: Probe()}

        JobExecutionEngine._bind_preflight_capabilities(_Ctx(), "DECISION")
    finally:
        registry.CAPABILITY_SPECS = original

    assert seen == ["DECISION"]


def test_a_capability_context_is_the_only_factory_argument() -> None:
    """One argument bundle for every factory — what let the ladder collapse.

    A dispatch table cannot have per-branch signatures, so the uniformity is
    load-bearing rather than tidy.
    """
    from functualize._engine.capabilities.log import CAPABILITY as LOG_SPEC

    class _Ctx:
        job_name = "probe"

    assert LOG_SPEC.factory is not None
    built = LOG_SPEC.factory(CapabilityContext(engine=None, context=_Ctx(), caps={}))
    assert type(built).__name__ == "Log"
