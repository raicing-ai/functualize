"""Unit tests for error handling edge cases across the composable DX surface.

Tests validation errors raised by:
- ResolutionPipeline.add_provider with non-provider arguments
- ResolutionPipeline.add_transform with non-transform arguments
- NamespaceTransform("") with empty prefix
- @app.on_job_failure("") with empty job name
- @app.before_job on a no-param function
- @app.run_middleware on a non-generator function
- @app.on_event("invalid!!pattern") with invalid event pattern

**Validates: Requirements 3.4, 4.5, 9.5, 14.4, 16.4, 17.5, 18.5, 28.5**
"""

from __future__ import annotations

from typing import Any

import pytest

from functualize._discovery.pipeline import ResolutionPipeline
from functualize._discovery.transforms import NamespaceTransform
from functualize.app.core import FunctualizeApp

# =============================================================================
# ResolutionPipeline Error Handling
# =============================================================================


class TestResolutionPipelineErrors:
    """Tests for type validation on ResolutionPipeline.

    **Validates: Requirements 3.4, 4.5**
    """

    def test_add_provider_with_non_provider_raises_typeerror(self) -> None:
        """add_job_provider raises TypeError when given a non-JobProvider instance.

        **Validates: Requirements 3.4**
        """
        pipeline = ResolutionPipeline()
        with pytest.raises(TypeError, match="Expected a JobProvider instance"):
            pipeline.add_provider("not a provider")  # type: ignore[arg-type]

    def test_add_provider_with_none_raises_typeerror(self) -> None:
        """add_job_provider raises TypeError when given None.

        **Validates: Requirements 3.4**
        """
        pipeline = ResolutionPipeline()
        with pytest.raises(TypeError, match="Expected a JobProvider instance"):
            pipeline.add_provider(None)  # type: ignore[arg-type]

    def test_add_provider_with_plain_object_raises_typeerror(self) -> None:
        """add_job_provider raises TypeError when given a plain object.

        **Validates: Requirements 3.4**
        """
        pipeline = ResolutionPipeline()

        class NotAProvider:
            pass

        with pytest.raises(TypeError, match="Expected a JobProvider instance"):
            pipeline.add_provider(NotAProvider())  # type: ignore[arg-type]

    def test_add_transform_with_non_transform_raises_typeerror(self) -> None:
        """add_job_transform raises TypeError when given a non-JobTransform instance.

        **Validates: Requirements 4.5**
        """
        pipeline = ResolutionPipeline()
        with pytest.raises(TypeError, match="Expected a JobTransform instance"):
            pipeline.add_transform("not a transform")  # type: ignore[arg-type]

    def test_add_transform_with_none_raises_typeerror(self) -> None:
        """add_job_transform raises TypeError when given None.

        **Validates: Requirements 4.5**
        """
        pipeline = ResolutionPipeline()
        with pytest.raises(TypeError, match="Expected a JobTransform instance"):
            pipeline.add_transform(None)  # type: ignore[arg-type]

    def test_add_transform_with_plain_object_raises_typeerror(self) -> None:
        """add_job_transform raises TypeError when given a plain object.

        **Validates: Requirements 4.5**
        """
        pipeline = ResolutionPipeline()

        class NotATransform:
            pass

        with pytest.raises(TypeError, match="Expected a JobTransform instance"):
            pipeline.add_transform(NotATransform())  # type: ignore[arg-type]


# =============================================================================
# NamespaceTransform Error Handling
# =============================================================================


class TestNamespaceTransformErrors:
    """Tests for NamespaceTransform construction validation.

    **Validates: Requirements 9.5**
    """

    def test_empty_prefix_raises_valueerror(self) -> None:
        """NamespaceTransform('') raises ValueError.

        **Validates: Requirements 9.5**
        """
        with pytest.raises(ValueError, match="prefix must be non-empty"):
            NamespaceTransform("")


# =============================================================================
# FunctualizeApp Decorator Error Handling
# =============================================================================


class TestAppDecoratorErrors:
    """Tests for decorator validation on FunctualizeApp.

    **Validates: Requirements 14.4, 16.4, 17.5, 18.5, 28.5**
    """

    @pytest.fixture()
    def app(self) -> FunctualizeApp:
        """Create a minimal FunctualizeApp for testing."""
        return FunctualizeApp(name="testapp")

    def test_on_job_failure_empty_string_raises_valueerror(
        self, app: FunctualizeApp
    ) -> None:
        """@app.on_job_failure('') raises ValueError.

        **Validates: Requirements 14.4**
        """
        with pytest.raises(ValueError, match="non-empty"):
            app.on_job_failure("")

    def test_on_job_teardown_empty_string_raises_valueerror(
        self, app: FunctualizeApp
    ) -> None:
        """@app.on_job_teardown('') raises ValueError.

        **Validates: Requirements 16.4**
        """
        with pytest.raises(ValueError, match="non-empty"):
            app.on_job_teardown("")

    def test_before_job_no_param_function_raises_typeerror(
        self, app: FunctualizeApp
    ) -> None:
        """@app.before_job on a function with no parameters raises TypeError.

        **Validates: Requirements 17.5**
        """
        with pytest.raises(
            TypeError, match="must accept at least one positional parameter"
        ):

            @app.before_job
            def no_params() -> None:
                pass

    def test_run_middleware_non_generator_raises_typeerror(
        self, app: FunctualizeApp
    ) -> None:
        """@app.run_middleware on a non-generator function raises TypeError.

        **Validates: Requirements 18.5**
        """
        with pytest.raises(TypeError, match="generator function"):

            @app.run_middleware
            def not_a_generator(rc: Any) -> None:
                pass

    def test_on_event_invalid_pattern_raises_valueerror(
        self, app: FunctualizeApp
    ) -> None:
        """@app.on_event('invalid!!pattern') raises ValueError.

        **Validates: Requirements 28.5**
        """
        with pytest.raises(ValueError, match="Invalid event pattern"):
            app.on_event("invalid!!pattern")
