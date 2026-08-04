"""Unit tests for AppState class."""

import threading

import pytest

from functualize._app.state import AppState


@pytest.fixture(autouse=True)
def _reset_state():
    """Ensure AppState is clean before and after each test."""
    AppState.reset()
    yield
    AppState.reset()


class TestAppStateGetSet:
    """Tests for basic get/set operations."""

    def test_get_unset_key_returns_none(self):
        assert AppState.get("nonexistent") is None

    def test_set_and_get_string(self):
        AppState.set("config_directory", "/some/path")
        assert AppState.get("config_directory") == "/some/path"

    def test_set_and_get_none_value(self):
        AppState.set("dotenv_path", None)
        assert AppState.get("dotenv_path") is None

    def test_set_overwrites_previous_value(self):
        AppState.set("environment", "DEV")
        AppState.set("environment", "PROD")
        assert AppState.get("environment") == "PROD"

    def test_set_and_get_various_types(self):
        AppState.set("int_val", 42)
        AppState.set("list_val", [1, 2, 3])
        AppState.set("dict_val", {"a": 1})
        assert AppState.get("int_val") == 42
        assert AppState.get("list_val") == [1, 2, 3]
        assert AppState.get("dict_val") == {"a": 1}


class TestAppStateReset:
    """Tests for reset behavior."""

    def test_reset_clears_all_keys(self):
        AppState.set("config_directory", "/path")
        AppState.set("environment", "DEV")
        AppState.reset()
        assert AppState.get("config_directory") is None
        assert AppState.get("environment") is None

    def test_reset_on_empty_state_does_not_raise(self):
        AppState.reset()  # Should not raise


class TestAppStateThreadSafety:
    """Tests for thread-safe concurrent access."""

    def test_concurrent_set_and_get(self):
        errors: list[Exception] = []
        barrier = threading.Barrier(10)

        def writer(key: str, value: str):
            try:
                barrier.wait()
                for _ in range(100):
                    AppState.set(key, value)
            except Exception as e:
                errors.append(e)

        def reader(key: str):
            try:
                barrier.wait()
                for _ in range(100):
                    result = AppState.get(key)
                    # Result should be None or a string previously set
                    assert result is None or isinstance(result, str)
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(5):
            threads.append(
                threading.Thread(target=writer, args=(f"key_{i}", f"val_{i}"))
            )
            threads.append(threading.Thread(target=reader, args=(f"key_{i}",)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []

    def test_concurrent_reset_does_not_corrupt(self):
        errors: list[Exception] = []
        barrier = threading.Barrier(4)

        def setter():
            try:
                barrier.wait()
                for i in range(100):
                    AppState.set(f"key_{i}", f"value_{i}")
            except Exception as e:
                errors.append(e)

        def resetter():
            try:
                barrier.wait()
                for _ in range(50):
                    AppState.reset()
            except Exception as e:
                errors.append(e)

        def getter():
            try:
                barrier.wait()
                for i in range(100):
                    AppState.get(f"key_{i}")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=setter),
            threading.Thread(target=setter),
            threading.Thread(target=resetter),
            threading.Thread(target=getter),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
