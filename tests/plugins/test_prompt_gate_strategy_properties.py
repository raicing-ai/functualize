"""Property-based tests for PROMPT gate resolver field handling.

Tests Property 6 from the Phase 2–5 Domain SDKs design document.

Property 6: PROMPT gate resolver prompts for exactly unresolved fields —
For any GateContext with unresolved_fields = [f1, f2, ..., fK] and
force_gate=False, the PROMPT gate resolver SHALL prompt the user for exactly
those K fields and no others. When force_gate=True, the resolver SHALL present
all fields (resolved + unresolved) to the user.

**Validates: Requirements 2.2, 2.3**
"""

from __future__ import annotations

import keyword
from typing import Any

from hypothesis import assume, given
from hypothesis import strategies as st
from pydantic import BaseModel, Field, create_model

from functualize._gate._context import GateContext
from functualize._gate.prompt_strategy import PromptGateResolver
from functualize._types.interactivity import PromptRequest, PromptResponse

# --- Helpers ---


class TrackingInputProvider:
    """InputProvider that tracks which fields were prompted.

    Records each prompt request and returns a valid value for the field.
    """

    def __init__(self) -> None:
        self.prompted_fields: list[str] = []
        self.requests: list[PromptRequest] = []

    def collect(self, request: PromptRequest) -> PromptResponse:
        """Record the request and return a generic string value."""
        self.requests.append(request)
        # Extract field name from the question label (format: "Field name" or "Field name (desc)")
        # The resolver builds questions as "Label" or "Label (description)"
        question = request.question
        label = question.split(" (")[0] if " (" in question else question
        # Convert label back to approximate field name for tracking
        self.prompted_fields.append(label.lower().replace(" ", "_"))
        # Return the default if available, otherwise a string value
        if request.default is not None:
            return PromptResponse(value=request.default, source="user")
        return PromptResponse(value="test_value", source="user")


def _build_dynamic_model(field_names: list[str]) -> type[BaseModel]:
    """Build a dynamic Pydantic model with all string fields having defaults.

    All fields have default values to avoid validation errors from our
    generic "test_value" responses.
    """
    field_definitions: dict[str, Any] = {}
    for name in field_names:
        field_definitions[name] = (
            str,
            Field(default="default_val", description=f"Field {name}"),
        )
    model = create_model("DynamicGateModel", **field_definitions)
    return model


# --- Strategies ---


# Reserved names that conflict with Pydantic BaseModel attributes
def _is_usable_pydantic_field_name(s: str) -> bool:
    """Names this generator may safely build a dynamic pydantic model from.

    Derived from `BaseModel` rather than hand-listed. The previous version was a
    literal blocklist that named "model" but not "model_dump", so the ci profile
    eventually drew `model_dump` and `create_model` raised
    ``ValueError: Field 'model_dump' conflicts with member ... of protected
    namespace``. Any hand-maintained list of another library's reserved names is
    incomplete by construction; asking the class is not.
    """
    if not s.isidentifier() or keyword.iskeyword(s) or keyword.issoftkeyword(s):
        return False
    if s.startswith("_"):
        return False
    # Pydantic reserves the whole `model_` prefix, and rejects any name that
    # shadows an existing BaseModel member.
    return not s.startswith("model_") and not hasattr(BaseModel, s)


# Strategy for valid Python identifier field names (at least 2 chars, valid identifiers)
field_name_strategy = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz_"),
    min_size=2,
    max_size=12,
).filter(_is_usable_pydantic_field_name)

# Strategy for generating a set of unique field names (between 1 and 8 fields)
field_names_strategy = st.lists(
    field_name_strategy,
    min_size=1,
    max_size=8,
    unique=True,
)


# --- Property 6a: force_gate=False prompts exactly unresolved fields ---


class TestPromptGateResolverUnresolvedFieldsProperty:
    """Property 6a: With force_gate=False, the resolver prompts for exactly unresolved fields.

    **Validates: Requirements 2.2**
    """

    @given(
        all_fields=field_names_strategy,
        data=st.data(),
    )
    def test_prompts_exactly_unresolved_fields(
        self, all_fields: list[str], data: st.DataObject
    ) -> None:
        """For any partition of fields into resolved/unresolved with force_gate=False,
        the resolver prompts for exactly the unresolved fields and no others.

        **Validates: Requirements 2.2**
        """
        # Partition fields into resolved and unresolved subsets
        resolved_mask = data.draw(
            st.lists(
                st.booleans(),
                min_size=len(all_fields),
                max_size=len(all_fields),
            )
        )
        resolved_fields_names = [
            f
            for f, is_resolved in zip(all_fields, resolved_mask, strict=False)
            if is_resolved
        ]
        unresolved_fields_names = [
            f
            for f, is_resolved in zip(all_fields, resolved_mask, strict=False)
            if not is_resolved
        ]

        # Build a dynamic model and context
        model_class = _build_dynamic_model(all_fields)
        resolved_values = {f: f"resolved_{f}" for f in resolved_fields_names}

        ctx = GateContext(
            model_class=model_class,
            resolved_fields=resolved_values,
            unresolved_fields=unresolved_fields_names,
            all_fields=all_fields,
            force_gate=False,
        )

        # Run the resolver
        provider = TrackingInputProvider()
        # The collector is resolved lazily through a factory so the strategy can
        # be registered at boot, before any surface exists.
        resolver = PromptGateResolver(collector_factory=lambda _app: provider)
        resolver.resolve(ctx)

        # Assert: number of prompts equals number of unresolved fields
        assert len(provider.requests) == len(unresolved_fields_names), (
            f"Expected {len(unresolved_fields_names)} prompts for unresolved fields, "
            f"got {len(provider.requests)}"
        )

    @given(
        all_fields=field_names_strategy,
        data=st.data(),
    )
    def test_prompted_field_set_matches_unresolved_set(
        self, all_fields: list[str], data: st.DataObject
    ) -> None:
        """The set of prompted fields is exactly the set of unresolved fields (no extras, no missing).

        **Validates: Requirements 2.2**
        """
        # Ensure at least one unresolved field
        resolved_mask = data.draw(
            st.lists(
                st.booleans(),
                min_size=len(all_fields),
                max_size=len(all_fields),
            )
        )
        resolved_fields_names = [
            f
            for f, is_resolved in zip(all_fields, resolved_mask, strict=False)
            if is_resolved
        ]
        unresolved_fields_names = [
            f
            for f, is_resolved in zip(all_fields, resolved_mask, strict=False)
            if not is_resolved
        ]

        assume(len(unresolved_fields_names) > 0)

        model_class = _build_dynamic_model(all_fields)
        resolved_values = {f: f"resolved_{f}" for f in resolved_fields_names}

        ctx = GateContext(
            model_class=model_class,
            resolved_fields=resolved_values,
            unresolved_fields=unresolved_fields_names,
            all_fields=all_fields,
            force_gate=False,
        )

        provider = TrackingInputProvider()
        # The collector is resolved lazily through a factory so the strategy can
        # be registered at boot, before any surface exists.
        resolver = PromptGateResolver(collector_factory=lambda _app: provider)
        resolver.resolve(ctx)

        # The prompted fields should match unresolved fields exactly
        assert provider.prompted_fields == unresolved_fields_names, (
            f"Expected prompts for {unresolved_fields_names}, "
            f"got prompts for {provider.prompted_fields}"
        )


# --- Property 6b: force_gate=True prompts for ALL fields ---


class TestPromptGateResolverForceGateProperty:
    """Property 6b: With force_gate=True, the resolver prompts for all fields.

    **Validates: Requirements 2.3**
    """

    @given(
        all_fields=field_names_strategy,
        data=st.data(),
    )
    def test_force_gate_prompts_all_fields(
        self, all_fields: list[str], data: st.DataObject
    ) -> None:
        """When force_gate=True, the resolver prompts for all fields regardless of resolution state.

        **Validates: Requirements 2.3**
        """
        # Create an arbitrary partition (doesn't matter for force_gate=True)
        resolved_mask = data.draw(
            st.lists(
                st.booleans(),
                min_size=len(all_fields),
                max_size=len(all_fields),
            )
        )
        resolved_fields_names = [
            f
            for f, is_resolved in zip(all_fields, resolved_mask, strict=False)
            if is_resolved
        ]
        unresolved_fields_names = [
            f
            for f, is_resolved in zip(all_fields, resolved_mask, strict=False)
            if not is_resolved
        ]

        model_class = _build_dynamic_model(all_fields)
        resolved_values = {f: f"resolved_{f}" for f in resolved_fields_names}

        ctx = GateContext(
            model_class=model_class,
            resolved_fields=resolved_values,
            unresolved_fields=unresolved_fields_names,
            all_fields=all_fields,
            force_gate=True,
        )

        provider = TrackingInputProvider()
        # The collector is resolved lazily through a factory so the strategy can
        # be registered at boot, before any surface exists.
        resolver = PromptGateResolver(collector_factory=lambda _app: provider)
        resolver.resolve(ctx)

        # Assert: number of prompts equals total number of fields
        assert len(provider.requests) == len(all_fields), (
            f"Expected {len(all_fields)} prompts for all fields (force_gate=True), "
            f"got {len(provider.requests)}"
        )

    @given(
        all_fields=field_names_strategy,
        data=st.data(),
    )
    def test_force_gate_prompted_field_set_matches_all_fields(
        self, all_fields: list[str], data: st.DataObject
    ) -> None:
        """The set of prompted fields with force_gate=True is exactly all_fields.

        **Validates: Requirements 2.3**
        """
        resolved_mask = data.draw(
            st.lists(
                st.booleans(),
                min_size=len(all_fields),
                max_size=len(all_fields),
            )
        )
        resolved_fields_names = [
            f
            for f, is_resolved in zip(all_fields, resolved_mask, strict=False)
            if is_resolved
        ]
        unresolved_fields_names = [
            f
            for f, is_resolved in zip(all_fields, resolved_mask, strict=False)
            if not is_resolved
        ]

        model_class = _build_dynamic_model(all_fields)
        resolved_values = {f: f"resolved_{f}" for f in resolved_fields_names}

        ctx = GateContext(
            model_class=model_class,
            resolved_fields=resolved_values,
            unresolved_fields=unresolved_fields_names,
            all_fields=all_fields,
            force_gate=True,
        )

        provider = TrackingInputProvider()
        # The collector is resolved lazily through a factory so the strategy can
        # be registered at boot, before any surface exists.
        resolver = PromptGateResolver(collector_factory=lambda _app: provider)
        resolver.resolve(ctx)

        # The prompted fields should match all_fields exactly
        assert provider.prompted_fields == all_fields, (
            f"Expected prompts for all fields {all_fields}, "
            f"got prompts for {provider.prompted_fields}"
        )

    @given(
        all_fields=field_names_strategy,
        data=st.data(),
    )
    def test_force_gate_resolved_values_used_as_defaults(
        self, all_fields: list[str], data: st.DataObject
    ) -> None:
        """When force_gate=True, already-resolved fields have their values as prompt defaults.

        **Validates: Requirements 2.3**
        """
        # Ensure at least one resolved field
        resolved_mask = data.draw(
            st.lists(
                st.booleans(),
                min_size=len(all_fields),
                max_size=len(all_fields),
            )
        )
        resolved_fields_names = [
            f
            for f, is_resolved in zip(all_fields, resolved_mask, strict=False)
            if is_resolved
        ]
        unresolved_fields_names = [
            f
            for f, is_resolved in zip(all_fields, resolved_mask, strict=False)
            if not is_resolved
        ]

        assume(len(resolved_fields_names) > 0)

        model_class = _build_dynamic_model(all_fields)
        resolved_values = {f: f"resolved_{f}" for f in resolved_fields_names}

        ctx = GateContext(
            model_class=model_class,
            resolved_fields=resolved_values,
            unresolved_fields=unresolved_fields_names,
            all_fields=all_fields,
            force_gate=True,
        )

        provider = TrackingInputProvider()
        # The collector is resolved lazily through a factory so the strategy can
        # be registered at boot, before any surface exists.
        resolver = PromptGateResolver(collector_factory=lambda _app: provider)
        resolver.resolve(ctx)

        # For each resolved field, its prompt should have the resolved value as default
        for i, field_name in enumerate(all_fields):
            if field_name in resolved_values:
                assert provider.requests[i].default == resolved_values[field_name], (
                    f"Resolved field '{field_name}' prompt default should be "
                    f"'{resolved_values[field_name]}', got '{provider.requests[i].default}'"
                )
