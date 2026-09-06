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
            "Detection",
            "InstallMode",
            "RuntimeOverrideError",
            "detect",
            "detect_from_process",
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


class TestNothingCliCameWithIt:
    def test_the_module_imports_no_cli_package(self) -> None:
        source = (REPO_ROOT / "src/functualize/app/packaging.py").read_text()
        assert "functualize._cli" not in source

    def test_it_imports_no_underscore_package_at_all(self) -> None:
        """`app/` is public. Acquiring an internal import here is what
        `lint-imports` would catch on the next run; asserting it locally makes
        the failure attributable to this file."""
        source = (REPO_ROOT / "src/functualize/app/packaging.py").read_text()
        assert "from functualize._" not in source
        assert "import functualize._" not in source

    def test_it_imports_no_click(self) -> None:
        source = (REPO_ROOT / "src/functualize/app/packaging.py").read_text()
        assert "click" not in source

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
