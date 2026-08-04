"""Unit tests for signature introspection utilities."""

from __future__ import annotations

from functualize._events.introspection import (
    accepts_keyword,
    filter_kwargs_for_callable,
)


class TestAcceptsKeyword:
    """Tests for accepts_keyword function."""

    def test_positional_or_keyword_param_accepted(self) -> None:
        def hook(rc, result=None):
            pass

        assert accepts_keyword(hook, "result") is True

    def test_keyword_only_param_accepted(self) -> None:
        def hook(rc, *, result):
            pass

        assert accepts_keyword(hook, "result") is True

    def test_var_keyword_accepts_anything(self) -> None:
        def hook(rc, **kwargs):
            pass

        assert accepts_keyword(hook, "result") is True
        assert accepts_keyword(hook, "kwargs") is True
        assert accepts_keyword(hook, "anything") is True

    def test_missing_param_rejected(self) -> None:
        def hook(rc):
            pass

        assert accepts_keyword(hook, "result") is False

    def test_positional_only_param_rejected(self) -> None:
        # Positional-only params cannot be passed as keyword args
        def hook(rc, result, /):
            pass

        assert accepts_keyword(hook, "result") is False

    def test_var_positional_does_not_accept_keyword(self) -> None:
        def hook(rc, *args):
            pass

        assert accepts_keyword(hook, "result") is False

    def test_uninspectable_callable_returns_false(self) -> None:
        # Built-in functions that can't be inspected
        assert accepts_keyword(print, "nonexistent_kwarg") is False

    def test_lambda_with_param(self) -> None:
        hook = lambda rc, result: None  # noqa: E731
        assert accepts_keyword(hook, "result") is True

    def test_lambda_without_param(self) -> None:
        hook = lambda rc: None  # noqa: E731
        assert accepts_keyword(hook, "result") is False

    def test_class_method(self) -> None:
        class MyPlugin:
            def on_success(self, rc, result=None):
                pass

        plugin = MyPlugin()
        assert accepts_keyword(plugin.on_success, "result") is True

    def test_class_method_without_param(self) -> None:
        class MyPlugin:
            def on_success(self, rc):
                pass

        plugin = MyPlugin()
        assert accepts_keyword(plugin.on_success, "result") is False


class TestFilterKwargsForCallable:
    """Tests for filter_kwargs_for_callable function."""

    def test_filters_to_accepted_keys(self) -> None:
        def hook(rc, result=None):
            pass

        filtered = filter_kwargs_for_callable(hook, {"result": 42, "extra": "nope"})
        assert filtered == {"result": 42}

    def test_var_keyword_accepts_all(self) -> None:
        def hook(rc, **kwargs):
            pass

        kwargs = {"result": 42, "extra": "yes", "another": True}
        filtered = filter_kwargs_for_callable(hook, kwargs)
        assert filtered == kwargs

    def test_empty_kwargs_returns_empty(self) -> None:
        def hook(rc):
            pass

        assert filter_kwargs_for_callable(hook, {}) == {}

    def test_no_matching_keys_returns_empty(self) -> None:
        def hook(rc):
            pass

        assert filter_kwargs_for_callable(hook, {"result": 42, "kwargs": {}}) == {}
