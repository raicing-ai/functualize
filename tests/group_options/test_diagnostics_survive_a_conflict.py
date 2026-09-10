"""A rule that stops `func builtin why` stops the answer to the question it raises.

Two files declaring `GroupOptions` for one group is a project-wide
contradiction, and it is fatal: the framework cannot know which declaration's
flags `func deploy --env prod` means, and the only alternative to stopping is
serving one of them silently. `test_conflict_is_reported.py` is where that is
asserted.

It was fatal for the *diagnostics* too — `func builtin why`, `builtin info` and
`builtin cache rebuild` all exited 2 with an empty stdout. So the command whose
whole purpose is answering "why is my job missing?" could not answer when the
answer was the conflict, and the documented way to clear a bad cache died before
reaching its own scan (adj M4, maintainer decision D-4).

The split is by **command, not by door**: `builtin parallel` runs jobs and stays
fatal, because the rule is about not running under an ambiguity rather than
about which entry point was used. `DIAGNOSTIC_BUILTINS` is the list, and
`test_the_exempt_set_is_real` keeps it from naming something that does not exist.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from functualize._cli.builtins import BUILTIN_COMMANDS, DIAGNOSTIC_BUILTINS

_GROUP_MODULE = '''\
from typing import Annotated

from functualize.job import GroupOptions, Option


class DeployOptions(GroupOptions, group="deploy"):
    """Deploy-level flags."""

    env: Annotated[str, Option("-e", help="Target environment")] = "staging"
'''

_DUP_MODULE = '''\
from typing import Annotated

from functualize.job import GroupOptions, Option


class OtherDeployOptions(GroupOptions, group="deploy"):
    """A second declaration of the same group."""

    region: Annotated[str, Option("-r", help="Region")] = "eu"
'''

_HEALTHY = 'def hello() -> str:\n    """Say hi."""\n    return "hi"\n'

#: `ExitCode.USAGE`.
_USAGE = 2


@pytest.fixture
def conflicting(tmp_path: Path, project_tree) -> Path:
    return project_tree(
        jobs={"_group.py": _GROUP_MODULE, "_dup.py": _DUP_MODULE, "hello.py": _HEALTHY}
    )


def _func(args: list[str], cwd: Path, cache: Path) -> subprocess.CompletedProcess[str]:
    """Run the real console script — this is about process exit codes."""
    import os

    script = Path(sys.executable).parent / "func"
    return subprocess.run(
        [str(script), *args],
        cwd=cwd,
        env={**os.environ, "XDG_CACHE_HOME": str(cache)},
        capture_output=True,
        text=True,
        timeout=120,
    )


class TestTheDiagnosticsRun:
    def test_info_reports_the_conflict_instead_of_dying(
        self, conflicting: Path, tmp_path: Path
    ) -> None:
        result = _func(["builtin", "info"], conflicting, tmp_path / "c1")

        assert result.returncode == 0, result.stderr
        assert "Discovery Failures" in result.stdout
        assert "deploy" in result.stdout

    def test_info_json_carries_it_in_the_adr_018_channel(
        self, conflicting: Path, tmp_path: Path
    ) -> None:
        """`discovery_failures` is the list, and it was always populated — what
        was missing was any command that lived long enough to render it."""
        result = _func(["builtin", "info", "--json"], conflicting, tmp_path / "c2")

        assert result.returncode == 0, result.stderr
        failures = json.loads(result.stdout)["discovery_failures"]
        assert [f["error_type"] for f in failures] == ["GroupOptionsConflictError"]

    def test_why_answers_for_a_job_the_conflict_took_out(
        self, conflicting: Path, tmp_path: Path
    ) -> None:
        """`web` lives in a contested file, so it is gone — and `why` says why.

        It used to print `KeyError: "Job 'web' not found in engine registry"`,
        which is the exception's repr rather than an answer.
        """
        result = _func(["builtin", "why", "web"], conflicting, tmp_path / "c3")

        combined = result.stdout + result.stderr
        assert "KeyError" not in combined, combined
        assert "deploy" in combined or "discovery problem" in combined, combined

    def test_cache_rebuild_reaches_its_own_scan(
        self, conflicting: Path, tmp_path: Path
    ) -> None:
        """The documented way to clear a bad cache died before running."""
        result = _func(["builtin", "cache", "rebuild"], conflicting, tmp_path / "c4")

        assert result.returncode == 0, result.stderr
        assert "rebuilt" in result.stdout.lower(), result.stdout


class TestEverythingElseStaysFatal:
    @pytest.mark.parametrize(
        "args",
        [
            pytest.param(["hello"], id="a-job"),
            pytest.param(["builtin", "parallel", "hello"], id="builtin-parallel"),
            pytest.param(["builtin", "history"], id="a-non-diagnostic-builtin"),
        ],
    )
    def test_it_exits_usage_with_the_rendered_error(
        self, args: list[str], conflicting: Path, tmp_path: Path
    ) -> None:
        result = _func(args, conflicting, tmp_path / "".join(args))

        assert result.returncode == _USAGE, (result.stdout, result.stderr)
        assert "declared exactly once" in result.stderr, result.stderr

    def test_parallel_is_deliberately_not_exempt(self) -> None:
        """Spelled out because it is the judgement call in the split.

        `builtin parallel` reaches the same door as the diagnostics, and it
        **runs jobs**. Exempting the door rather than the command would let a
        fan-out run under an ambiguity the framework refused to resolve.
        """
        assert "parallel" not in DIAGNOSTIC_BUILTINS


class TestTheExemptSetIsReal:
    def test_every_exempt_name_is_a_builtin(self) -> None:
        """A name that is not a builtin exempts nothing and reads as if it did."""
        known = {command.name for command in BUILTIN_COMMANDS}

        assert known >= DIAGNOSTIC_BUILTINS, DIAGNOSTIC_BUILTINS - known

    def test_the_set_is_not_empty(self) -> None:
        """The falsifier for every test above: an empty set exempts nothing,
        and `TestEverythingElseStaysFatal` would still pass."""
        assert DIAGNOSTIC_BUILTINS


def test_a_healthy_project_is_unaffected(project_tree, tmp_path: Path) -> None:
    """The diagnostics are not a second code path — they run the same boot.

    Asserted on the answer rather than the exit code: `func builtin why` exits
    with the *verdict's* code, and a job with no `@job` declaration is `unknown`
    → 2 whether or not anything is wrong with the project. Using that number
    here would pin a fact about `why`'s own vocabulary in a file about group
    conflicts.
    """
    root = project_tree(jobs={"hello.py": _HEALTHY})

    result = _func(["builtin", "why", "hello"], root, tmp_path / "clean")

    assert "hello" in result.stdout
    assert "WOULD RUN" in result.stdout, result.stdout
    assert "discovery problem" not in result.stdout, result.stdout
    assert result.stderr == "", result.stderr


class TestWhichCommandTheArgsName:
    """`_diagnostic_scope` reads the family positionally, so pin the reading.

    It cannot ask click: `cli_app`'s only child is `builtin`, so
    `ctx.invoked_subcommand` is always `"builtin"` and the family is one level
    deeper. And it cannot wait for a callback, because the app boots inside
    `FunctualizeApp.__init__` — by the time anything could ask, the boot that
    would have exited has happened. So it reads `effective_args`, which
    `detect_mode` has already stripped of the pre-boot globals.
    """

    @staticmethod
    def _is_diagnostic(args: list[str]) -> bool:
        import contextlib

        from functualize._cli.main import _diagnostic_scope

        return not isinstance(_diagnostic_scope(args), contextlib.nullcontext)

    @pytest.mark.parametrize(
        "args",
        [
            pytest.param(["builtin", "why", "hello"], id="why"),
            pytest.param(["builtin", "info"], id="info-bare"),
            pytest.param(["builtin", "info", "--json"], id="info-with-a-flag"),
            pytest.param(["builtin", "cache", "rebuild"], id="cache-rebuild"),
            pytest.param(["builtin", "self", "doctor"], id="self-doctor"),
        ],
    )
    def test_a_diagnostic_is_recognised(self, args: list[str]) -> None:
        assert self._is_diagnostic(args)

    @pytest.mark.parametrize(
        "args",
        [
            pytest.param(["builtin", "parallel", "a", "b"], id="parallel"),
            pytest.param(["builtin", "history"], id="history"),
            pytest.param(["builtin", "workflow", "resume", "s"], id="workflow"),
            pytest.param(["builtin"], id="bare-builtin"),
            pytest.param(["builtin", "--help"], id="only-a-flag-after-builtin"),
            pytest.param(["hello"], id="a-job"),
            pytest.param([], id="nothing"),
        ],
    )
    def test_everything_else_is_not(self, args: list[str]) -> None:
        assert not self._is_diagnostic(args)

    def test_a_flag_before_the_family_does_not_become_the_family(self) -> None:
        """The first non-flag token after `builtin` is the family.

        Taking `effective_args[index + 1]` blindly would read a flag as the
        command name and exempt nothing — silently, which is the failure mode
        this whole decision was about.
        """
        assert self._is_diagnostic(["builtin", "--no-color", "why", "hello"])


class TestHelpNeverDiesOfAConflict:
    """`--help` prints and stops. It runs nothing, so nothing is ambiguous.

    `func builtin why --help` exited 2 with an empty stdout: a user with a
    broken project could not read the manual for the command that would explain
    it. The exemption on this route is unconditional rather than by command —
    `builtin history --help` is exempt too — because the rule is about not
    *running* under an ambiguity, and this path runs nothing.
    """

    @pytest.mark.parametrize(
        "args",
        [
            pytest.param(["builtin", "why", "--help"], id="a-diagnostic"),
            pytest.param(["builtin", "history", "--help"], id="a-non-diagnostic"),
            pytest.param(["builtin", "--help"], id="the-builtin-root"),
            pytest.param(["--help"], id="top-level"),
        ],
    )
    def test_it_prints(
        self, args: list[str], conflicting: Path, tmp_path: Path
    ) -> None:
        result = _func(args, conflicting, tmp_path / "h".join(args))

        assert result.returncode == 0, result.stderr
        assert "Usage" in result.stdout or "Commands" in result.stdout, result.stdout
        assert "declared exactly once" not in result.stderr, result.stderr
