"""The dead-code delta: what a change introduces or orphans, and nothing else.

`.github/scripts/dead_code_delta.py` runs vulture at two commits and reports only
what is new at the head. Every case here builds a throwaway repository with a
base and a head commit and asks the script about the pair, because the inputs it
reads — two commits and the objects behind them — are inputs of a git
invocation, not of a function.

The fixture's `[tool.vulture]` table is the **shipped** one, copied from this
repository's `pyproject.toml`, so the framework cases (a Textual handler, a Click
command) exercise the ignore list that is actually in force rather than one
written for the test.

Most cases call `main()` in-process for speed; one runs the script as a process,
the way a reviewer does, so the exit status that reaches a shell is pinned too.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / ".github" / "scripts" / "dead_code_delta.py"
_AGENTS = _ROOT / "AGENTS.md"

COMMAND = "uv run python .github/scripts/dead_code_delta.py"

PRIMITIVES = "src/pkg/_primitives/helpers.py"


def _delta() -> Any:
    """Load the script out-of-tree, under a name of its own.

    Registered in `sys.modules` before execution for the reason
    `tests/spec/test_message_hygiene_check.py::_checker` records.
    """
    name = "_fz_dead_code_delta"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        del sys.modules[name]
        raise
    return module


def _shipped_vulture_table() -> dict[str, Any]:
    with (_ROOT / "pyproject.toml").open("rb") as handle:
        table: dict[str, Any] = tomllib.load(handle)["tool"]["vulture"]
    return table


def _pyproject() -> str:
    """A `pyproject.toml` carrying the shipped `[tool.vulture]` table.

    JSON arrays of plain strings are valid TOML arrays, so `json.dumps` is a
    faithful serialiser for the two lists without a TOML writer.
    """
    table = _shipped_vulture_table()
    return (
        "[tool.vulture]\n"
        f"min_confidence = {table['min_confidence']}\n"
        f"ignore_names = {json.dumps(table['ignore_names'])}\n"
        f"ignore_decorators = {json.dumps(table['ignore_decorators'])}\n"
    )


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "--no-verify", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


BASE_FILES = {
    "src/pkg/__init__.py": "",
    "src/pkg/_primitives/__init__.py": "",
    PRIMITIVES: (
        "def used_helper():\n    return 1\n\n\ndef stale_helper():\n    return 2\n"
    ),
    "src/pkg/core.py": (
        "from pkg._primitives.helpers import used_helper\n"
        "\n"
        "\n"
        "def entry():\n"
        "    return used_helper()\n"
        "\n"
        "\n"
        "print(entry())\n"
    ),
    "tests/test_core.py": (
        "from pkg.core import entry\n\n\ndef test_entry():\n    assert entry() == 1\n"
    ),
}


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repository whose base already carries one dead helper, `stale_helper`."""
    _git(tmp_path, "init", "-q", "-b", "master")
    _git(tmp_path, "config", "user.email", "tester@example.invalid")
    _git(tmp_path, "config", "user.name", "Tester")
    _write(tmp_path, "pyproject.toml", _pyproject())
    for rel, text in BASE_FILES.items():
        _write(tmp_path, rel, text)
    _commit(tmp_path, "chore: base")
    _git(tmp_path, "checkout", "-q", "-b", "topic")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict[str, Any]]:
    code = _delta().main([*argv, "--json"])
    out = capsys.readouterr().out
    return code, json.loads(out) if out.strip() else {}


def _names(document: dict[str, Any]) -> list[tuple[str, str]]:
    return [(f["symbol"], f["class"]) for f in document["findings"]]


class TestNoChange:
    def test_a_commit_against_itself_reports_nothing(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The pre-existing `stale_helper` cancels against itself."""
        code, document = _run(capsys, "master", "master")
        assert code == 0
        assert document["findings"] == []
        assert document["counts"] == {"NEW_DEAD": 0, "TESTS_ONLY": 0}

    def test_shifted_lines_are_not_new(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Findings are keyed by symbol, so a line shift above one is no finding."""
        text = (repo / PRIMITIVES).read_text(encoding="utf-8")
        _write(
            repo, PRIMITIVES, '"""Helpers.\n\nNow with a docstring.\n"""\n\n\n' + text
        )
        head = _commit(repo, "docs: describe the helpers")
        code, document = _run(capsys, "master", head)
        assert code == 0, document["findings"]

    def test_a_renamed_file_carries_its_old_findings_with_it(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`git mv` of a file holding pre-existing dead code is no finding."""
        _git(repo, "mv", PRIMITIVES, "src/pkg/_primitives/moved.py")
        _write(
            repo,
            "src/pkg/core.py",
            BASE_FILES["src/pkg/core.py"].replace("helpers", "moved"),
        )
        head = _commit(repo, "refactor: move")
        code, document = _run(capsys, "master", head)
        assert code == 0, document["findings"]


class TestNewDead:
    def test_an_uncalled_function_is_exactly_one_new_dead(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = (repo / PRIMITIVES).read_text(encoding="utf-8")
        _write(repo, PRIMITIVES, text + "\n\ndef never_called():\n    return 3\n")
        head = _commit(repo, "feat: add a helper")
        code, document = _run(capsys, "master", head)
        assert code == 1
        assert document["findings"] == [
            {
                "path": PRIMITIVES,
                "line": 9,
                "symbol": "never_called",
                "kind": "function",
                "class": "NEW_DEAD",
                "marker": None,
                "confidence": 60,
            }
        ]

    def test_removing_the_only_call_orphans_a_function_in_an_untouched_file(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The orphan case: the diff never touches the function's own file."""
        _write(
            repo, "src/pkg/core.py", "def entry():\n    return 1\n\n\nprint(entry())\n"
        )
        head = _commit(repo, "refactor: inline the helper")
        assert PRIMITIVES not in _git(repo, "diff", "--name-only", "master", head)
        code, document = _run(capsys, "master", head)
        assert code == 1
        assert _names(document) == [("used_helper", "NEW_DEAD")]
        assert document["findings"][0]["path"] == PRIMITIVES

    def test_methods_are_keyed_by_their_class(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Two pre-existing dead `run`s do not hide a third in a new class."""
        _write(
            repo,
            "src/pkg/shapes.py",
            "class A:\n    def run(self):\n        pass\n\n\n"
            "class B:\n    def run(self):\n        pass\n\n\nprint(A, B)\n",
        )
        _commit(repo, "feat: shapes")
        base = _git(repo, "rev-parse", "HEAD").strip()
        text = (repo / "src/pkg/shapes.py").read_text(encoding="utf-8")
        _write(
            repo,
            "src/pkg/shapes.py",
            text + "\n\nclass C:\n    def run(self):\n        pass\n\n\nprint(C)\n",
        )
        head = _commit(repo, "feat: a third shape")
        code, document = _run(capsys, base, head)
        assert code == 1
        assert _names(document) == [("C.run", "NEW_DEAD")]


class TestTestsOnly:
    def test_a_function_only_a_new_test_calls_is_tests_only(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = (repo / PRIMITIVES).read_text(encoding="utf-8")
        _write(repo, PRIMITIVES, text + "\n\ndef only_tested():\n    return 4\n")
        _write(
            repo,
            "tests/test_helpers.py",
            "from pkg._primitives.helpers import only_tested\n\n\n"
            "def test_only_tested():\n    assert only_tested() == 4\n",
        )
        head = _commit(repo, "feat: a tested helper")
        code, document = _run(capsys, "master", head)
        assert code == 1
        assert _names(document) == [("only_tested", "TESTS_ONLY")]

    def test_removing_the_last_production_caller_leaves_it_tests_only(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(
            repo,
            "tests/test_helpers.py",
            "from pkg._primitives.helpers import used_helper\n\n\n"
            "def test_used_helper():\n    assert used_helper() == 1\n",
        )
        base = _commit(repo, "test: pin the helper")
        _write(
            repo, "src/pkg/core.py", "def entry():\n    return 1\n\n\nprint(entry())\n"
        )
        head = _commit(repo, "refactor: inline the helper")
        code, document = _run(capsys, base, head)
        assert code == 1
        assert _names(document) == [("used_helper", "TESTS_ONLY")]


class TestNotReported:
    def test_a_textual_handler_and_a_click_command_are_not_reported(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Framework-dispatched: nothing calls them by name, by design.

        The handler's `event` argument is unused too, which is an interface
        concern and not reported either.
        """
        _write(
            repo,
            "src/pkg/tui.py",
            "from textual.app import App\n\n\n"
            "class Panel(App):\n"
            "    BINDINGS = []\n\n"
            "    def compose(self):\n        yield from ()\n\n"
            "    def on_key(self, event):\n        pass\n\n"
            "    def action_quit_panel(self):\n        pass\n\n\n"
            "print(Panel)\n",
        )
        _write(
            repo,
            "src/pkg/commands.py",
            "import click\n\n\n"
            "@click.group()\ndef cli():\n    pass\n\n\n"
            '@cli.command("hello")\n@click.option("--name")\n'
            "def hello(name):\n    pass\n\n\n"
            "print(cli)\n",
        )
        head = _commit(repo, "feat: a panel and a command")
        code, document = _run(capsys, "master", head)
        assert code == 0, document["findings"]

    def test_a_pytest_fixture_and_a_job_function_are_not_reported(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(
            repo,
            "tests/conftest.py",
            "import pytest\n\n\n@pytest.fixture()\ndef workspace():\n    return 1\n",
        )
        _write(repo, "examples/demo/jobs/deploy.py", "def deploy():\n    return 0\n")
        head = _commit(repo, "test: a fixture and a job")
        code, document = _run(capsys, "master", head)
        assert code == 0, document["findings"]


class TestMarker:
    def test_a_transitional_definition_is_marked(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = (repo / PRIMITIVES).read_text(encoding="utf-8")
        _write(
            repo,
            PRIMITIVES,
            text + "\n\n# TRANSITIONAL(2.3): consumed once the reader lands.\n"
            "def staged():\n    return 5\n",
        )
        head = _commit(repo, "feat: stage a helper")
        code, document = _run(capsys, "master", head)
        assert code == 1
        [finding] = document["findings"]
        assert (finding["symbol"], finding["marker"]) == ("staged", "TRANSITIONAL")

        assert _delta().main(["master", head]) == 1
        text_out = capsys.readouterr().out
        assert (
            f"{PRIMITIVES}:10 staged function NEW_DEAD marker=TRANSITIONAL" in text_out
        )


class TestNeighbourhood:
    def test_pre_existing_findings_in_changed_files_are_shown_and_capped(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(
            repo,
            "src/pkg/old.py",
            "def a():\n    pass\n\n\ndef b():\n    pass\n\n\ndef c():\n    pass\n",
        )
        base = _commit(repo, "chore: three dead functions")
        _write(
            repo,
            "src/pkg/old.py",
            (repo / "src/pkg/old.py").read_text(encoding="utf-8") + "\nprint(1)\n",
        )
        head = _commit(repo, "chore: touch the file")
        code, document = _run(capsys, base, head, "--neighbourhood", "2")
        assert code == 0
        assert document["findings"] == []
        neighbourhood = document["neighbourhood"]
        assert neighbourhood["total"] == 3
        assert [(f["symbol"], f["class"]) for f in neighbourhood["shown"]] == [
            ("a", "NEIGHBOURHOOD"),
            ("b", "NEIGHBOURHOOD"),
        ]


class TestTreeIsUntouched:
    def test_the_working_tree_and_index_are_identical_after_a_run(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = (repo / PRIMITIVES).read_text(encoding="utf-8")
        _write(repo, PRIMITIVES, text + "\n\ndef never_called():\n    return 3\n")
        head = _commit(repo, "feat: add a helper")
        _write(repo, "src/pkg/core.py", "# an uncommitted edit\n")
        _write(repo, "src/pkg/staged.py", "STAGED = 1\n")
        _git(repo, "add", "src/pkg/staged.py")
        _write(repo, "untracked.py", "UNTRACKED = 1\n")

        def snapshot() -> tuple[str, str, str]:
            return (
                _git(repo, "status", "--porcelain", "--untracked-files=all"),
                _git(repo, "diff"),
                _git(repo, "diff", "--cached"),
            )

        before = snapshot()
        code, _ = _run(capsys, "master", head)
        assert code == 1
        assert snapshot() == before


class TestErrors:
    def test_an_unknown_revision_is_a_tool_error(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _delta().main(["master", "no-such-ref"]) == 2
        assert "not a commit" in capsys.readouterr().err

    def test_a_negative_neighbourhood_is_a_usage_error(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _delta().main(["master", "master", "--neighbourhood", "-1"]) == 2

    def test_a_missing_argument_is_a_usage_error(self, repo: Path) -> None:
        with pytest.raises(SystemExit) as raised:
            _delta().main(["master"])
        assert raised.value.code == 2

    def test_outside_a_repository_is_a_tool_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        outside = tmp_path / "plain"
        outside.mkdir()
        monkeypatch.chdir(outside)
        monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
        assert _delta().main(["HEAD", "HEAD"]) == 2


class TestAsAProcess:
    def test_the_exit_status_reaches_the_shell(self, repo: Path) -> None:
        text = (repo / PRIMITIVES).read_text(encoding="utf-8")
        _write(repo, PRIMITIVES, text + "\n\ndef never_called():\n    return 3\n")
        head = _commit(repo, "feat: add a helper")
        result = subprocess.run(
            [sys.executable, str(_SCRIPT), "master", head],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "GIT_CEILING_DIRECTORIES": str(repo.parent)},
        )
        assert result.returncode == 1, result.stderr
        assert f"{PRIMITIVES}:9 never_called function NEW_DEAD" in result.stdout


class TestShippedConfiguration:
    def test_the_vulture_table_is_one_the_vulture_cli_accepts(self) -> None:
        """An unknown key or a wrongly typed value makes `vulture` refuse the file."""
        from vulture import config

        config._check_input_config(_shipped_vulture_table())

    def test_agents_md_names_the_command(self) -> None:
        assert COMMAND in _AGENTS.read_text(encoding="utf-8")
