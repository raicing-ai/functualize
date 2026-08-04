"""Tests for plugin-registered CLI command dispatch from global ``func``.

Covers the fix that makes plugin commands (e.g. ``func mcp serve``) reachable
from the global ``func`` entry point, which has no CliAdapter. Two gaps:

- Gap B: ``_dispatch_group`` resolves job groups *and* plugin command groups
  post-boot (GROUP mode / the UNKNOWN fallback).
- Gap A: ``_handle_job`` falls back to plugin group / ungrouped plugin command
  dispatch before erroring (UNKNOWN mode), since plugin groups are invisible to
  pre-boot mode detection.

Strategy: the ``mcp`` plugin (installed in the dev/test env) registers the
``mcp`` command group at APP_READY — exactly the timing that broke pre-boot
classification. Tests boot against it plus directory-discovered jobs, mirroring
production. The ungrouped-command path uses a synthetic plugin wired via static
wiring (the only boot mode that honors ``explicit_plugins``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from functualize._cli.main import (
    _dispatch_group,
    _handle_job,
    _plugin_namespace_names,
    _run_adhoc_command,
)
from functualize.app import FunctualizeApp
from functualize.app.config import ConfigSources, JobSources, PluginSources

_HELLO_JOB = (
    "def greet(name: str = 'world') -> str:\n"
    "    '''Greet someone.'''\n"
    "    return name\n"
)


def _boot_real(tmp_path: Path, files: dict[str, str] | None = None) -> FunctualizeApp:
    """Boot with default entry-point plugins (incl. mcp) + directory jobs."""
    for name, content in (files or {"hello.py": _HELLO_JOB}).items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    return FunctualizeApp(
        name="functualize",
        job_sources=JobSources(directories=[str(tmp_path)], lazy=False),
        config_sources=ConfigSources(dotenv=False),
    )


def _effective(tmp_path: Path) -> dict[str, list[str]]:
    return {"jobs_directories": [str(tmp_path)], "import_libs": []}


def _requires_mcp() -> None:
    pytest.importorskip("functualize_mcp")


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


class TestPluginNamespaceNames:
    def test_collects_namespace_and_ancestors(self) -> None:
        class _Cmd:
            def __init__(self, namespace: str | None) -> None:
                self.namespace = namespace

        names = _plugin_namespace_names([_Cmd("a.b.c"), _Cmd("mcp"), _Cmd(None)])
        assert names == {"a", "a.b", "a.b.c", "mcp"}

    def test_empty(self) -> None:
        assert _plugin_namespace_names([]) == set()


class TestRunAdhocTyper:
    def test_executes_and_emits_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        def fn(value: str = "x") -> str:
            return f"got:{value}"

        code = _run_adhoc_command("cmd", fn, ["--value", "y"], "json")
        assert code == 0
        assert '"got:y"' in capsys.readouterr().out

    def test_future_annotations_bool_resolves(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # This module uses `from __future__ import annotations`, so fn's
        # annotations are strings. functools.wraps must let Typer resolve them
        # (regression guard for "Type not yet supported: bool").
        def fn(flag: bool = False) -> str:
            return "on" if flag else "off"

        code = _run_adhoc_command("cmd", fn, ["--flag"], "json")
        assert code == 0
        assert '"on"' in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Gap B: _dispatch_group against the real mcp plugin group
# ---------------------------------------------------------------------------


class TestDispatchGroupPlugin:
    def test_lists_plugin_group_with_help(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _requires_mcp()
        app = _boot_real(tmp_path)
        code = _dispatch_group(app, ["mcp"], set())
        assert code == 0
        out = capsys.readouterr().out
        assert "serve" in out and "tools" in out
        assert "Start MCP server" in out  # help_text surfaced

    def test_executes_plugin_command(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _requires_mcp()
        app = _boot_real(tmp_path)
        code = _dispatch_group(app, ["mcp", "tools"], set())
        assert code == 0
        assert "greet" in capsys.readouterr().out  # the discovered job as a tool

    def test_unknown_sub_command_lists_available(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _requires_mcp()
        app = _boot_real(tmp_path)
        code = _dispatch_group(app, ["mcp", "nope"], set())
        assert code == 1
        err = capsys.readouterr().err
        assert "Unknown command 'nope'" in err
        assert "serve" in err and "tools" in err


class TestDispatchGroupMerged:
    def test_merged_listing_job_and_plugin(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _requires_mcp()
        # A job whose group == "mcp" coexists with the plugin's mcp group.
        app = _boot_real(
            tmp_path,
            {
                "mcpjobs.py": (
                    'JOB_GROUP = "mcp"\n\n\n'
                    "def provision() -> str:\n"
                    '    """Provision."""\n'
                    '    return "JOB"\n'
                ),
            },
        )
        code = _dispatch_group(app, ["mcp"], {"mcp"})
        assert code == 0
        out = capsys.readouterr().out
        assert "provision" in out  # the job
        assert "serve" in out and "tools" in out  # plugin commands

    def test_job_wins_on_name_collision(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _requires_mcp()
        # Both a job and the plugin register "tools" in group "mcp".
        app = _boot_real(
            tmp_path,
            {
                "mcpjobs.py": (
                    "from functualize.job import Stdout\n\n"
                    'JOB_GROUP = "mcp"\n\n\n'
                    "def tools(out: Stdout) -> str:\n"
                    '    """Colliding job."""\n'
                    '    out.emit("JOB_TOOLS")\n'
                    '    return "JOB_TOOLS"\n'
                ),
            },
        )
        code = _dispatch_group(app, ["mcp", "tools"], {"mcp"}, output_format="json")
        assert code == 0
        out = capsys.readouterr().out
        # Job wins (D3). The observable is what the job *emits*, not what it
        # returns: a job's return value is programmatic only (rc.invoke /
        # FromJob) and is never written to stdout. This doubles as the
        # end-to-end proof that `out: Stdout` is injected and honors --output
        # through real dispatch.
        assert "JOB_TOOLS" in out
        assert "MCP Tools" not in out


# ---------------------------------------------------------------------------
# Gap A: _handle_job UNKNOWN fallback (plugin group + ungrouped command)
# ---------------------------------------------------------------------------


class TestHandleJobFallbackGrouped:
    def test_plugin_group_token_lists(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _requires_mcp()
        (tmp_path / "hello.py").write_text(_HELLO_JOB, encoding="utf-8")
        code = _handle_job(["mcp"], tmp_path, {}, _effective(tmp_path), {})
        assert code == 0
        out = capsys.readouterr().out
        assert "serve" in out and "tools" in out

    def test_plugin_sub_command_executes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _requires_mcp()
        (tmp_path / "hello.py").write_text(_HELLO_JOB, encoding="utf-8")
        code = _handle_job(["mcp", "tools"], tmp_path, {}, _effective(tmp_path), {})
        assert code == 0
        assert "greet" in capsys.readouterr().out

    def test_unknown_token_still_errors_with_suggestions(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "hello.py").write_text(_HELLO_JOB, encoding="utf-8")
        code = _handle_job(
            ["definitely_not_a_command"], tmp_path, {}, _effective(tmp_path), {}
        )
        assert code == 1
        assert "Unknown command" in capsys.readouterr().err


class _UngroupedPlugin:
    """Static-wiring fixture registering a top-level (ungrouped) command."""

    name = "ungrouped-plugin"
    version = "1.0.0"
    description = "Fixture plugin registering an ungrouped command"

    def __call__(self, app: Any) -> None:
        from functualize._events.hooks import HookEvent

        app.hook_registry.register_global(HookEvent.APP_READY, self._on_ready)

    def _on_ready(self, app: Any) -> None:
        app.register_plugin_command(
            "standalone", self._standalone, help_text="Top-level command"
        )

    @staticmethod
    def _standalone(value: str = "x") -> str:
        return f"standalone:{value}"


def _dummy_job() -> str:
    return "dummy"


def _boot_static(plugins: list[Any]) -> FunctualizeApp:
    """Boot via static wiring — the only mode that honors explicit_plugins."""
    from functualize._config.chain import ResolutionChain
    from functualize._config.sources import DefaultSource

    return FunctualizeApp(
        name="functualize",
        job_sources=JobSources(functions=[_dummy_job]),
        config_sources=ConfigSources(
            config_resolution_chain=ResolutionChain([DefaultSource({})]),
            dotenv=False,
        ),
        plugin_sources=PluginSources(entry_point_group="", explicit_plugins=plugins),
    )


class TestHandleJobFallbackUngrouped:
    def test_ungrouped_command_executes(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # _handle_job builds its own app; inject a pre-booted static-wired app
        # carrying an ungrouped plugin command. _handle_job does
        # `from functualize.app import FunctualizeApp`, so patch it there.
        booted = _boot_static([_UngroupedPlugin()])
        assert any(c.name == "standalone" for c in booted.get_plugin_commands())
        monkeypatch.setattr(
            "functualize.app.FunctualizeApp",
            lambda *a, **k: booted,
            raising=True,
        )
        code = _handle_job(
            ["standalone", "--value", "zz"],
            tmp_path,
            {},
            _effective(tmp_path),
            {},
            output_format="json",
        )
        assert code == 0
        assert '"standalone:zz"' in capsys.readouterr().out
