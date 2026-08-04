"""Tests for adapter extraction completeness (Task 11.3).

Verifies:
1. `app/adapters/` contains ONLY `CliAdapter`, `TuiAdapter`, and `AdapterPlugin`
   protocol — no HTTP/Lambda adapter implementations remain in the core package.
2. The old `adapters/http.py` and `adapters/lambda_.py` files have been deleted
   from the core source tree.
3. Importing `functualize.app` without HTTP/Lambda packages does NOT trigger
   ImportError.

Requirements: 10.5, 10.6
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

# Root of the functualize source package
SRC_ROOT = Path(__file__).parent.parent / "src" / "functualize"


class TestAdapterDirectoryContents:
    """Verify app/adapters/ contains only the expected built-in modules."""

    def test_app_adapters_contains_only_expected_files(self):
        """app/adapters/ should contain only the known adapter modules."""
        adapters_dir = SRC_ROOT / "app" / "adapters"
        assert adapters_dir.exists(), f"{adapters_dir} does not exist"

        # Get all .py files (excluding __pycache__)
        py_files = sorted(
            f.name for f in adapters_dir.iterdir() if f.is_file() and f.suffix == ".py"
        )

        # lazy_command.py: lazy command construction from cached metadata, moved
        # out of _discovery so internal packages stay import-light
        # click_params.py: click-native command construction from job signatures
        # + config models (the typer-free replacement for the create_job_command
        # pipeline); shares the engine callback so the paths cannot drift
        # surface_gate.py: direct-run StdoutSurface gate shared by cli.py and
        # lazy_command.py so the two command paths cannot drift
        expected_files = [
            "__init__.py",
            "_validation.py",
            "cli.py",
            "click_params.py",
            "lazy_command.py",
            "surface_gate.py",
            "tui.py",
        ]
        assert py_files == expected_files, (
            f"app/adapters/ should contain exactly {expected_files}, "
            f"but found: {py_files}"
        )

    def test_no_http_adapter_in_app_adapters(self):
        """No http.py file should exist in app/adapters/."""
        http_path = SRC_ROOT / "app" / "adapters" / "http.py"
        assert not http_path.exists(), (
            "http.py should not exist in app/adapters/ — "
            "HttpAdapter has been extracted to plugins/functualize-http/"
        )

    def test_no_lambda_adapter_in_app_adapters(self):
        """No lambda_.py file should exist in app/adapters/."""
        lambda_path = SRC_ROOT / "app" / "adapters" / "lambda_.py"
        assert not lambda_path.exists(), (
            "lambda_.py should not exist in app/adapters/ — "
            "LambdaAdapter has been extracted to plugins/functualize-lambda/"
        )


class TestOldAdaptersDirectoryCleaned:
    """Verify the old top-level adapters/ directory has no HTTP/Lambda files."""

    def test_no_http_adapter_in_old_adapters(self):
        """Old adapters/http.py should not exist."""
        http_path = SRC_ROOT / "adapters" / "http.py"
        assert not http_path.exists(), (
            "adapters/http.py should have been deleted — "
            "HttpAdapter extracted to plugins/functualize-http/"
        )

    def test_no_lambda_adapter_in_old_adapters(self):
        """Old adapters/lambda_.py should not exist."""
        lambda_path = SRC_ROOT / "adapters" / "lambda_.py"
        assert not lambda_path.exists(), (
            "adapters/lambda_.py should have been deleted — "
            "LambdaAdapter extracted to plugins/functualize-lambda/"
        )


class TestAppAdaptersExports:
    """Verify app/adapters/__init__.py exports exactly CliAdapter, TuiAdapter,
    and AdapterPlugin."""

    def test_all_contains_expected_symbols(self):
        """__all__ should list exactly AdapterPlugin, CliAdapter, TuiAdapter."""
        from functualize.app import adapters

        expected = {"AdapterPlugin", "CliAdapter", "TuiAdapter"}
        actual = set(adapters.__all__)
        assert actual == expected, (
            f"app/adapters/__all__ should be {sorted(expected)}, "
            f"but is {sorted(actual)}"
        )

    def test_adapter_plugin_is_importable(self):
        """AdapterPlugin should be importable from functualize.app.adapters."""
        from functualize.app.adapters import AdapterPlugin

        assert AdapterPlugin is not None
        # It should be a Protocol class
        assert hasattr(AdapterPlugin, "__protocol_attrs__") or hasattr(
            AdapterPlugin, "_is_protocol"
        ), "AdapterPlugin should be a Protocol"

    def test_cli_adapter_is_importable(self):
        """CliAdapter should be importable from functualize.app.adapters."""
        from functualize.app.adapters import CliAdapter

        assert CliAdapter is not None

    def test_tui_adapter_is_importable(self):
        """TuiAdapter should be importable from functualize.app.adapters."""
        from functualize.app.adapters import TuiAdapter

        assert TuiAdapter is not None


class TestImportWithoutHttpLambda:
    """Verify importing functualize.app without HTTP/Lambda packages
    does not trigger ImportError (Requirement 10.6)."""

    def test_import_functualize_app_no_import_error(self):
        """import functualize.app should succeed without HTTP/Lambda packages."""
        # This test runs in-process — if HTTP/Lambda adapters were still
        # referenced as runtime imports, this would fail with ImportError
        import functualize.app  # noqa: F401

    def test_import_functualize_app_subprocess(self, tmp_path: Path):
        """Subprocess test: import functualize.app succeeds and does not
        reference any http/lambda adapter modules."""
        script = textwrap.dedent("""\
            import sys

            # Import the public app module
            import functualize.app

            # Check that no http/lambda adapter modules are loaded
            http_modules = [m for m in sys.modules if 'functualize_http' in m]
            lambda_modules = [m for m in sys.modules if 'functualize_lambda' in m]

            if http_modules:
                print(f"FAIL: HTTP adapter modules loaded: {http_modules}", file=sys.stderr)
                sys.exit(1)
            if lambda_modules:
                print(f"FAIL: Lambda adapter modules loaded: {lambda_modules}", file=sys.stderr)
                sys.exit(1)

            # Also verify that no adapters/http or adapters/lambda_ modules exist
            adapter_modules = [
                m for m in sys.modules
                if 'adapters.http' in m or 'adapters.lambda' in m
            ]
            if adapter_modules:
                print(f"FAIL: Old adapter modules loaded: {adapter_modules}", file=sys.stderr)
                sys.exit(1)

            print("PASS: functualize.app imports cleanly without HTTP/Lambda")
            sys.exit(0)
        """)

        script_path = tmp_path / "check_no_http_lambda.py"
        script_path.write_text(script)

        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, (
            f"Importing functualize.app triggered HTTP/Lambda adapter loading:\n"
            f"  stdout: {result.stdout}\n"
            f"  stderr: {result.stderr}"
        )

    def test_import_functualize_job_no_import_error(self):
        """import functualize.job should also succeed without HTTP/Lambda."""
        import functualize.job  # noqa: F401
