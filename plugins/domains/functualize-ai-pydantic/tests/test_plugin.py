"""Unit tests for functualize-ai-pydantic plugin.

Tests Pydantic model integration with the AI capability layer.
"""

from __future__ import annotations


class TestImports:
    """Verify the plugin is importable."""

    def test_import_package(self):
        import functualize_ai_pydantic

        assert dir(functualize_ai_pydantic)


class TestStateNamespace:
    """`_resolve_state_namespace` had no coverage, and needed some.

    It used to import `StateBackend` from the retired `functualize-state`
    domain and reach past the facades into the app's private DI registry,
    behind `except (ImportError, Exception)`. The import always raised, so the
    backend handed on was always `None` — but T2's sabotage showed that
    breaking `resolve_ai_state_backend` outright left every AI test green, so
    nothing here was proven either way.
    """

    def test_resolves_an_ephemeral_backend_without_reading_the_app(self):
        from functualize_ai._state_fallback import EphemeralStateBackend
        from functualize_ai_pydantic._plugin import PydanticAIPlugin

        class HostileApp:
            """Raises on any attribute access — this helper reads none."""

            def __getattr__(self, name):
                raise AssertionError(
                    f"_resolve_state_namespace must not read app.{name}"
                )

        backend = PydanticAIPlugin()._resolve_state_namespace(HostileApp())

        assert isinstance(backend, EphemeralStateBackend)

    def test_the_backend_it_returns_actually_stores(self):
        from functualize_ai_pydantic._plugin import PydanticAIPlugin

        backend = PydanticAIPlugin()._resolve_state_namespace(object())

        backend.set("budget.spent", 3)
        assert backend.get("budget.spent") == 3
