"""Public API surface stability tests.

Verifies that all 7 public packages (functualize, functualize.app,
functualize.job, functualize.plugin, functualize.types, functualize.workflow,
functualize.testing) maintain correct, importable, and stable __all__ exports.

Maintenance contract:
    When a developer adds or removes a symbol from a public package's __all__,
    they must update EXPECTED_EXPORTS below. Test failure messages guide this
    explicitly.

Requirements: 2.1, 3.3, 6.1
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest  # noqa: F401 — used by test classes added in subsequent tasks

EXPECTED_EXPORTS: dict[str, set[str]] = {
    "functualize": {
        "FunctualizeApp",
        "JobConfigView",
        "RunContext",
        "__version__",
        "workflow",
        "Step",
        "Gate",
        "Edge",
        "ConditionalEdge",
        "END",
        "GateStrategy",
        "GateResolver",
        "GateContext",
    },
    "functualize.app": {
        "FunctualizeApp",
        "FallbackCommand",
        "DiscoveryConfig",
        "JobSources",
        "ConfigSources",
        "PluginSources",
        "ExecutionConfig",
        "classic",
        "twelve_factor",
        "env_only",
        "remote_first",
        "get_perf_timeline",
    },
    "functualize.job": {
        "RunContext",
        # Callers compare `result.status` against this — notably
        # RunStatus.BLOCKED, which a gated workflow returns.
        "RunStatus",
        # A parameter annotated FromJob[x] is both the dependency edge and
        # the injection of x's return value (S8).
        "FromJob",
        "Log",
        "Invoke",
        "Prompt",
        "Perf",
        "State",
        "JobContext",
        "JobConfigView",
        "TTY",
        "Live",
        "TerminalUnavailable",
        "Shell",
        "ShellError",
        "ShellResult",
        "Stdout",
        "Responder",
        "FailingResponder",
        "job",
        "suppress_live",
        "surface_hint",
        "Arg",
        "Option",
        "Stdin",
        # Per-group declared flags (S6a). Lazily materialized via the module
        # __getattr__ hook — see functualize/job/__init__.py.
        "GroupOptions",
        # @job declaration model (S1)
        "JobDeclaration",
        "Deps",
        "Fingerprint",
        "Guards",
        "Exec",
        "Retry",
        "Precondition",
        "Call",
        "call",
        "_make_global_only_decorator",
        "_make_hook_decorator",
        "_make_middleware_decorator",
    },
    "functualize.plugin": {
        "BarRenderer",
        "DisplayProvider",
        "InteractiveContent",
        "EventBus",
        "HeaderItemProvider",
        "HookEvent",
        "StructuredEvent",
        "JobProvider",
        "JobTransform",
        "Job",
        "AdapterPlugin",
        "PromptCollector",
        "Surface",
        "LiveConstruct",
        # Shell command tree (convergence C1.1) — the protocols a provider
        # implements so jobs and builtins compose into one tree.
        "CommandNode",
        "CommandProvider",
        # Input-mode registry (convergence C1b.1) — sigil-dispatched bar modes.
        "DEFAULT_SIGIL",
        "InputMode",
        "InputModeRegistry",
        # App-parameterized settings declaration (convergence C2.1).
        "AppSettingsSchema",
        "Setting",
        "SettingsSources",
        "PanelProvider",
        "PostRunStampProvider",
        "PromptRequest",
        "PromptResponse",
        "PromptIntent",
        "PromptSeverity",
        "PromptChoice",
        "PluginMetadata",
        "PluginWithShutdown",
        "SessionState",
        "SignatureProvider",
        "Source",
        "StatusBarItemProvider",
        "FormatProvider",
        "ThemeProvider",
        "discover_domains",
        "scan_domain_providers",
        "validate_extension_id",
    },
    "functualize.types": {
        "JobResult",
        "JobDescriptor",
        "FieldDescriptor",
        "RunStatus",
        "RunType",
        "JobPhase",
        "CacheInfo",
        "ConfigFileInfo",
        "ConfigFileRole",
        "EnvironmentSource",
        "Secret",
    },
    "functualize.workflow": {
        # A gate offers jobs; Tool narrows which of their arguments the
        # resolving agent may set.
        "Tool",
        "workflow",
        "ConditionalEdge",
        "Edge",
        "END",
        "FromStep",
        "Gate",
        "Step",
        "_EndSentinel",
    },
    "functualize.testing": {
        "AutoPrompt",
        "CapturingLog",
        "FakeShell",
        "FakeShellCall",
        "FakeStdout",
        "MockInvoke",
        "NoopPerf",
        "TestRunContext",
    },
}

KNOWN_PRIVATE_DEVIATIONS: dict[str, set[str]] = {
    "functualize.job": {
        "_make_global_only_decorator",
        "_make_hook_decorator",
        "_make_middleware_decorator",
    },
    "functualize.workflow": {
        "_EndSentinel",
    },
}


def _import_module(module_path: str) -> Any:
    """Import and return a module by dotted path."""
    return importlib.import_module(module_path)


class TestAllExportsAreImportable:
    """Verify every name in __all__ exists as an attribute on the module.

    Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5
    """

    @pytest.mark.parametrize("module_path", sorted(EXPECTED_EXPORTS.keys()))
    def test_all_names_resolve(self, module_path: str) -> None:
        mod = _import_module(module_path)

        assert hasattr(mod, "__all__"), f"{module_path}: module does not define __all__"

        missing = [name for name in mod.__all__ if not hasattr(mod, name)]

        assert not missing, (
            f"{module_path}: names in __all__ not found as module attributes: "
            f"{sorted(missing)}"
        )


class TestModuleImportability:
    """Verify all 7 public packages import without error.

    Requirements: 4.1, 4.2, 4.3, 4.4
    """

    @pytest.mark.parametrize("module_path", sorted(EXPECTED_EXPORTS.keys()))
    def test_import_succeeds(self, module_path: str) -> None:
        """Each public package must import successfully via importlib."""
        mod = _import_module(module_path)
        assert mod is not None, f"{module_path} imported as None"


class TestAllMatchesExpected:
    """Snapshot-based regression detection for additions and removals.

    Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5
    """

    @pytest.mark.parametrize("module_path", sorted(EXPECTED_EXPORTS.keys()))
    def test_no_unexpected_additions(self, module_path: str) -> None:
        """actual - expected must be empty; new symbols need explicit registration."""
        mod = _import_module(module_path)
        actual = set(mod.__all__)
        expected = EXPECTED_EXPORTS[module_path]
        extras = sorted(actual - expected)

        assert not extras, (
            f"{module_path}: unexpected additions to __all__: {extras}. "
            f"If intentional, add to EXPECTED_EXPORTS in "
            f"tests/test_public_api_surface.py."
        )

    @pytest.mark.parametrize("module_path", sorted(EXPECTED_EXPORTS.keys()))
    def test_no_unexpected_removals(self, module_path: str) -> None:
        """expected - actual must be empty; removals are breaking changes."""
        mod = _import_module(module_path)
        actual = set(mod.__all__)
        expected = EXPECTED_EXPORTS[module_path]
        missing = sorted(expected - actual)

        assert not missing, (
            f"BREAKING CHANGE in {module_path}: "
            f"expected names missing from __all__: {missing}"
        )


class TestNoPrivateSymbolsInPublicAll:
    """Detect underscore-prefixed names in __all__ (API hygiene).

    Validates: Requirements 3.1, 3.2, 3.3, 3.4
    """

    @pytest.mark.parametrize("module_path", sorted(EXPECTED_EXPORTS.keys()))
    def test_no_new_private_symbols(self, module_path: str) -> None:
        """Private names minus known deviations must be empty."""
        mod = _import_module(module_path)
        actual = set(mod.__all__)

        private_symbols = {
            name
            for name in actual
            if name.startswith("_") and not name.startswith("__")
        }
        new_privates = private_symbols - KNOWN_PRIVATE_DEVIATIONS.get(
            module_path, set()
        )

        assert not new_privates, (
            f"{module_path}: new private symbols found in __all__: "
            f"{sorted(new_privates)}. "
            f"Do not add private names to public __all__ unless the deviation "
            f"is explicitly registered in KNOWN_PRIVATE_DEVIATIONS."
        )

    @pytest.mark.parametrize(
        ("module_path", "expected_privates"),
        sorted(KNOWN_PRIVATE_DEVIATIONS.items()),
    )
    def test_known_deviations_still_exist(
        self, module_path: str, expected_privates: set[str]
    ) -> None:
        """Skip with informational message if deviations were cleaned up."""
        mod = _import_module(module_path)
        actual = set(mod.__all__)

        cleaned_up = expected_privates - actual
        if cleaned_up:
            pytest.skip(
                f"{module_path}: known private deviations were cleaned up: "
                f"{sorted(cleaned_up)}. "
                f"Consider removing this entry from KNOWN_PRIVATE_DEVIATIONS."
            )


class TestCrossPackageConsistency:
    """Verify re-exported symbols are the same Python objects across import paths.

    Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5
    """

    def test_functualize_app_is_same_as_app_module(self) -> None:
        """functualize.FunctualizeApp is functualize.app.FunctualizeApp."""
        top = _import_module("functualize")
        app_mod = _import_module("functualize.app")

        assert top.FunctualizeApp is app_mod.FunctualizeApp

    def test_functualize_runcontext_is_same_as_job_module(self) -> None:
        """functualize.RunContext is functualize.job.RunContext."""
        top = _import_module("functualize")
        job_mod = _import_module("functualize.job")

        assert top.RunContext is job_mod.RunContext

    def test_functualize_workflow_symbols_match(self) -> None:
        """workflow, Step, Edge, ConditionalEdge, END identity with functualize.workflow."""
        top = _import_module("functualize")
        wf_mod = _import_module("functualize.workflow")

        assert top.workflow is wf_mod.workflow
        assert top.Step is wf_mod.Step
        assert top.Edge is wf_mod.Edge
        assert top.ConditionalEdge is wf_mod.ConditionalEdge
        assert top.END is wf_mod.END

    def test_functualize_gate_symbols_match(self) -> None:
        """GateStrategy, GateResolver, GateContext identity with functualize._gate."""
        top = _import_module("functualize")
        gate_mod = _import_module("functualize._gate")

        assert top.GateStrategy is gate_mod.GateStrategy
        assert top.GateResolver is gate_mod.GateResolver
        assert top.GateContext is gate_mod.GateContext

    def test_session_overlay_source_removed(self) -> None:
        """SessionOverlaySource is no longer importable."""
        import pytest

        with pytest.raises(ImportError):
            from functualize.app import SessionOverlaySource  # noqa: F401
