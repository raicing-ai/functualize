"""AI capability class — provider-agnostic LLM interaction.

The AI class provides convenient methods (complete, run, stream, extract) that
delegate to a registered AIProvider. If no provider is registered, all methods
raise AINotAvailableError with install instructions.

The EventBus and StateNamespace are duck-typed:
- EventBus must have an ``emit(event_name: str, **payload)`` method.
- StateNamespace must have ``get(key, default=None)`` and ``set(key, value)`` methods.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from functualize_ai._errors import AINotAvailableError, BudgetExceededError
from functualize_ai._events import (
    AI_BUDGET_EXCEEDED,
    AI_CALL_COMPLETED,
    AI_CALL_FAILED,
    AI_CALL_STARTED,
    AI_TOOL_CALLED,
)

if TYPE_CHECKING:
    from functualize_ai._protocols import AIProvider
    from functualize_ai._tool_scope import ToolScope
    from functualize_ai._types import AILimits, AIResult, ToolDef

T = TypeVar("T")

_NO_PROVIDER_MESSAGE = (
    "No AI provider configured. Install one: pip install functualize-ai-pydantic"
)


class _EventBus(Protocol):
    """Duck-typed EventBus — only requires an emit method."""

    def emit(self, event_name: str, **payload: Any) -> None: ...


class AI:
    """LLM interaction capability — provider-agnostic.

    Provides structured output, tool calling, streaming, and extraction
    capabilities backed by a pluggable AIProvider implementation.

    Args:
        _provider: The AIProvider implementation to delegate to, or None.
        _event_bus: An optional event bus (duck-typed with ``emit()``).
        _state_ns: An optional StateNamespace (duck-typed with ``get``/``set``).
    """

    def __init__(
        self,
        *,
        _provider: AIProvider | None = None,
        _event_bus: Any | None = None,
        _state_ns: Any | None = None,
    ) -> None:
        self._provider = _provider
        self._event_bus = _event_bus
        self._state_ns = _state_ns

    def _emit(self, event_name: str, **payload: Any) -> None:
        """Emit an event if an event bus is available."""
        if self._event_bus is not None:
            self._event_bus.emit(event_name, **payload)

    def _ensure_provider(self) -> AIProvider:
        """Return the active provider or raise AINotAvailableError."""
        if self._provider is None:
            raise AINotAvailableError(_NO_PROVIDER_MESSAGE)
        return self._provider

    def complete(
        self, prompt: str, *, response_model: type[T] | None = None, **kwargs: Any
    ) -> Any:
        """Complete a prompt, optionally returning structured output.

        If ``response_model`` is provided, validates the provider response against
        the model schema. Retries up to 3 times on validation failure, then raises
        ValueError.

        If no ``response_model``, returns the raw text response as a string.

        Args:
            prompt: The prompt text to send to the LLM.
            response_model: Optional type for structured output validation.
            **kwargs: Additional provider-specific parameters.

        Returns:
            An instance of ``response_model`` if provided, otherwise a string.

        Raises:
            AINotAvailableError: If no provider is registered or provider raises.
            ValueError: If schema validation fails after 3 retries.
        """
        provider = self._ensure_provider()

        model_name = kwargs.get("model", "unknown")
        self._emit(
            AI_CALL_STARTED,
            prompt_length=len(prompt),
            model=model_name,
            tools_count=0,
        )
        start_time = time.time()

        if response_model is None:
            try:
                result = provider.complete(prompt, response_model=None, **kwargs)
                duration_ms = (time.time() - start_time) * 1000
                self._emit(
                    AI_CALL_COMPLETED,
                    tokens=None,
                    duration_ms=duration_ms,
                    tool_calls_count=0,
                )
                return result
            except AINotAvailableError:
                duration_ms = (time.time() - start_time) * 1000
                self._emit(
                    AI_CALL_FAILED, error="AINotAvailableError", duration_ms=duration_ms
                )
                raise
            except Exception as exc:
                duration_ms = (time.time() - start_time) * 1000
                self._emit(AI_CALL_FAILED, error=str(exc), duration_ms=duration_ms)
                raise AINotAvailableError(str(exc)) from exc

        # With response_model: retry up to 3 times on validation failure
        last_error: Exception | None = None
        for _attempt in range(3):
            try:
                result = provider.complete(
                    prompt, response_model=response_model, **kwargs
                )
                # Validate by attempting to construct the model if needed
                validated = _validate_response(result, response_model)
                duration_ms = (time.time() - start_time) * 1000
                self._emit(
                    AI_CALL_COMPLETED,
                    tokens=None,
                    duration_ms=duration_ms,
                    tool_calls_count=0,
                )
                return validated
            except ValueError as ve:
                last_error = ve
                continue
            except AINotAvailableError:
                duration_ms = (time.time() - start_time) * 1000
                self._emit(
                    AI_CALL_FAILED, error="AINotAvailableError", duration_ms=duration_ms
                )
                raise
            except Exception as exc:
                duration_ms = (time.time() - start_time) * 1000
                self._emit(AI_CALL_FAILED, error=str(exc), duration_ms=duration_ms)
                raise AINotAvailableError(str(exc)) from exc

        # All retries exhausted
        duration_ms = (time.time() - start_time) * 1000
        self._emit(AI_CALL_FAILED, error=str(last_error), duration_ms=duration_ms)
        raise ValueError(f"Schema validation failed after 3 retries: {last_error}")

    def run(
        self,
        prompt: str,
        *,
        tools: ToolScope | None = None,
        response_model: type[T] | None = None,
        limits: AILimits | None = None,
        **kwargs: Any,
    ) -> AIResult:
        """Run a prompt with optional tool calling, structured output, and limits.

        When a ``ToolScope`` is provided, resolves it to tool definitions via
        ``scope.to_tool_defs()`` and passes them to the provider.

        Args:
            prompt: The prompt text to send to the LLM.
            tools: Optional ToolScope restricting available tools.
            response_model: Optional type for structured output.
            limits: Optional budget and constraint caps.
            **kwargs: Additional provider-specific parameters.

        Returns:
            An AIResult containing output, tool call records, usage, and duration.

        Raises:
            AINotAvailableError: If no provider is registered or provider raises.
            BudgetExceededError: If cumulative budget is exceeded.
        """
        provider = self._ensure_provider()

        # Resolve ToolScope to tool definitions
        tool_defs: list[ToolDef] | None = None
        if tools is not None:
            # Use kwargs job_registry if provided, otherwise pass empty list
            job_registry = kwargs.pop("job_registry", None)
            if job_registry is not None:
                tool_defs = tools.to_tool_defs(job_registry)
            else:
                tool_defs = tools.to_tool_defs([])

        tools_count = len(tool_defs) if tool_defs else 0
        model_name = kwargs.get("model", "unknown")

        # Budget check before the call
        if (
            limits is not None
            and limits.budget_usd is not None
            and self._state_ns is not None
        ):
            from functualize_ai._budget import BudgetEnforcer

            enforcer = BudgetEnforcer(state_ns=self._state_ns)
            try:
                enforcer.check_budget(limits)
            except BudgetExceededError:
                self._emit(
                    AI_BUDGET_EXCEEDED,
                    limit=limits.budget_usd,
                    actual=enforcer.get_cumulative_spend(),
                    job_name=kwargs.get("job_name", ""),
                )
                raise

        self._emit(
            AI_CALL_STARTED,
            prompt_length=len(prompt),
            model=model_name,
            tools_count=tools_count,
        )
        start_time = time.time()

        try:
            result = provider.run(
                prompt,
                tools=tool_defs,
                response_model=response_model,
                limits=limits,
                **kwargs,
            )

            duration_ms = (time.time() - start_time) * 1000

            # Emit tool.called events for each tool call in the result
            for tc in result.tool_calls:
                self._emit(
                    AI_TOOL_CALLED,
                    tool_name=tc.tool_name,
                    args=tc.args,
                    duration_ms=tc.duration_ms,
                    status="success",
                )

            # Record budget spend if state is available
            if self._state_ns is not None and result.usage.cost_usd is not None:
                from functualize_ai._budget import BudgetEnforcer

                enforcer = BudgetEnforcer(state_ns=self._state_ns)
                enforcer.record_spend(result.usage)

            self._emit(
                AI_CALL_COMPLETED,
                tokens=result.usage,
                duration_ms=duration_ms,
                tool_calls_count=len(result.tool_calls),
            )
            return result
        except AINotAvailableError:
            duration_ms = (time.time() - start_time) * 1000
            self._emit(
                AI_CALL_FAILED, error="AINotAvailableError", duration_ms=duration_ms
            )
            raise
        except BudgetExceededError:
            duration_ms = (time.time() - start_time) * 1000
            self._emit(
                AI_CALL_FAILED, error="BudgetExceededError", duration_ms=duration_ms
            )
            raise
        except Exception as exc:
            duration_ms = (time.time() - start_time) * 1000
            self._emit(AI_CALL_FAILED, error=str(exc), duration_ms=duration_ms)
            raise AINotAvailableError(str(exc)) from exc

    def stream(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        """Stream a response as incremental text chunks.

        Args:
            prompt: The prompt text to send to the LLM.
            **kwargs: Additional provider-specific parameters.

        Returns:
            An iterator yielding string chunks of the response.

        Raises:
            AINotAvailableError: If no provider is registered or provider raises.
        """
        provider = self._ensure_provider()

        model_name = kwargs.get("model", "unknown")
        self._emit(
            AI_CALL_STARTED,
            prompt_length=len(prompt),
            model=model_name,
            tools_count=0,
        )
        start_time = time.time()

        try:
            result = provider.stream(prompt, **kwargs)
            duration_ms = (time.time() - start_time) * 1000
            self._emit(
                AI_CALL_COMPLETED,
                tokens=None,
                duration_ms=duration_ms,
                tool_calls_count=0,
            )
            return result
        except AINotAvailableError:
            duration_ms = (time.time() - start_time) * 1000
            self._emit(
                AI_CALL_FAILED, error="AINotAvailableError", duration_ms=duration_ms
            )
            raise
        except Exception as exc:
            duration_ms = (time.time() - start_time) * 1000
            self._emit(AI_CALL_FAILED, error=str(exc), duration_ms=duration_ms)
            raise AINotAvailableError(str(exc)) from exc

    def extract(self, text: str, *, model: type[T]) -> Any:
        """Extract structured data from text.

        Validates the provider response against the model schema.
        Retries up to 3 times on validation failure, then raises ValueError.

        Args:
            text: The text to extract data from.
            model: The type to extract into.

        Returns:
            An instance of ``model`` populated from the text.

        Raises:
            AINotAvailableError: If no provider is registered or provider raises.
            ValueError: If extraction validation fails after 3 retries.
        """
        provider = self._ensure_provider()

        self._emit(
            AI_CALL_STARTED,
            prompt_length=len(text),
            model="unknown",
            tools_count=0,
        )
        start_time = time.time()

        last_error: Exception | None = None
        for _attempt in range(3):
            try:
                result = provider.extract(text, model=model)
                validated = _validate_response(result, model)
                duration_ms = (time.time() - start_time) * 1000
                self._emit(
                    AI_CALL_COMPLETED,
                    tokens=None,
                    duration_ms=duration_ms,
                    tool_calls_count=0,
                )
                return validated
            except ValueError as ve:
                last_error = ve
                continue
            except AINotAvailableError:
                duration_ms = (time.time() - start_time) * 1000
                self._emit(
                    AI_CALL_FAILED, error="AINotAvailableError", duration_ms=duration_ms
                )
                raise
            except Exception as exc:
                duration_ms = (time.time() - start_time) * 1000
                self._emit(AI_CALL_FAILED, error=str(exc), duration_ms=duration_ms)
                raise AINotAvailableError(str(exc)) from exc

        # All retries exhausted
        duration_ms = (time.time() - start_time) * 1000
        self._emit(AI_CALL_FAILED, error=str(last_error), duration_ms=duration_ms)
        raise ValueError(f"Schema validation failed after 3 retries: {last_error}")


def _validate_response(result: Any, expected_type: type) -> Any:
    """Validate that result is an instance of expected_type.

    If the result is already the correct type, return as-is.
    If expected_type is a Pydantic model and result is a dict, attempt construction.

    Args:
        result: The value to validate.
        expected_type: The expected type.

    Returns:
        The validated instance.

    Raises:
        ValueError: If validation fails.
    """
    if isinstance(result, expected_type):
        return result

    # Try Pydantic model construction from dict
    if isinstance(result, dict) and hasattr(expected_type, "model_validate"):
        try:
            return expected_type.model_validate(result)
        except Exception as exc:
            raise ValueError(
                f"Failed to validate response against {expected_type.__name__}: {exc}"
            ) from exc

    # Try basic construction from dict
    if isinstance(result, dict):
        try:
            return expected_type(**result)
        except Exception as exc:
            raise ValueError(
                f"Failed to construct {expected_type.__name__} from response: {exc}"
            ) from exc

    raise ValueError(f"Expected {expected_type.__name__}, got {type(result).__name__}")
