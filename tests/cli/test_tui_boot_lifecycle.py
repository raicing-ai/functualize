"""Integration tests for boot/shutdown lifecycle components.

# Feature: tui-foundation, Task 6.2

Tests the TUI boot/shutdown sequence at the component level:
- ArgumentHistory loads from disk on boot and flushes on shutdown

These are unit-level integration tests that verify the components work
together in the boot sequence without actually starting the Textual TUI.

Requirements: 1.5, 1.7, 2.2
"""

from __future__ import annotations

import json
from pathlib import Path

from functualize._cli.data.argument_history import ArgumentHistory

# =============================================================================
# Test 1: ArgumentHistory loads from disk at boot
# =============================================================================


class TestArgumentHistoryLoadsOnBoot:
    """ArgumentHistory loads existing data from disk when the TUI boots.

    **Validates: Requirement 1.5**
    """

    def test_load_reads_existing_history(self, tmp_path: Path):
        """Loading from a file with known data restores that data."""
        history_file = tmp_path / "argument_history.json"
        seed_data = {
            "version": 1,
            "history": {
                "deploy": {
                    "environment": ["staging", "production"],
                    "region": ["us-east-1"],
                }
            },
        }
        history_file.write_text(json.dumps(seed_data), encoding="utf-8")

        history = ArgumentHistory.load(path=history_file)

        assert history.get_history("deploy", "environment") == [
            "production",
            "staging",
        ]
        assert history.get_history("deploy", "region") == ["us-east-1"]

    def test_load_then_record_then_flush_updates_file(self, tmp_path: Path):
        """Recording new values after load and flushing updates the file."""
        history_file = tmp_path / "argument_history.json"
        seed_data = {
            "version": 1,
            "history": {"build": {"target": ["debug"]}},
        }
        history_file.write_text(json.dumps(seed_data), encoding="utf-8")

        history = ArgumentHistory.load(path=history_file)
        history.record("build", "target", "release")
        history.flush()

        updated = json.loads(history_file.read_text(encoding="utf-8"))
        assert updated["history"]["build"]["target"] == ["debug", "release"]


# =============================================================================
# Test 2: ArgumentHistory flush on shutdown
# =============================================================================


class TestArgumentHistoryFlushOnShutdown:
    """ArgumentHistory flushes pending changes to disk on TUI shutdown.

    **Validates: Requirement 1.7**
    """

    def test_flush_persists_recorded_values(self, tmp_path: Path):
        """After recording values, flush() writes them to disk."""
        history_file = tmp_path / "history.json"
        history = ArgumentHistory.load(path=history_file)
        history.record("migrate", "target", "head")
        history.record("migrate", "target", "v2.0")

        history.flush()

        assert history_file.exists()
        data = json.loads(history_file.read_text(encoding="utf-8"))
        assert data["version"] == 1
        assert data["history"]["migrate"]["target"] == ["head", "v2.0"]

    def test_flush_noop_when_no_changes(self, tmp_path: Path):
        """Calling flush() with no recorded changes does not write a file."""
        history_file = tmp_path / "history.json"
        history = ArgumentHistory.load(path=history_file)

        history.flush()

        assert not history_file.exists()

    def test_flush_clears_dirty_flag(self, tmp_path: Path):
        """After flush, the _dirty flag is reset so repeat flush is a no-op."""
        history_file = tmp_path / "history.json"
        history = ArgumentHistory.load(path=history_file)
        history.record("test", "field", "value")

        history.flush()
        assert history._dirty is False

        # Second flush should be no-op (file unchanged)
        mtime_after_first = history_file.stat().st_mtime_ns
        history.flush()
        mtime_after_second = history_file.stat().st_mtime_ns
        assert mtime_after_first == mtime_after_second


# =============================================================================
# Test 4: Full lifecycle simulation
# =============================================================================


class TestFullLifecycleSimulation:
    """Simulates the complete boot → use → shutdown → reboot cycle.

    **Validates: Requirements 1.5, 1.7, 2.2**
    """

    def test_boot_record_flush_reload_persists(self, tmp_path: Path):
        """Full lifecycle: load → record → flush → reload verifies persistence."""
        history_file = tmp_path / "argument_history.json"

        # Boot: load (empty initially)
        history = ArgumentHistory.load(path=history_file)
        assert history.get_history("deploy", "env") == []

        # Use: record values during session
        history.record("deploy", "env", "staging")
        history.record("deploy", "env", "production")
        history.record("deploy", "region", "us-west-2")

        # Shutdown: flush to disk
        history.flush()
        assert history_file.exists()

        # Reboot: reload from disk and verify state persisted
        reloaded = ArgumentHistory.load(path=history_file)
        assert reloaded.get_history("deploy", "env") == ["production", "staging"]
        assert reloaded.get_history("deploy", "region") == ["us-west-2"]

    def test_multiple_flush_reload_cycles(self, tmp_path: Path):
        """Multiple flush/reload cycles accumulate history correctly."""
        history_file = tmp_path / "argument_history.json"

        # First session
        h1 = ArgumentHistory.load(path=history_file)
        h1.record("build", "target", "debug")
        h1.flush()

        # Second session
        h2 = ArgumentHistory.load(path=history_file)
        h2.record("build", "target", "release")
        h2.flush()

        # Third session: verify accumulated
        h3 = ArgumentHistory.load(path=history_file)
        assert h3.get_history("build", "target") == ["release", "debug"]
