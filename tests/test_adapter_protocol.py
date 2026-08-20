"""Unit and property tests for AdapterPlugin Protocol (Task 13.1).

Tests the AdapterPlugin protocol definition, structural typing correctness,
and validate_adapter() TypeError behavior.

# Feature: unified-architecture-redesign, Task 13.1
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize.app.adapters import (
    AdapterPlugin,
    validate_adapter,
)
from functualize.app.adapters._validation import (
    _ADAPTER_REQUIRED_FIELDS,
    _ADAPTER_REQUIRED_METHODS,
    _get_missing_adapter_members,
)

# =============================================================================
# Helpers
# =============================================================================


def _make_class_with_members(
    fields: dict[str, Any] | None = None,
    methods: dict[str, Any] | None = None,
) -> type:
    """Dynamically create a class with the given fields and methods."""
    namespace: dict[str, Any] = {}
    if fields:
        namespace.update(fields)
    if methods:
        namespace.update(methods)
    return type("DynamicAdapter", (), namespace)


def _make_valid_adapter_class() -> type:
    """Create a class that satisfies the full AdapterPlugin protocol."""
    return _make_class_with_members(
        fields={
            "name": "test-adapter",
            "version": "1.0.0",
            "description": "A test adapter",
            "adapter_type": "cli",
        },
        methods={
            "__call__": lambda self, app: None,
            "run": lambda self, *args, **kwargs: None,
            "shutdown": lambda self: None,
        },
    )


class FullAdapter:
    """A concrete adapter class satisfying the full protocol."""

    name = "full-adapter"
    version = "2.0.0"
    description = "Full protocol implementation"
    adapter_type = "http"

    def __call__(self, app: Any) -> None:
        self._app = app

    def run(self, *args: Any, **kwargs: Any) -> Any:
        return None

    def shutdown(self) -> None:
        pass


class LambdaStyleAdapter:
    """A concrete adapter with non-None return from run()."""

    name = "lambda-adapter"
    version = "1.0.0"
    description = "Lambda-style adapter"
    adapter_type = "lambda"

    def __call__(self, app: Any) -> None:
        self._app = app

    def run(self, event: dict, context: Any) -> dict:
        return {"statusCode": 200, "body": "ok"}

    def shutdown(self) -> None:
        pass


# =============================================================================
# Unit Tests: Protocol structural typing
# =============================================================================


class TestAdapterPluginProtocol:
    """Unit tests for AdapterPlugin protocol basic behavior."""

    def test_full_adapter_satisfies_protocol(self):
        """A class with all required fields and methods satisfies the protocol."""
        adapter = FullAdapter()
        assert isinstance(adapter, AdapterPlugin)

    def test_lambda_style_adapter_satisfies_protocol(self):
        """Adapter with typed run() signature still satisfies the protocol."""
        adapter = LambdaStyleAdapter()
        assert isinstance(adapter, AdapterPlugin)

    def test_dynamically_created_valid_adapter_satisfies_protocol(self):
        """Dynamically created class with all members satisfies protocol."""
        cls = _make_valid_adapter_class()
        instance = cls()
        assert isinstance(instance, AdapterPlugin)

    def test_missing_name_fails_protocol(self):
        """Missing 'name' field causes protocol check to fail."""

        class NoName:
            version = "1.0.0"
            description = "test"
            adapter_type = "cli"

            def __call__(self, app):
                pass

            def run(self, *args, **kwargs):
                pass

            def shutdown(self):
                pass

        assert not isinstance(NoName(), AdapterPlugin)

    def test_missing_run_fails_protocol(self):
        """Missing 'run' method causes protocol check to fail."""

        class NoRun:
            name = "test"
            version = "1.0.0"
            description = "test"
            adapter_type = "cli"

            def __call__(self, app):
                pass

            def shutdown(self):
                pass

        assert not isinstance(NoRun(), AdapterPlugin)

    def test_missing_shutdown_fails_protocol(self):
        """Missing 'shutdown' method causes protocol check to fail."""

        class NoShutdown:
            name = "test"
            version = "1.0.0"
            description = "test"
            adapter_type = "cli"

            def __call__(self, app):
                pass

            def run(self, *args, **kwargs):
                pass

        assert not isinstance(NoShutdown(), AdapterPlugin)

    def test_missing_call_fails_protocol(self):
        """Missing '__call__' method causes protocol check to fail."""

        class NoCall:
            name = "test"
            version = "1.0.0"
            description = "test"
            adapter_type = "cli"

            def run(self, *args, **kwargs):
                pass

            def shutdown(self):
                pass

        assert not isinstance(NoCall(), AdapterPlugin)

    def test_empty_class_fails_protocol(self):
        """Empty class fails protocol check."""

        class Empty:
            pass

        assert not isinstance(Empty(), AdapterPlugin)

    def test_no_inheritance_required(self):
        """Protocol is satisfied via structural typing, no inheritance needed."""

        class Standalone:
            name = "standalone"
            version = "0.1.0"
            description = "No inheritance"
            adapter_type = "mcp"

            def __call__(self, app):
                pass

            def run(self, *args, **kwargs):
                return {"result": "ok"}

            def shutdown(self):
                pass

        adapter = Standalone()
        assert isinstance(adapter, AdapterPlugin)
        # Verify it's not inheriting from AdapterPlugin
        assert AdapterPlugin not in type(adapter).__mro__

    def test_protocol_is_runtime_checkable(self):
        """AdapterPlugin is decorated with @runtime_checkable."""
        # If not runtime_checkable, isinstance() would raise TypeError
        # The fact we can call isinstance without error proves it
        assert isinstance(FullAdapter(), AdapterPlugin)

    def test_extra_methods_dont_break_protocol(self):
        """Extra methods beyond protocol requirements don't affect conformance."""

        class ExtendedAdapter:
            name = "extended"
            version = "1.0.0"
            description = "Extended adapter"
            adapter_type = "cli"

            def __call__(self, app):
                pass

            def run(self, *args, **kwargs):
                pass

            def shutdown(self):
                pass

            def custom_method(self):
                return "extra"

            def another_method(self, x: int) -> str:
                return str(x)

        assert isinstance(ExtendedAdapter(), AdapterPlugin)


# =============================================================================
# Unit Tests: validate_adapter()
# =============================================================================


class TestValidateAdapter:
    """Unit tests for validate_adapter() function."""

    def test_valid_adapter_passes_validation(self):
        """validate_adapter does not raise for a conforming object."""
        adapter = FullAdapter()
        # Should not raise
        validate_adapter(adapter)

    def test_invalid_adapter_raises_type_error(self):
        """validate_adapter raises TypeError for non-conforming object."""

        class Invalid:
            pass

        with pytest.raises(TypeError, match="Expected an AdapterPlugin instance"):
            validate_adapter(Invalid())

    def test_type_error_includes_class_name(self):
        """TypeError message includes the class name of the non-conforming object."""

        class MyBadAdapter:
            pass

        with pytest.raises(TypeError, match="MyBadAdapter"):
            validate_adapter(MyBadAdapter())

    def test_type_error_lists_missing_members(self):
        """TypeError message lists which protocol members are missing."""

        class PartialAdapter:
            name = "partial"
            version = "1.0.0"
            # Missing: description, adapter_type, run, shutdown

            def __call__(self, app):
                pass

        with pytest.raises(TypeError, match="Missing methods/attributes:"):
            validate_adapter(PartialAdapter())

    def test_type_error_mentions_specific_missing_field(self):
        """TypeError specifically names the missing field."""

        class MissingDescription:
            name = "test"
            version = "1.0.0"
            adapter_type = "cli"

            def __call__(self, app):
                pass

            def run(self, *args, **kwargs):
                pass

            def shutdown(self):
                pass

        with pytest.raises(TypeError, match="description"):
            validate_adapter(MissingDescription())

    def test_type_error_mentions_missing_method(self):
        """TypeError specifically names the missing method."""

        class MissingShutdown:
            name = "test"
            version = "1.0.0"
            description = "test"
            adapter_type = "cli"

            def __call__(self, app):
                pass

            def run(self, *args, **kwargs):
                pass

        with pytest.raises(TypeError, match="shutdown"):
            validate_adapter(MissingShutdown())

    def test_validate_adapter_with_none_raises(self):
        """validate_adapter raises TypeError for None."""
        with pytest.raises(TypeError):
            validate_adapter(None)

    def test_validate_adapter_with_string_raises(self):
        """validate_adapter raises TypeError for a string."""
        with pytest.raises(TypeError):
            validate_adapter("not an adapter")

    def test_validate_adapter_with_dict_raises(self):
        """validate_adapter raises TypeError for a dict."""
        with pytest.raises(TypeError):
            validate_adapter({"name": "test", "version": "1.0.0"})


# =============================================================================
# Unit Tests: _get_missing_adapter_members()
# =============================================================================


class TestGetMissingAdapterMembers:
    """Unit tests for _get_missing_adapter_members helper."""

    def test_full_adapter_has_no_missing_members(self):
        """A valid adapter has no missing members."""
        adapter = FullAdapter()
        assert _get_missing_adapter_members(adapter) == []

    def test_empty_class_missing_all_members(self):
        """An empty class is missing all required members."""

        class Empty:
            pass

        missing = _get_missing_adapter_members(Empty())
        # Should include all required fields and methods (except __call__ which
        # all objects have technically)
        assert "name" in missing
        assert "version" in missing
        assert "description" in missing
        assert "adapter_type" in missing
        assert "run" in missing
        assert "shutdown" in missing

    def test_partially_complete_class(self):
        """A class with some members lists only the missing ones."""

        class Partial:
            name = "partial"
            adapter_type = "cli"

            def __call__(self, app):
                pass

            def run(self, *args, **kwargs):
                pass

        missing = _get_missing_adapter_members(Partial())
        assert "version" in missing
        assert "description" in missing
        assert "shutdown" in missing
        assert "name" not in missing
        assert "adapter_type" not in missing
        assert "run" not in missing


# =============================================================================
# Property Tests: AdapterPlugin structural typing
# =============================================================================


# Strategies for property tests
_adapter_type_strategy = st.sampled_from(["cli", "http", "lambda", "mcp", "custom"])
_version_strategy = st.from_regex(r"[0-9]+\.[0-9]+\.[0-9]+", fullmatch=True)
_name_strategy = st.from_regex(r"[a-z][a-z0-9\-]{0,20}", fullmatch=True)
_description_strategy = st.text(min_size=1, max_size=100)


class TestAdapterPluginStructuralTypingProperty:
    """Property tests for AdapterPlugin structural typing correctness.

    For any class that defines all required methods/attributes of the
    AdapterPlugin Protocol without inheriting from it, isinstance(instance,
    AdapterPlugin) SHALL return True. For any class missing a required
    member, isinstance SHALL return False.

    **Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5**
    """

    @given(
        has_name=st.booleans(),
        has_version=st.booleans(),
        has_description=st.booleans(),
        has_adapter_type=st.booleans(),
        has_call=st.booleans(),
        has_run=st.booleans(),
        has_shutdown=st.booleans(),
    )
    def test_protocol_satisfaction_requires_all_members(
        self,
        has_name: bool,
        has_version: bool,
        has_description: bool,
        has_adapter_type: bool,
        has_call: bool,
        has_run: bool,
        has_shutdown: bool,
    ):
        """isinstance returns True iff ALL required members are present.

        **Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5**
        """
        fields: dict[str, Any] = {}
        methods: dict[str, Any] = {}

        if has_name:
            fields["name"] = "test-adapter"
        if has_version:
            fields["version"] = "1.0.0"
        if has_description:
            fields["description"] = "Test adapter"
        if has_adapter_type:
            fields["adapter_type"] = "cli"
        if has_call:
            methods["__call__"] = lambda self, app: None
        if has_run:
            methods["run"] = lambda self, *args, **kwargs: None
        if has_shutdown:
            methods["shutdown"] = lambda self: None

        cls = _make_class_with_members(fields, methods)
        instance = cls()

        all_present = (
            has_name
            and has_version
            and has_description
            and has_adapter_type
            and has_call
            and has_run
            and has_shutdown
        )
        assert isinstance(instance, AdapterPlugin) == all_present

    @given(
        name=_name_strategy,
        version=_version_strategy,
        description=_description_strategy,
        adapter_type=_adapter_type_strategy,
    )
    def test_valid_adapters_always_satisfy_protocol(
        self,
        name: str,
        version: str,
        description: str,
        adapter_type: str,
    ):
        """Any class with all members (regardless of field values) satisfies the protocol.

        **Validates: Requirements 10.1, 10.5**
        """
        cls = _make_class_with_members(
            fields={
                "name": name,
                "version": version,
                "description": description,
                "adapter_type": adapter_type,
            },
            methods={
                "__call__": lambda self, app: None,
                "run": lambda self, *args, **kwargs: None,
                "shutdown": lambda self: None,
            },
        )
        instance = cls()
        assert isinstance(instance, AdapterPlugin)

    @given(
        name=_name_strategy,
        version=_version_strategy,
        description=_description_strategy,
        adapter_type=_adapter_type_strategy,
    )
    def test_validate_adapter_does_not_raise_for_valid_instances(
        self,
        name: str,
        version: str,
        description: str,
        adapter_type: str,
    ):
        """validate_adapter() never raises for objects satisfying the protocol.

        **Validates: Requirements 10.5, 10.7**
        """
        cls = _make_class_with_members(
            fields={
                "name": name,
                "version": version,
                "description": description,
                "adapter_type": adapter_type,
            },
            methods={
                "__call__": lambda self, app: None,
                "run": lambda self, *args, **kwargs: None,
                "shutdown": lambda self: None,
            },
        )
        instance = cls()
        # Should not raise
        validate_adapter(instance)

    @given(
        has_name=st.booleans(),
        has_version=st.booleans(),
        has_description=st.booleans(),
        has_adapter_type=st.booleans(),
        has_call=st.booleans(),
        has_run=st.booleans(),
        has_shutdown=st.booleans(),
    )
    def test_validate_adapter_raises_type_error_for_non_conforming(
        self,
        has_name: bool,
        has_version: bool,
        has_description: bool,
        has_adapter_type: bool,
        has_call: bool,
        has_run: bool,
        has_shutdown: bool,
    ):
        """validate_adapter raises TypeError iff any required member is missing.

        **Validates: Requirements 10.7**
        """
        fields: dict[str, Any] = {}
        methods: dict[str, Any] = {}

        if has_name:
            fields["name"] = "test-adapter"
        if has_version:
            fields["version"] = "1.0.0"
        if has_description:
            fields["description"] = "Test adapter"
        if has_adapter_type:
            fields["adapter_type"] = "cli"
        if has_call:
            methods["__call__"] = lambda self, app: None
        if has_run:
            methods["run"] = lambda self, *args, **kwargs: None
        if has_shutdown:
            methods["shutdown"] = lambda self: None

        cls = _make_class_with_members(fields, methods)
        instance = cls()

        all_present = (
            has_name
            and has_version
            and has_description
            and has_adapter_type
            and has_call
            and has_run
            and has_shutdown
        )

        if all_present:
            # Should not raise
            validate_adapter(instance)
        else:
            with pytest.raises(TypeError):
                validate_adapter(instance)

    @given(
        extra_methods=st.lists(
            st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True),
            min_size=0,
            max_size=5,
            unique=True,
        )
    )
    def test_extra_members_do_not_affect_protocol_satisfaction(
        self, extra_methods: list[str]
    ):
        """Extra methods/fields beyond the protocol don't break conformance.

        **Validates: Requirements 10.5**
        """
        fields: dict[str, Any] = {
            "name": "test",
            "version": "1.0.0",
            "description": "test",
            "adapter_type": "cli",
        }
        methods: dict[str, Any] = {
            "__call__": lambda self, app: None,
            "run": lambda self, *args, **kwargs: None,
            "shutdown": lambda self: None,
        }

        # Add extra methods — filter out conflicts with required names
        required_names = set(_ADAPTER_REQUIRED_FIELDS) | set(_ADAPTER_REQUIRED_METHODS)
        for method_name in extra_methods:
            if method_name not in required_names:
                methods[method_name] = lambda self: None

        cls = _make_class_with_members(fields, methods)
        instance = cls()
        assert isinstance(instance, AdapterPlugin)
        validate_adapter(instance)
