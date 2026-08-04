"""Tests for functualize top-level convenience exports (Task 4.1)."""

from __future__ import annotations


class TestTopLevelExports:
    """Top-level functualize imports are accessible and correct."""

    def test_import_functualize_app(self):
        from functualize import FunctualizeApp
        from functualize.app.core import FunctualizeApp as CoreApp

        assert FunctualizeApp is CoreApp

    def test_import_run_context(self):
        from functualize import RunContext
        from functualize.job.context import RunContext as CtxRunContext

        assert RunContext is CtxRunContext

    def test_import_job_config_view(self):
        from functualize import JobConfigView
        from functualize._config.job_config import JobConfigView as CfgJobConfigView

        assert JobConfigView is CfgJobConfigView

    def test_attribute_access_on_module(self):
        import functualize

        assert hasattr(functualize, "FunctualizeApp")
        assert hasattr(functualize, "RunContext")
        assert hasattr(functualize, "JobConfigView")
        assert hasattr(functualize, "__version__")

    def test_version_string(self):
        import functualize

        assert isinstance(functualize.__version__, str)
        assert functualize.__version__
