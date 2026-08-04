"""Startup performance budget tests.

These tests verify that functualize bootstrap phases complete within
acceptable time budgets. When a new feature adds overhead to the boot
sequence, these tests surface the impact immediately.

Budget philosophy:
- Each phase has a maximum allowed duration (the "budget").
- Budgets are generous enough to pass on CI but tight enough to catch
  gross regressions (e.g., accidentally loading a heavy module eagerly).
- Total boot time is tracked as a sum of phases.

To update budgets after intentional changes, run:
    pytest tests/perf/test_startup_budget.py -v

and adjust the constants below based on the new baseline.
"""

from __future__ import annotations

import os
import tempfile

import pytest

# --- Budget constants (milliseconds) ---
# These represent the maximum acceptable time for each phase.
# Adjust after intentional changes to boot sequence.

BUDGET_TOTAL_BOOT_MS = 500.0  # Entire FunctualizeApp.__init__
BUDGET_CORE_INFRA_MS = 50.0  # Object instantiation, no I/O
BUDGET_PROVIDER_REGISTRY_MS = 10.0  # Two format providers registered
BUDGET_OBSERVABILITY_MS = 50.0  # EventBus, MiddlewareStack, SignalBus, catalog
BUDGET_PLUGINS_MS = 200.0  # Entry point discovery (depends on environment)
BUDGET_CONFIG_ENTRY_POINTS_MS = 50.0  # discover_entry_points()
BUDGET_CONFIG_RESOLUTION_MS = 100.0  # ResourceLocator + ResolutionChain build
BUDGET_JOB_REGISTRATION_MS = 50.0  # Command registration (no jobs = fast)
BUDGET_CHILDREN_MS = 50.0  # No children = fast


@pytest.fixture
def boot_report():
    """Bootstrap a FunctualizeApp and return the perf report.

    Uses a temporary directory as config path to avoid file system
    variance from real config files.
    """
    from functualize._app.state import AppState
    from functualize._events.perf import perf_timeline

    # Reset global state for clean measurement
    AppState.reset()
    perf_timeline.reset()

    with tempfile.TemporaryDirectory() as tmp_dir:
        # Set CWD to tmp to avoid picking up real config files
        original_cwd = os.getcwd()
        os.chdir(tmp_dir)
        try:
            from functualize.app.core import FunctualizeApp

            _app = FunctualizeApp(name="perf_test_app")
            report = perf_timeline.report()
        finally:
            os.chdir(original_cwd)
            AppState.reset()

    return report


class TestStartupBudget:
    """Verify each boot phase stays within its time budget."""

    def test_total_boot_time(self, boot_report) -> None:
        """Total boot time stays within budget."""
        phase = boot_report.phase("boot.total")
        assert phase is not None, "boot.total phase not recorded"
        assert phase.duration_ms < BUDGET_TOTAL_BOOT_MS, (
            f"Total boot time {phase.duration_ms:.2f}ms exceeds "
            f"budget of {BUDGET_TOTAL_BOOT_MS}ms"
        )

    def test_core_infra_budget(self, boot_report) -> None:
        """Core infrastructure instantiation stays within budget."""
        phase = boot_report.phase("boot.core_infra")
        assert phase is not None, "boot.core_infra phase not recorded"
        assert phase.duration_ms < BUDGET_CORE_INFRA_MS, (
            f"Core infra {phase.duration_ms:.2f}ms exceeds "
            f"budget of {BUDGET_CORE_INFRA_MS}ms"
        )

    def test_provider_registry_budget(self, boot_report) -> None:
        """Provider registry setup stays within budget."""
        phase = boot_report.phase("boot.provider_registry")
        assert phase is not None, "boot.provider_registry phase not recorded"
        assert phase.duration_ms < BUDGET_PROVIDER_REGISTRY_MS, (
            f"Provider registry {phase.duration_ms:.2f}ms exceeds "
            f"budget of {BUDGET_PROVIDER_REGISTRY_MS}ms"
        )

    def test_observability_budget(self, boot_report) -> None:
        """Observability initialization stays within budget."""
        phase = boot_report.phase("boot.observability")
        assert phase is not None, "boot.observability phase not recorded"
        assert phase.duration_ms < BUDGET_OBSERVABILITY_MS, (
            f"Observability init {phase.duration_ms:.2f}ms exceeds "
            f"budget of {BUDGET_OBSERVABILITY_MS}ms"
        )

    def test_plugins_budget(self, boot_report) -> None:
        """Plugin loading stays within budget."""
        phase = boot_report.phase("boot.plugins")
        assert phase is not None, "boot.plugins phase not recorded"
        assert phase.duration_ms < BUDGET_PLUGINS_MS, (
            f"Plugin loading {phase.duration_ms:.2f}ms exceeds "
            f"budget of {BUDGET_PLUGINS_MS}ms"
        )

    def test_config_entry_points_budget(self, boot_report) -> None:
        """Config entry point discovery stays within budget."""
        phase = boot_report.phase("boot.config_entry_points")
        assert phase is not None, "boot.config_entry_points phase not recorded"
        assert phase.duration_ms < BUDGET_CONFIG_ENTRY_POINTS_MS, (
            f"Config entry points {phase.duration_ms:.2f}ms exceeds "
            f"budget of {BUDGET_CONFIG_ENTRY_POINTS_MS}ms"
        )

    def test_config_resolution_budget(self, boot_report) -> None:
        """Config resolution chain build stays within budget."""
        phase = boot_report.phase("boot.config_resolution")
        assert phase is not None, "boot.config_resolution phase not recorded"
        assert phase.duration_ms < BUDGET_CONFIG_RESOLUTION_MS, (
            f"Config resolution {phase.duration_ms:.2f}ms exceeds "
            f"budget of {BUDGET_CONFIG_RESOLUTION_MS}ms"
        )

    def test_job_registration_budget(self, boot_report) -> None:
        """Job registration stays within budget."""
        phase = boot_report.phase("boot.job_registration")
        assert phase is not None, "boot.job_registration phase not recorded"
        assert phase.duration_ms < BUDGET_JOB_REGISTRATION_MS, (
            f"Job registration {phase.duration_ms:.2f}ms exceeds "
            f"budget of {BUDGET_JOB_REGISTRATION_MS}ms"
        )

    def test_children_budget(self, boot_report) -> None:
        """Child project mounting stays within budget."""
        phase = boot_report.phase("boot.children")
        assert phase is not None, "boot.children phase not recorded"
        assert phase.duration_ms < BUDGET_CHILDREN_MS, (
            f"Children mounting {phase.duration_ms:.2f}ms exceeds "
            f"budget of {BUDGET_CHILDREN_MS}ms"
        )

    def test_tui_budget(self, boot_report) -> None:
        """TUI command registration moved to CliAdapter; verify no phase remains.

        After Phase 5 adapter extraction, TUI initialization is no longer part
        of the kernel boot path. This test now validates that the kernel boot
        does NOT include TUI overhead (confirming successful extraction).
        """
        phase = boot_report.phase("boot.tui")
        # boot.tui should no longer be emitted after adapter extraction
        # TUI registration now happens in CliAdapter.run(), not FunctualizeApp.__init__()
        assert phase is None, (
            "boot.tui phase should not be recorded after adapter extraction — "
            "TUI logic moved to CliAdapter"
        )

    def test_report_summary_available(self, boot_report) -> None:
        """The performance report is human-readable."""
        summary = boot_report.summary()
        assert "Total:" in summary
        # Print for visibility in test output
        print(f"\n--- Startup Performance Report ---\n{summary}")
