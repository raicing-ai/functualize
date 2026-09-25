"""Unit tests for the tests-for-diff mapper (.agents/skills/test-tiers)."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / ".agents/skills/test-tiers/scripts/tests-for-diff"
)


def _load_mapper() -> ModuleType:
    # The script has no .py extension, so a SourceFileLoader must be explicit.
    loader = importlib.machinery.SourceFileLoader("tests_for_diff", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_loader("tests_for_diff", loader)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MAPPER = _load_mapper()


def _write(root: Path, rel: str, content: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.chdir(tmp_path)
    yield tmp_path


def test_changed_test_file_selects_itself(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(repo, "tests/config/test_project_dirs.py")
    assert MAPPER.main(["--files", "tests/config/test_project_dirs.py"]) == 0
    assert capsys.readouterr().out.splitlines() == ["tests/config/test_project_dirs.py"]


def test_direct_importers_selected(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(repo, "src/functualize/_config/project_dirs.py")
    _write(
        repo,
        "tests/config/test_project_dirs.py",
        "from functualize._config.project_dirs import read_toml_file\n",
    )
    _write(
        repo,
        "tests/cli/test_single_file_cwd_isolation.py",
        "from functualize._config import project_dirs\n",
    )
    _write(
        repo,
        "tests/app/test_job_sources.py",
        "from functualize._config import resolution_chain\n",
    )
    assert MAPPER.main(["--files", "src/functualize/_config/project_dirs.py"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out == [
        "tests/cli/test_single_file_cwd_isolation.py",
        "tests/config/test_project_dirs.py",
    ]


def test_no_direct_importers_falls_back_to_package(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(repo, "src/functualize/_engine/job_middleware.py")
    _write(
        repo,
        "tests/context/test_middleware_di.py",
        "from functualize._engine.middleware import build_chain\n",
    )
    _write(
        repo,
        "tests/config/test_unrelated.py",
        "from functualize._config.resolution_chain import ResolutionChain\n",
    )
    assert MAPPER.main(["--files", "src/functualize/_engine/job_middleware.py"]) == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines() == ["tests/context/test_middleware_di.py"]
    # Composed at runtime: this file's own source must not carry the dotted
    # module path as a literal, or the mapper would count this test as a
    # direct importer and the fallback under test would never fire here.
    dotted = "functualize._engine" + ".job_middleware"
    assert f"no test imports {dotted} directly" in captured.err


@pytest.mark.parametrize(
    "path",
    [
        "tests/conftest.py",
        "tests/_support/engine_run.py",
        "pyproject.toml",
        "uv.lock",
    ],
)
def test_shared_infrastructure_exits_three(
    repo: Path, capsys: pytest.CaptureFixture[str], path: str
) -> None:
    _write(repo, path)
    assert MAPPER.main(["--files", path]) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "shared infrastructure changed: run the tip tier" in captured.err


def test_non_code_paths_select_nothing(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(repo, "docs/index.md")
    _write(repo, ".spec/STATUS.md")
    assert MAPPER.main(["--files", "docs/index.md", ".spec/STATUS.md"]) == 0
    assert capsys.readouterr().out == ""


def test_plugin_change_selects_plugin_tests(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(
        repo, "plugins/adapters/functualize-inline/src/functualize_inline/adapter.py"
    )
    _write(repo, "plugins/adapters/functualize-inline/tests/test_adapter.py")
    path = "plugins/adapters/functualize-inline/src/functualize_inline/adapter.py"
    assert MAPPER.main(["--files", path]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "plugins/adapters/functualize-inline/tests"
    ]


def test_plugin_without_tests_dir_selects_nothing(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(repo, "plugins/adapters/bare-plugin/src/thing.py")
    assert MAPPER.main(["--files", "plugins/adapters/bare-plugin/src/thing.py"]) == 0
    assert capsys.readouterr().out == ""


def test_output_deduplicated_sorted_existing_only(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(repo, "src/functualize/_config/project_dirs.py")
    _write(
        repo,
        "tests/config/test_project_dirs.py",
        "from functualize._config.project_dirs import read_toml_file\n",
    )
    _write(
        repo,
        "tests/cli/test_single_file_cwd_isolation.py",
        "from functualize._config import project_dirs\n",
    )
    args = [
        "tests/config/test_project_dirs.py",
        "tests/config/test_project_dirs.py",  # duplicate input
        "src/functualize/_config/project_dirs.py",
        "tests/test_deleted.py",  # changed but not on disk
    ]
    assert MAPPER.main(["--files", *args]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "tests/cli/test_single_file_cwd_isolation.py",
        "tests/config/test_project_dirs.py",
    ]


def test_default_input_reads_committed_and_uncommitted_changes(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(repo, "src/functualize/_config/project_dirs.py")
    _write(
        repo,
        "tests/cli/test_single_file_cwd_isolation.py",
        "from functualize._config import project_dirs\n",
    )
    _git(repo, "init", "-b", "topic")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Mapper Test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    _git(repo, "update-ref", "refs/remotes/origin/master", "HEAD")
    _write(repo, "src/functualize/_config/project_dirs.py", "# edited\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "edit module")
    _write(repo, "tests/config/test_added.py")  # untracked, selects itself (M1)
    assert MAPPER.main([]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "tests/cli/test_single_file_cwd_isolation.py",  # committed src change (M2)
        "tests/config/test_added.py",  # uncommitted new test (M1)
    ]


def test_script_is_executable_and_runs_standalone(repo: Path) -> None:
    assert SCRIPT_PATH.stat().st_mode & 0o111
    assert SCRIPT_PATH.read_text(encoding="utf-8").splitlines()[0].startswith("#!")
    _write(repo, "tests/test_smoke.py")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--files", "tests/test_smoke.py"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(repo),
    )
    assert proc.returncode == 0
    assert proc.stdout.splitlines() == ["tests/test_smoke.py"]
