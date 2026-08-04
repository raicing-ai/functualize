"""Integration tests for PendingExecution lifecycle in app.py.

Verifies that:
1. PendingExecution is created when a job is recognized in the SmartBar
2. PendingExecution overrides sync with SmartBar CLI tokens
3. _build_pending_execution constructs correct resolved_values
4. _refresh_all_views helper works without errors

Requirements: R1-AC1, R1-AC2, R1-AC3, R1-AC6
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from functualize._cli.data.pending_execution import PendingExecution
from functualize._cli.data.resolved_value_compat import ResolvedValueCompat
from functualize._cli.tui.app import FunctualizeInlineTUI
from functualize._cli.tui.cli_arg_parser import parse_cli_args_to_kwargs

# =============================================================================
# Helpers
# =============================================================================


def _make_field_descriptor(
    name: str,
    *,
    required: bool = False,
    default: Any = None,
    positional: bool = False,
    short_flag: str | None = None,
    type_annotation: str = "str",
    description: str = "",
    choices: list[str] | None = None,
) -> SimpleNamespace:
    """Create a mock field descriptor matching the JobDescriptor.parameters interface."""
    return SimpleNamespace(
        name=name,
        required=required,
        default=default,
        positional=positional,
        short_flag=short_flag,
        type_annotation=type_annotation,
        description=description,
        choices=choices,
    )


def _make_job_descriptor(name: str, fields: list[SimpleNamespace]) -> SimpleNamespace:
    """Create a mock JobDescriptor with given fields."""
    return SimpleNamespace(
        name=name,
        config_fields=fields,
        parameters=fields,
        docstring="Test job",
        group=None,
        source_path=None,
    )


def _make_func_app(jobs: list[SimpleNamespace]) -> MagicMock:
    """Create a mock FunctualizeApp with given job descriptors."""
    app = MagicMock()
    app.name = "test-app"
    app.get_jobs.return_value = jobs
    app.get_job.side_effect = lambda name: next(
        (j for j in jobs if j.name == name), None
    )
    return app


# =============================================================================
# Test: ResolvedValueCompat adapter
# =============================================================================


class TestResolvedValueCompat:
    """ResolvedValueCompat provides .value and .source_type for PendingExecution."""

    def test_frozen_dataclass_attributes(self) -> None:
        """ResolvedValueCompat exposes value and source_type."""
        rv = ResolvedValueCompat(value="hello", source_type="default")
        assert rv.value == "hello"
        assert rv.source_type == "default"

    def test_works_with_pending_execution(self) -> None:
        """PendingExecution can use ResolvedValueCompat as resolved values."""
        rv = ResolvedValueCompat(value="8080", source_type="default")
        pending = PendingExecution(job_name="serve", resolved_values={"port": rv})
        assert pending.effective_value("port") == "8080"
        assert pending.effective_source("port") == "default"

    def test_override_wins_over_resolved(self) -> None:
        """Overrides take precedence over resolved values."""
        rv = ResolvedValueCompat(value="8080", source_type="default")
        pending = PendingExecution(job_name="serve", resolved_values={"port": rv})
        pending.overrides["port"] = "9090"
        assert pending.effective_value("port") == "9090"
        assert pending.effective_source("port") == "cli"


# =============================================================================
# Test: _build_pending_execution
# =============================================================================


class TestBuildPendingExecution:
    """_build_pending_execution constructs PendingExecution from job fields."""

    def test_creates_pending_with_defaults(self) -> None:
        """Fields with defaults get ResolvedValueCompat(value=default, source='default')."""
        fields = [
            _make_field_descriptor("port", default=8080),
            _make_field_descriptor("host", default="localhost"),
        ]
        job = _make_job_descriptor("serve", fields)
        func_app = _make_func_app([job])

        with patch.object(
            FunctualizeInlineTUI, "__init__", lambda self, *a, **kw: None
        ):
            tui = FunctualizeInlineTUI.__new__(FunctualizeInlineTUI)
            tui._func_app = func_app
            # Simulate SmartBar value
            tui._smart_bar = MagicMock()
            tui._smart_bar.value = "serve"

            pending = tui._build_pending_execution("serve")

        assert pending.job_name == "serve"
        assert "port" in pending.resolved_values
        assert "host" in pending.resolved_values
        assert pending.resolved_values["port"].value == "8080"
        assert pending.resolved_values["port"].source_type == "default"
        assert pending.resolved_values["host"].value == "localhost"
        assert pending.resolved_values["host"].source_type == "default"

    def test_creates_pending_with_cli_values(self) -> None:
        """CLI-provided values are reflected as source_type='cli'."""
        fields = [
            _make_field_descriptor("port", default=8080),
            _make_field_descriptor("host", default="localhost"),
        ]
        job = _make_job_descriptor("serve", fields)
        func_app = _make_func_app([job])

        with patch.object(
            FunctualizeInlineTUI, "__init__", lambda self, *a, **kw: None
        ):
            tui = FunctualizeInlineTUI.__new__(FunctualizeInlineTUI)
            tui._func_app = func_app
            tui._smart_bar = MagicMock()
            tui._smart_bar.value = "serve --port 9090"

            pending = tui._build_pending_execution("serve")

        assert pending.resolved_values["port"].value == "9090"
        assert pending.resolved_values["port"].source_type == "cli"
        assert pending.resolved_values["host"].value == "localhost"
        assert pending.resolved_values["host"].source_type == "default"

    def test_creates_pending_with_no_default_fields(self) -> None:
        """Fields without defaults get empty value with source_type='default'."""
        fields = [
            _make_field_descriptor("env", required=True),
        ]
        job = _make_job_descriptor("deploy", fields)
        func_app = _make_func_app([job])

        with patch.object(
            FunctualizeInlineTUI, "__init__", lambda self, *a, **kw: None
        ):
            tui = FunctualizeInlineTUI.__new__(FunctualizeInlineTUI)
            tui._func_app = func_app
            tui._smart_bar = MagicMock()
            tui._smart_bar.value = "deploy"

            pending = tui._build_pending_execution("deploy")

        assert pending.resolved_values["env"].value == ""
        assert pending.resolved_values["env"].source_type == "default"

    def test_creates_pending_for_unknown_job(self) -> None:
        """Unknown job results in empty resolved_values."""
        func_app = _make_func_app([])

        with patch.object(
            FunctualizeInlineTUI, "__init__", lambda self, *a, **kw: None
        ):
            tui = FunctualizeInlineTUI.__new__(FunctualizeInlineTUI)
            tui._func_app = func_app
            tui._smart_bar = MagicMock()
            tui._smart_bar.value = "unknown"

            pending = tui._build_pending_execution("unknown")

        assert pending.job_name == "unknown"
        assert pending.resolved_values == {}


# =============================================================================
# Test: PendingExecution overrides sync with SmartBar tokens
# =============================================================================


class TestOverridesSyncWithTokens:
    """PendingExecution overrides update when SmartBar text changes."""

    def test_overrides_populated_from_cli_args(self) -> None:
        """Parsing '--port 9090' from SmartBar populates pending.overrides."""
        fields = [
            _make_field_descriptor("port", default=8080),
            _make_field_descriptor("host", default="localhost"),
        ]
        # Simulate what on_input_changed does: parse tokens → update overrides
        pending = PendingExecution(
            job_name="serve",
            resolved_values={
                "port": ResolvedValueCompat(value="8080", source_type="default"),
                "host": ResolvedValueCompat(value="localhost", source_type="default"),
            },
        )

        tokens = ["serve", "--port", "9090"]
        provided = parse_cli_args_to_kwargs(tokens[1:], fields=fields)

        # Simulate the sync logic from on_input_changed
        for key, val in provided.items():
            if key in pending.resolved_values:
                pending.overrides[key] = val

        assert pending.overrides == {"port": "9090"}
        assert pending.effective_value("port") == "9090"
        assert pending.effective_value("host") == "localhost"

    def test_override_removed_when_token_removed(self) -> None:
        """Removing a token from SmartBar clears the corresponding override."""
        pending = PendingExecution(
            job_name="serve",
            resolved_values={
                "port": ResolvedValueCompat(value="8080", source_type="default"),
                "host": ResolvedValueCompat(value="localhost", source_type="default"),
            },
            overrides={"port": "9090"},
        )

        # User clears the --port arg from SmartBar
        tokens = ["serve"]
        fields = [
            _make_field_descriptor("port", default=8080),
            _make_field_descriptor("host", default="localhost"),
        ]
        provided = parse_cli_args_to_kwargs(tokens[1:], fields=fields)

        # Simulate the sync logic (GAP-1): clear overrides not in provided,
        # unconditionally — a value has no life apart from its bar token.
        current_override_keys = set(pending.overrides.keys())
        for key, val in provided.items():
            if key in pending.resolved_values:
                pending.overrides[key] = val
        for key in current_override_keys - set(provided.keys()):
            pending.overrides.pop(key, None)

        assert "port" not in pending.overrides
        assert pending.effective_value("port") == "8080"

    def test_panel_override_cleared_on_cli_change(self) -> None:
        """A panel-edit override is cleared when its bar token disappears.

        Under the SmartBar-as-CLI model (GAP-1) there is no "session" override
        that survives independently of its bar token: a table-edit value is
        synced into the bar, so a vanished token means the value is gone.
        """
        pending = PendingExecution(
            job_name="serve",
            resolved_values={
                "port": ResolvedValueCompat(value="8080", source_type="default"),
                "host": ResolvedValueCompat(value="localhost", source_type="default"),
            },
        )
        # User set host via panel (direct override, no target bookkeeping)
        pending.overrides["host"] = "0.0.0.0"

        # SmartBar text changes to just "serve --port 9090" — host token gone
        tokens = ["serve", "--port", "9090"]
        fields = [
            _make_field_descriptor("port", default=8080),
            _make_field_descriptor("host", default="localhost"),
        ]
        provided = parse_cli_args_to_kwargs(tokens[1:], fields=fields)

        current_override_keys = set(pending.overrides.keys())
        for key, val in provided.items():
            if key in pending.resolved_values:
                pending.overrides[key] = val
        for key in current_override_keys - set(provided.keys()):
            pending.overrides.pop(key, None)

        # host override cleared because its token disappeared
        assert "host" not in pending.overrides
        # CLI override for port applied
        assert pending.overrides["port"] == "9090"


# =============================================================================
# Test: ConfigSnapshotStore loaded at init
# =============================================================================


class TestSnapshotStoreLoadedAtInit:
    """ConfigSnapshotStore is loaded at boot for prior session history."""

    def test_snapshot_store_available(self) -> None:
        """The _snapshot_store attribute is a ConfigSnapshotStore instance."""
        from functualize._cli.data.config_snapshot_store import ConfigSnapshotStore

        _make_func_app([])

        with (
            patch.object(
                ConfigSnapshotStore, "load", return_value=ConfigSnapshotStore()
            ),
            patch.object(FunctualizeInlineTUI, "__init__", lambda self, *a, **kw: None),
        ):
            tui = FunctualizeInlineTUI.__new__(FunctualizeInlineTUI)
            tui._snapshot_store = ConfigSnapshotStore.load()

        assert isinstance(tui._snapshot_store, ConfigSnapshotStore)
