"""Install detection is public: `functualize.app.packaging`.

`_cli/runtime.py`, `_cli/package_ops.py` and `_cli/manifest.py` are ~1,683
lines answering "is this installed, how, and what command changes it" — for
functualize itself only. A package built on functualize had two options:
reimplement it, and ship a second detector that disagrees; or import an
underscore package the constitution forbids even `_cli` from touching.

Nothing about the semantics changes. `_cli/runtime.py` **moved** to
`app/packaging.py` rather than being wrapped, because it was already
stdlib-only (`os`, `tomllib`, `dataclasses`, `enum`, `pathlib`, `typing`) —
nothing CLI travelled with it. The 193 existing behaviour tests in
`tests/_cli/` still pass, unchanged except for the import line.

This file asserts the *seam*, not the behaviour: that it is reachable from a
public module, that nothing CLI came with it, and that the old private path is
gone rather than shadowing it.

Never runs `self update` or `self install` — they mutate the developer's
environment.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestThePublicSurface:
    def test_the_documented_names_import(self) -> None:
        from functualize.app.packaging import (
            Detection,
            InstallMode,
            RuntimeOverrideError,
            detect,
            detect_from_process,
        )

        assert all(
            obj is not None
            for obj in (
                Detection,
                InstallMode,
                RuntimeOverrideError,
                detect,
                detect_from_process,
            )
        )

    def test_all_lists_them(self) -> None:
        from functualize.app import packaging

        assert set(packaging.__all__) == {
            # Detection (3.1)
            "Detection",
            "InstallMode",
            "RuntimeOverrideError",
            "detect",
            "detect_from_process",
            # Command planning (3.2)
            "LossyReceiptError",
            "MissingToolError",
            "Receipt",
            "Requirement",
            "StandaloneUpdateError",
            "capture",
            "capture_environment",
            "drop_from_receipt",
            "install_commands",
            "merge_receipt",
            "names_to_restore",
            "normalize",
            "owned_python",
            "read_receipt",
            "resolve_pipx",
            "resolve_uv",
            "uninstall_commands",
            "update_commands",
        }

    def test_detect_from_process_answers_for_this_install(self) -> None:
        """The ergonomic entry point: no arguments, reads the live process."""
        from functualize.app.packaging import Detection, detect_from_process

        result = detect_from_process()
        assert isinstance(result, Detection)
        assert result.mode is not None

    def test_detect_takes_every_input_explicitly(self) -> None:
        """`contracts.md` §S2 sketches `detect(tool: str = "functualize")`.
        That is **not** the signature, and the difference is deliberate rather
        than an oversight: every input is a parameter because `sys.prefix`
        cannot be set by an environment variable, so a version reading it
        directly could only be exercised in whichever mode the suite happens
        to run under.

        3.1 is a *move*, not a redesign — "nothing about the semantics
        changes" — so the real signature is what became public, and the
        contract sketch is what is wrong. Pinned here so the mismatch is a
        recorded decision rather than a surprise.
        """
        import inspect

        from functualize.app.packaging import Detection, detect

        assert list(inspect.signature(detect).parameters) == [
            "prefix",
            "base_prefix",
            "environ",
            "argv0",
            "cwd",
        ]
        result = detect(
            prefix="/venv",
            base_prefix="/usr",
            environ={},
            argv0="func",
            cwd=REPO_ROOT,
        )
        assert isinstance(result, Detection)

    def test_install_mode_serializes_to_its_spelling(self) -> None:
        """It is a `StrEnum` on purpose — a host embedding the answer in JSON
        gets the documented word, not `InstallMode.UV_TOOL`."""
        from functualize.app.packaging import InstallMode

        for member in InstallMode:
            assert str(member) == member.value


def _imported_modules() -> set[str]:
    """Every module named by an import in `app/packaging.py`.

    Parsed, not grepped. These assertions used to search the source text, and
    3.2 broke two of them by *documenting* what the module deliberately does
    not do -- `functualize._cli.self_update` is named in a docstring that
    explains why standalone update is not a subprocess. A substring test cannot
    tell an import from a sentence about one; the AST can.
    """
    import ast

    tree = ast.parse((REPO_ROOT / "src/functualize/app/packaging.py").read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


class TestNothingCliCameWithIt:
    def test_the_module_imports_no_cli_package(self) -> None:
        assert not {m for m in _imported_modules() if m.startswith("functualize._cli")}

    def test_it_imports_no_underscore_package_at_all(self) -> None:
        """`app/` is public. Acquiring an internal import here is what
        `lint-imports` would catch on the next run; asserting it locally makes
        the failure attributable to this file."""
        assert not {m for m in _imported_modules() if m.startswith("functualize._")}

    def test_it_imports_no_click(self) -> None:
        """Planning is public; prompting is not. A CLI framework here would
        make the module unimportable for a host that has no terminal."""
        assert not {m for m in _imported_modules() if m.split(".")[0] == "click"}

    def test_the_import_check_can_actually_fail(self) -> None:
        """The guard against a vacuous structural test."""
        import ast

        tree = ast.parse("import click\nfrom functualize._cli import x\n")
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module)
        assert found == {"click", "functualize._cli"}

    def test_importing_it_pulls_in_no_cli_module(self) -> None:
        """Stronger than reading the file: a transitive import would not show
        up in the source, and this module is meant to be cheap enough for a
        host to import at startup."""
        program = (
            "import sys; import functualize.app.packaging; "
            "print([m for m in sys.modules if m.startswith('functualize._cli')])"
        )
        result = subprocess.run(
            ["python", "-c", program],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip() == "[]", result.stdout


class TestThePrivatePathIsGone:
    def test_the_old_module_no_longer_exists(self) -> None:
        """A shim left behind would let a consumer keep the private import and
        never learn the public one exists."""
        assert not (REPO_ROOT / "src/functualize/_cli/runtime.py").exists()

    def test_it_is_not_importable(self) -> None:
        with pytest.raises(ModuleNotFoundError):
            import functualize._cli.runtime  # noqa: F401

    def test_no_source_file_still_imports_it(self) -> None:
        """The task's own gate, executable rather than run once by hand."""
        result = subprocess.run(
            ["grep", "-rn", "from functualize._cli.runtime import", "src/"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.stdout == "", result.stdout


class TestPlanningIsPublicAndPure:
    """3.2 — the command builders are askable by a host, and answer with argv.

    The split is the point: a host that wants to know *what would upgrade this*
    can now ask without importing `_cli` and without anything being printed,
    prompted, or run. `_cli/package_ops.py` keeps exactly the three functions
    that need a terminal.
    """

    def test_a_host_can_plan_an_upgrade_without_touching_cli(self, monkeypatch) -> None:
        from functualize.app import packaging

        monkeypatch.setattr(packaging, "resolve_uv", lambda: "/opt/uv")
        commands = packaging.update_commands(
            packaging.Detection(
                mode=packaging.InstallMode.TOOL_UV,
                owning_distribution="myapp",
            ),
            "/usr/local/bin/myapp",
        )
        assert commands == (("/opt/uv", "tool", "upgrade", "myapp"),)

    def test_planning_runs_nothing(self, monkeypatch) -> None:
        """The property that makes it safe to call from a host: a planner that
        executed would mutate the caller's environment on a question."""
        import subprocess as _subprocess

        from functualize.app import packaging

        def _explode(*args, **kwargs):
            raise AssertionError("planning must not spawn a process")

        monkeypatch.setattr(_subprocess, "run", _explode)
        monkeypatch.setattr(_subprocess, "call", _explode)
        monkeypatch.setattr(_subprocess, "Popen", _explode)
        monkeypatch.setattr(packaging, "resolve_uv", lambda: "/opt/uv")

        detection = packaging.Detection(
            mode=packaging.InstallMode.PROJECT, owning_distribution="myapp"
        )
        packaging.update_commands(detection, "/usr/local/bin/myapp")
        packaging.install_commands(detection, "requests")
        packaging.uninstall_commands(detection, "requests")

    def test_the_owner_is_never_hardcoded_to_functualize(self, monkeypatch) -> None:
        """The reason planning is a function rather than a table: an
        application built on functualize upgrades *itself*."""
        from functualize.app import packaging

        monkeypatch.setattr(packaging, "resolve_pipx", lambda: "/opt/pipx")
        (command,) = packaging.update_commands(
            packaging.Detection(
                mode=packaging.InstallMode.TOOL_PIPX,
                owning_distribution="someone-elses-app",
            ),
            "/usr/local/bin/x",
        )
        assert "someone-elses-app" in command
        assert "functualize" not in command


class TestTheInteractiveHalfStayedBehind:
    """`announce`, `plan_or_exit` and `refuse` print, prompt, and exit.

    They are the reason `app/packaging.py` can stay terminal-free, so their
    staying is as load-bearing as the move itself.
    """

    def test_the_three_are_still_in_cli(self) -> None:
        from functualize._cli import package_ops

        for name in ("announce", "plan_or_exit", "refuse"):
            assert callable(getattr(package_ops, name)), name

    def test_they_did_not_also_land_in_the_public_module(self) -> None:
        from functualize.app import packaging

        for name in ("announce", "plan_or_exit", "refuse"):
            assert not hasattr(packaging, name), name

    def test_the_execution_seam_stayed_in_cli(self) -> None:
        """`_call` is the single point this feature executes anything, and the
        seam every test replaces. Moving it would put a subprocess on a public
        module."""
        from functualize._cli import package_ops
        from functualize.app import packaging

        assert hasattr(package_ops, "_call")
        assert not hasattr(packaging, "_call")
