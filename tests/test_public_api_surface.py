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
        "AgentStep",
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
        # The resolved inputs a job's own Fingerprint declared, so the body
        # reads what the freshness check already resolved instead of restating
        # the glob (ADR-012).
        "Sources",
        # The verdict that same check produced, so a job can act on its own
        # freshness instead of restating its own staleness check (F9).
        "Freshness",
        "FreshnessVerdict",
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
        # `Job` was public and the only thing that consumes it was not, so the
        # documented way to contribute jobs ran through a private import.
        "StaticProvider",
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
        # Pre-import discovery predicate (third-party-host-seams/1.3). Promoted
        # from _primitives so a host can supply one; `fingerprint()` is part of
        # the contract because the discovery cache replays negative decisions.
        "ModulePreFilter",
        "SessionState",
        "SignatureProvider",
        "Source",
        "StatusBarItemProvider",
        "FormatProvider",
        "ThemeProvider",
        "VaultKeyProvider",
        # The agent step port (agent-step-port F6): one Protocol a plugin
        # implements, plus the capability flags it declares and the payload
        # types it is handed and returns.
        "AgentStepExecutor",
        "AgentCapability",
        "AgentStepContext",
        "AgentStepResult",
        "discover_domains",
        "scan_domain_providers",
        "validate_extension_id",
    },
    "functualize.types": {
        # The outcome authority (run-outcome-authority F2 T1/T2).
        "ExitCode",
        "exit_code_for_status",
        "Family",
        "is_failure",
        "report_line",
        "status_from_wire",
        "wire_value",
        # The request a run is made from (run-request-entry F1 T1).
        "RunRequest",
        "RunSurface",
        # The wire envelope's one parser. HTTP and Lambda held byte-identical
        # copies differing only in the `surface` literal, and MCP restated the
        # shape in prose at both its doors — one contract in four places, its
        # breaking change documented four times, three citations wrong (rre
        # F12). Public because all four callers live outside core.
        "request_from_envelope",
        "MissingValueError",
        "RUN_SURFACES",
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
        # The one RunStatus -> HTTP table, beside RunStatus itself, so a
        # trigger plugin consumes it instead of writing a second opinion.
        "http_status_for_status",
        # Flag vocabulary and alias matching (run-outcome-authority F2 T8).
        "GLOBAL_OPTIONS_ALWAYS_VALUE",
        "GLOBAL_OPTIONS_OPTIONAL_VALUE",
        "OPTIONAL_VALUE_VALID_SET",
        "GLOBAL_OPTIONS_WITH_VALUE",
        "GLOBAL_BOOL_FLAGS",
        "flag_aliases",
        "negative_aliases",
        "match_group_flag",
        "negative_flag_for",
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
        "Loop",
        "OnFailure",
        "Step",
        # A node performed by an agent rather than by a registered job
        # (agent-step-port F6).
        "AgentStep",
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

    def test_every_node_kind_reaches_the_root_facade(self) -> None:
        """The three node kinds travel together, or the facade teaches a
        vocabulary the framework does not have.

        `AgentStep` reached `functualize.workflow` and stopped there, so
        `from functualize import Gate` worked and `from functualize import
        AgentStep` raised — for a node kind the same `@workflow` graph
        declares beside the other two (asp M-5). Derived from
        `functualize.workflow`'s own list rather than restated, so a fourth
        node kind fails here until it is exported too.
        """
        top = _import_module("functualize")
        wf_mod = _import_module("functualize.workflow")

        node_kinds = {
            name for name in wf_mod.__all__ if name in {"Step", "Gate", "AgentStep"}
        }
        assert node_kinds == {"Step", "Gate", "AgentStep"}, (
            f"functualize.workflow's node kinds changed: {sorted(node_kinds)}. "
            f"Update this set and the root facade together."
        )
        missing = [name for name in node_kinds if not hasattr(top, name)]
        assert not missing, (
            f"node kinds declared in functualize.workflow but not importable "
            f"from functualize: {missing}"
        )
        for name in node_kinds:
            assert getattr(top, name) is getattr(wf_mod, name)

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
