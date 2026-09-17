"""Unit tests for functualize-tasks-local plugin.

Tests the local task runner implementation.
"""

from __future__ import annotations


class TestImports:
    """Verify the plugin is importable."""

    def test_import_package(self):
        import functualize_tasks_local

        assert dir(functualize_tasks_local)


class TestItRegistersThroughTheHooksFacade:
    """`__call__` had no test at all — `plugin-host-protocol`/T6.

    T6's reachability gate said breaking `make_on_ready_decorator`'s
    registration would fail "all four plugin suites". Measured, it failed one:
    `functualize-mcp`, whose commands stop appearing. This suite and
    `functualize-state-sqlite`'s passed, because neither had a test that ever
    called the plugin — `LocalTasksPlugin` was reached only through
    `_on_app_ready` in other people's fixtures, never through the registration
    that puts `_on_app_ready` on the hook.

    So the one line T6 changed here was, until now, covered by nothing.
    """

    def test_it_asks_for_on_ready_and_hands_over_its_handler(self):
        from functualize_tasks_local import LocalTasksPlugin

        handed = []

        class _Hooks:
            def on_ready(self, handler):
                handed.append(handler)
                return handler

        class _App:
            hooks = _Hooks()

        plugin = LocalTasksPlugin()
        plugin(_App())

        assert handed == [plugin._on_app_ready]

    def test_registering_does_not_build_the_provider(self):
        """Registration is not initialisation, and the split is the point.

        The provider needs the app's substrate, which a storage plugin may
        still install at its own `APP_READY`. Building it during `__call__`
        would read the substrate before that could happen.
        """
        from functualize_tasks_local import LocalTasksPlugin

        class _App:
            class hooks:  # noqa: N801
                @staticmethod
                def on_ready(handler):
                    return handler

        plugin = LocalTasksPlugin()
        plugin(_App())

        assert plugin.provider is None
