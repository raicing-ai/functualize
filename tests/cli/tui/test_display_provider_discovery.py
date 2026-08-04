"""Unit tests for display_provider_discovery.register_display_providers."""

from __future__ import annotations

import json
import platform
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

from functualize._cli.tui.display_provider_discovery import register_display_providers
from functualize.app.utils import resolve_cache_path

if TYPE_CHECKING:
    import pytest

_VALID_DISPLAY_MODULE = '''
class ValidProvider:
    display_id = "valid"
    display_title = "Valid Provider"
    display_priority = 1

    def should_show(self) -> bool:
        return True

    def compose_display(self):
        return []


class NotAProvider:
    """Missing required attributes — should be skipped."""

    def __init__(self):
        pass
'''


class _FakeApp:
    def __init__(self) -> None:
        self._display_slot = MagicMock()
        # register_display_providers() logs via app.log.warning(...) on its
        # best-effort exception path (loading a user displays.py can fail
        # for many reasons) — the fake must expose the same minimal surface
        # the production code duck-types against.
        self.log = MagicMock()


class TestRegisterDisplayProviders:
    """Tests for register_display_providers()."""

    def test_no_displays_file_is_noop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing displays.py → no registration, no error."""
        monkeypatch.chdir(tmp_path)
        app = _FakeApp()
        register_display_providers(app)  # type: ignore[arg-type]
        app._display_slot.register_display.assert_not_called()

    def test_registers_duck_typed_provider(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A class with all required DisplayProvider attributes gets registered."""
        (tmp_path / "displays.py").write_text(_VALID_DISPLAY_MODULE)
        monkeypatch.chdir(tmp_path)
        app = _FakeApp()

        register_display_providers(app)  # type: ignore[arg-type]

        assert app._display_slot.register_display.call_count == 1
        registered = app._display_slot.register_display.call_args[0][0]
        assert registered.display_id == "valid"

    def test_skips_classes_missing_required_attrs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Classes without the full DisplayProvider attribute set are skipped."""
        (tmp_path / "displays.py").write_text(_VALID_DISPLAY_MODULE)
        monkeypatch.chdir(tmp_path)
        app = _FakeApp()

        register_display_providers(app)  # type: ignore[arg-type]

        registered_ids = [
            call.args[0].display_id
            for call in app._display_slot.register_display.call_args_list
        ]
        assert "NotAProvider" not in registered_ids
        assert registered_ids == ["valid"]

    def test_broken_displays_file_does_not_raise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Syntax errors or exceptions during module load are swallowed."""
        (tmp_path / "displays.py").write_text("this is not valid python (((")
        monkeypatch.chdir(tmp_path)
        app = _FakeApp()

        register_display_providers(app)  # type: ignore[arg-type]

        app._display_slot.register_display.assert_not_called()


# =============================================================================
# Cache-flagged module path
# =============================================================================


class _RingStub:
    def __init__(self) -> None:
        self._displays: list[Any] = []


class _SlotStub:
    """DisplaySlot stand-in exposing the ring the dedupe helper reads."""

    def __init__(self) -> None:
        self._ring = _RingStub()
        self.registered: list[Any] = []

    def register_display(self, provider: Any) -> None:
        self.registered.append(provider)
        display = MagicMock()
        display.display_id = provider.display_id
        self._ring._displays.append(display)


class _FakeAppWithSlot:
    def __init__(self) -> None:
        self._display_slot = _SlotStub()
        self.log = MagicMock()


def _write_display_cache(project_dir: Path, displays: dict) -> Path:
    """Seed a valid v-current cache file with the given displays section."""
    from functualize._primitives.cache_format import (
        CACHE_VERSION,
        compute_deps_hash,
        get_functualize_version,
    )

    (project_dir / ".functualize").mkdir(exist_ok=True)
    cache_path = resolve_cache_path(project_dir)
    data = {
        "version": CACHE_VERSION,
        "functualize_version": get_functualize_version(),
        "python_version": platform.python_version(),
        "deps_hash": compute_deps_hash(project_dir),
        "generated_at": "2026-01-01T00:00:00+00:00",
        "entries": {},
        "pre_filter_decisions": {},
        "displays": displays,
    }
    cache_path.write_text(json.dumps(data), encoding="utf-8")
    return cache_path


def _display_module_source(display_id: str, class_name: str = "CachedDisplay") -> str:
    return (
        f"class {class_name}:\n"
        f'    display_id = "{display_id}"\n'
        f'    display_title = "Cached"\n'
        f"    display_priority = 5\n"
        f"\n"
        f"    def should_show(self, cwd, app):\n"
        f"        return True\n"
        f"\n"
        f"    def compose_display(self):\n"
        f"        return []\n"
    )


class TestRegisterCachedDisplays:
    """The TUI imports only the modules the cache flags as having displays."""

    def test_registers_from_cache_flagged_module(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = tmp_path / "widgets.py"
        module.write_text(_display_module_source("cached"))
        _write_display_cache(
            tmp_path,
            {
                str(module): {
                    "source_file": str(module),
                    "class_names": ["CachedDisplay"],
                    "source_mtime": module.stat().st_mtime,
                    "content_hash": "x",
                }
            },
        )
        monkeypatch.chdir(tmp_path)
        app = _FakeAppWithSlot()

        register_display_providers(app)  # type: ignore[arg-type]

        assert [p.display_id for p in app._display_slot.registered] == ["cached"]

    def test_dedupes_against_cwd_displays_py(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A displays.py that is also cache-flagged registers once, not twice."""
        module = tmp_path / "displays.py"
        module.write_text(_display_module_source("shared"))
        _write_display_cache(
            tmp_path,
            {
                str(module): {
                    "source_file": str(module),
                    "class_names": ["CachedDisplay"],
                    "source_mtime": module.stat().st_mtime,
                    "content_hash": "x",
                }
            },
        )
        monkeypatch.chdir(tmp_path)
        app = _FakeAppWithSlot()

        register_display_providers(app)  # type: ignore[arg-type]

        assert [p.display_id for p in app._display_slot.registered] == ["shared"]

    def test_missing_flagged_module_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A cache entry pointing at a deleted file is skipped without error."""
        _write_display_cache(
            tmp_path,
            {
                "/nowhere/gone.py": {
                    "source_file": "/nowhere/gone.py",
                    "class_names": ["CachedDisplay"],
                    "source_mtime": 0.0,
                    "content_hash": "x",
                }
            },
        )
        monkeypatch.chdir(tmp_path)
        app = _FakeAppWithSlot()

        register_display_providers(app)  # type: ignore[arg-type]

        assert app._display_slot.registered == []

    def test_broken_flagged_module_does_not_block_others(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = tmp_path / "broken.py"
        broken.write_text("this is not valid python (((")
        good = tmp_path / "good.py"
        good.write_text(_display_module_source("good"))
        _write_display_cache(
            tmp_path,
            {
                str(broken): {
                    "source_file": str(broken),
                    "class_names": ["CachedDisplay"],
                    "source_mtime": broken.stat().st_mtime,
                    "content_hash": "x",
                },
                str(good): {
                    "source_file": str(good),
                    "class_names": ["CachedDisplay"],
                    "source_mtime": good.stat().st_mtime,
                    "content_hash": "x",
                },
            },
        )
        monkeypatch.chdir(tmp_path)
        app = _FakeAppWithSlot()

        register_display_providers(app)  # type: ignore[arg-type]

        assert [p.display_id for p in app._display_slot.registered] == ["good"]

    def test_stale_version_cache_is_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A cache from another format version is not trusted for imports."""
        module = tmp_path / "widgets.py"
        module.write_text(_display_module_source("cached"))
        cache_path = _write_display_cache(
            tmp_path,
            {
                str(module): {
                    "source_file": str(module),
                    "class_names": ["CachedDisplay"],
                    "source_mtime": module.stat().st_mtime,
                    "content_hash": "x",
                }
            },
        )
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        data["version"] = -1
        cache_path.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        app = _FakeAppWithSlot()

        register_display_providers(app)  # type: ignore[arg-type]

        assert app._display_slot.registered == []
