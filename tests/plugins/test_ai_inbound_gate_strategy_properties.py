"""Property-based tests for AI_INBOUND gate resolver prompt construction.

Tests Property 19 from the Phase 2–5 Domain SDKs design document.

Property 19: AI_INBOUND gate resolver includes context in prompt —
For any GateContext, the AI_INBOUND resolver SHALL construct a prompt that
includes all resolved_fields as context and explicitly asks the LLM to decide
values for all unresolved_fields.

**Validates: Requirements 10.3, 10.4**
"""

from __future__ import annotations

import keyword
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from functualize_ai._ai import AI
from functualize_ai._gate_strategy import (
    AIInboundGateResolver,
    _build_prompt,
)
from hypothesis import assume, given
from hypothesis import strategies as st
from pydantic import BaseModel, Field, create_model

from functualize._gate._context import GateContext

if TYPE_CHECKING:
    from functualize_ai._types import AILimits, AIResult

# --- Helpers ---


class CapturingAIProvider:
    """AI provider that captures the prompt and response_model passed to complete().

    Returns a dummy instance of the response_model when called.
    """

    def __init__(self) -> None:
        self.last_prompt: str | None = None
        self.last_response_model: type | None = None
        self.call_count: int = 0

    def complete(
        self, prompt: str, *, response_model: type | None = None, **kwargs: Any
    ) -> Any:
        self.last_prompt = prompt
        self.last_response_model = response_model
        self.call_count += 1
        # Return a valid instance of the response_model with defaults
        if response_model is not None:
            # Construct with default values for all fields
            field_values = {}
            for name, field_info in response_model.model_fields.items():
                if field_info.default is not None:
                    field_values[name] = field_info.default
                else:
                    # Provide a generic value based on annotation
                    annotation = field_info.annotation
                    if annotation is int:
                        field_values[name] = 0
                    elif annotation is float:
                        field_values[name] = 0.0
                    elif annotation is bool:
                        field_values[name] = False
                    else:
                        field_values[name] = "generated"
            return response_model(**field_values)
        return "generated text"

    def run(
        self,
        prompt: str,
        *,
        tools: Any = None,
        response_model: type | None = None,
        limits: AILimits | None = None,
        **kwargs: Any,
    ) -> AIResult:
        raise NotImplementedError

    def stream(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        raise NotImplementedError

    def extract(self, text: str, *, model: type) -> Any:
        raise NotImplementedError


def _build_dynamic_model(field_names: list[str]) -> type[BaseModel]:
    """Build a dynamic Pydantic model with all string fields having defaults.

    All fields have default values and descriptions so the resolver can
    construct prompts including type hints and descriptions.
    """
    field_definitions: dict[str, Any] = {}
    for name in field_names:
        field_definitions[name] = (
            str,
            Field(default="default_val", description=f"Description for {name}"),
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


# Strategy for valid Python identifier field names
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

# Strategy for resolved field values (simple JSON-compatible values)
resolved_values = st.one_of(
    st.text(min_size=1, max_size=50),
    st.integers(min_value=-1000, max_value=1000),
    st.booleans(),
)


# --- Property 19a: Prompt contains all resolved field names and values ---


class TestBuildPromptIncludesResolvedFields:
    """Property 19a: For any GateContext with resolved_fields, the prompt SHALL
    contain all resolved field names and their values.

    **Validates: Requirements 10.3**
    """

    @given(
        all_fields=field_names_strategy,
        data=st.data(),
    )
    def test_prompt_contains_all_resolved_field_names(
        self, all_fields: list[str], data: st.DataObject
    ) -> None:
        """For any set of resolved fields, _build_prompt includes every field name.

        **Validates: Requirements 10.3**
        """
        # Partition fields: at least one resolved
        assume(len(all_fields) >= 1)
        split_idx = data.draw(
            st.integers(min_value=1, max_value=len(all_fields)), label="split_idx"
        )
        resolved_names = all_fields[:split_idx]
        unresolved_names = all_fields[split_idx:]

        model_class = _build_dynamic_model(all_fields)

        # Generate values for resolved fields
        resolved_fields = {}
        for name in resolved_names:
            resolved_fields[name] = data.draw(resolved_values, label=f"val_{name}")

        ctx = GateContext(
            model_class=model_class,
            resolved_fields=resolved_fields,
            unresolved_fields=unresolved_names,
            all_fields=all_fields,
            force_gate=False,
        )

        prompt = _build_prompt(ctx)

        # Every resolved field name must appear in the prompt
        for field_name in resolved_names:
            assert field_name in prompt, (
                f"Resolved field name '{field_name}' not found in prompt"
            )

    @given(
        all_fields=field_names_strategy,
        data=st.data(),
    )
    def test_prompt_contains_all_resolved_field_values(
        self, all_fields: list[str], data: st.DataObject
    ) -> None:
        """For any set of resolved fields, _build_prompt includes every field value repr.

        **Validates: Requirements 10.3**
        """
        assume(len(all_fields) >= 1)
        split_idx = data.draw(
            st.integers(min_value=1, max_value=len(all_fields)), label="split_idx"
        )
        resolved_names = all_fields[:split_idx]
        unresolved_names = all_fields[split_idx:]

        model_class = _build_dynamic_model(all_fields)

        resolved_fields = {}
        for name in resolved_names:
            resolved_fields[name] = data.draw(resolved_values, label=f"val_{name}")

        ctx = GateContext(
            model_class=model_class,
            resolved_fields=resolved_fields,
            unresolved_fields=unresolved_names,
            all_fields=all_fields,
            force_gate=False,
        )

        prompt = _build_prompt(ctx)

        # Every resolved field value repr must appear in the prompt
        for field_name, value in resolved_fields.items():
            assert repr(value) in prompt, (
                f"Resolved field value repr({value!r}) for '{field_name}' "
                f"not found in prompt"
            )


# --- Property 19b: Prompt contains all unresolved field names ---


class TestBuildPromptIncludesUnresolvedFields:
    """Property 19b: For any GateContext with unresolved_fields, the prompt SHALL
    contain all unresolved field names.

    **Validates: Requirements 10.4**
    """

    @given(
        all_fields=field_names_strategy,
        data=st.data(),
    )
    def test_prompt_contains_all_unresolved_field_names(
        self, all_fields: list[str], data: st.DataObject
    ) -> None:
        """For any set of unresolved fields, _build_prompt includes every field name.

        **Validates: Requirements 10.4**
        """
        # Partition fields: at least one unresolved
        assume(len(all_fields) >= 1)
        split_idx = data.draw(
            st.integers(min_value=0, max_value=len(all_fields) - 1),
            label="split_idx",
        )
        resolved_names = all_fields[:split_idx]
        unresolved_names = all_fields[split_idx:]

        assume(len(unresolved_names) >= 1)

        model_class = _build_dynamic_model(all_fields)

        resolved_fields = {}
        for name in resolved_names:
            resolved_fields[name] = data.draw(resolved_values, label=f"val_{name}")

        ctx = GateContext(
            model_class=model_class,
            resolved_fields=resolved_fields,
            unresolved_fields=unresolved_names,
            all_fields=all_fields,
            force_gate=False,
        )

        prompt = _build_prompt(ctx)

        # Every unresolved field name must appear in the prompt
        for field_name in unresolved_names:
            assert field_name in prompt, (
                f"Unresolved field name '{field_name}' not found in prompt"
            )

    @given(
        all_fields=field_names_strategy,
    )
    def test_prompt_all_unresolved_no_resolved(self, all_fields: list[str]) -> None:
        """When all fields are unresolved, all field names appear in prompt.

        **Validates: Requirements 10.4**
        """
        model_class = _build_dynamic_model(all_fields)

        ctx = GateContext(
            model_class=model_class,
            resolved_fields={},
            unresolved_fields=all_fields,
            all_fields=all_fields,
            force_gate=False,
        )

        prompt = _build_prompt(ctx)

        for field_name in all_fields:
            assert field_name in prompt, (
                f"Field name '{field_name}' not found in prompt when all unresolved"
            )


# --- Property 19c: Resolver uses AI.complete() with response_model ---


class TestResolverUsesAICompleteWithResponseModel:
    """Property 19c: The resolver uses AI.complete() with response_model set to
    the gate's model_class.

    **Validates: Requirements 10.3, 10.4**
    """

    @given(
        all_fields=field_names_strategy,
        data=st.data(),
    )
    def test_resolver_passes_model_class_as_response_model(
        self, all_fields: list[str], data: st.DataObject
    ) -> None:
        """For any GateContext, the resolver calls AI.complete with response_model
        set to the gate's model_class.

        **Validates: Requirements 10.3, 10.4**
        """
        split_idx = data.draw(
            st.integers(min_value=0, max_value=len(all_fields)),
            label="split_idx",
        )
        resolved_names = all_fields[:split_idx]
        unresolved_names = all_fields[split_idx:]

        model_class = _build_dynamic_model(all_fields)

        resolved_fields = {}
        for name in resolved_names:
            resolved_fields[name] = data.draw(resolved_values, label=f"val_{name}")

        ctx = GateContext(
            model_class=model_class,
            resolved_fields=resolved_fields,
            unresolved_fields=unresolved_names,
            all_fields=all_fields,
            force_gate=False,
        )

        provider = CapturingAIProvider()
        ai = AI(_provider=provider)
        resolver = AIInboundGateResolver(ai=ai)

        result = resolver.resolve(ctx)

        # The resolver must call AI.complete with the gate's model_class
        assert provider.last_response_model is model_class, (
            f"Expected response_model={model_class.__name__}, "
            f"got {provider.last_response_model}"
        )
        assert provider.call_count == 1
        assert isinstance(result, model_class)

    @given(
        all_fields=field_names_strategy,
        data=st.data(),
    )
    def test_resolver_prompt_matches_build_prompt_output(
        self, all_fields: list[str], data: st.DataObject
    ) -> None:
        """For any GateContext, the prompt passed to AI.complete matches _build_prompt.

        **Validates: Requirements 10.3, 10.4**
        """
        split_idx = data.draw(
            st.integers(min_value=0, max_value=len(all_fields)),
            label="split_idx",
        )
        resolved_names = all_fields[:split_idx]
        unresolved_names = all_fields[split_idx:]

        model_class = _build_dynamic_model(all_fields)

        resolved_fields = {}
        for name in resolved_names:
            resolved_fields[name] = data.draw(resolved_values, label=f"val_{name}")

        ctx = GateContext(
            model_class=model_class,
            resolved_fields=resolved_fields,
            unresolved_fields=unresolved_names,
            all_fields=all_fields,
            force_gate=False,
        )

        provider = CapturingAIProvider()
        ai = AI(_provider=provider)
        resolver = AIInboundGateResolver(ai=ai)

        resolver.resolve(ctx)

        # The prompt sent to the provider should match _build_prompt
        expected_prompt = _build_prompt(ctx)
        assert provider.last_prompt == expected_prompt, (
            "Prompt passed to AI.complete() does not match _build_prompt(ctx)"
        )
