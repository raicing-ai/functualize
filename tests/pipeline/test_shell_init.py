"""The emitted completion scripts — static, valid, and Python-free (T44b).

The one non-negotiable, greppable in every emitted script: **no `func` and no
`__complete` invocation**. That is the whole design — a completion that shelled
out to Python on each TAB would pay the ~400ms warm boot per keystroke. The
word lists are baked in as literals; TAB is pure shell builtins.

Beyond that, the scripts must be syntactically valid for their shell and must
actually complete the right words. Syntax is checked with each shell's `-n`
(skipped when the shell is absent); the functional bash check sources the script
and drives `_func_complete` with a simulated `COMP_WORDS`, which is the only way
to prove the word lists are wired to the completer and not merely present.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from functualize._cli.completions.data import CompletionData
from functualize._cli.completions.shell_init import SHELLS, render_completion_script

# A hand-built fixture: a group `deploy` with a job `run` that has own flags and
# an inherited enum group-flag. Independent of extraction (tested separately),
# so a failure here points at emission, not at the data.
_DATA = CompletionData(
    command_tree={
        "": ["builtin", "deploy"],
        "deploy": ["run"],
        "deploy run": ["--image", "--env", "-e"],
        "builtin": ["cache", "history"],
        "builtin cache": ["show", "clear"],
    },
    flag_choices={"deploy run": {"--env": ["dev", "prod"]}},
)


@pytest.mark.parametrize("shell", SHELLS)
def test_no_python_callback_in_the_emitted_script(shell: str) -> None:
    """The greppable rule. A `func`/`__complete` call would mean a subprocess
    per TAB — the design's entire point is that there is none."""
    script = render_completion_script(_DATA, shell)

    for line in script.splitlines():
        code = line.split("#", 1)[0]  # comments may mention the regen command
        assert "__complete" not in code
        assert "func " not in code or "_func" in code  # `_func_complete` is ours


@pytest.mark.parametrize("shell", SHELLS)
def test_the_word_lists_are_present_as_literals(shell: str) -> None:
    script = render_completion_script(_DATA, shell)

    assert "deploy" in script
    assert "--image" in script
    assert "dev" in script and "prod" in script


def test_an_unknown_shell_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported shell"):
        render_completion_script(_DATA, "powershell")


class TestSyntaxIsValid:
    @pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
    def test_bash(self) -> None:
        script = render_completion_script(_DATA, "bash")
        result = subprocess.run(
            ["bash", "-n"], input=script, text=True, capture_output=True
        )
        assert result.returncode == 0, result.stderr

    @pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh not installed")
    def test_zsh(self) -> None:
        script = render_completion_script(_DATA, "zsh")
        result = subprocess.run(
            ["zsh", "-n"], input=script, text=True, capture_output=True
        )
        assert result.returncode == 0, result.stderr

    @pytest.mark.skipif(shutil.which("fish") is None, reason="fish not installed")
    def test_fish(self) -> None:
        script = render_completion_script(_DATA, "fish")
        result = subprocess.run(
            ["fish", "-n", "/dev/stdin"], input=script, text=True, capture_output=True
        )
        assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
class TestBashActuallyCompletes:
    """Source the script and drive the completer — the only proof the literals
    are wired to `_func_complete` rather than merely emitted."""

    @staticmethod
    def _complete(words: list[str]) -> list[str]:
        script = render_completion_script(_DATA, "bash")
        # Build COMP_WORDS from the given tokens, run the completer, print the
        # reply one per line.
        driver = (
            f"{script}\n"
            f"COMP_WORDS=({' '.join(_bash_quote(w) for w in words)})\n"
            "COMP_CWORD=$(( ${#COMP_WORDS[@]} - 1 ))\n"
            "COMPREPLY=()\n"
            "_func_complete\n"
            'printf "%s\\n" "${COMPREPLY[@]}"\n'
        )
        out = subprocess.run(["bash", "-c", driver], text=True, capture_output=True)
        return [line for line in out.stdout.splitlines() if line]

    def test_top_level(self) -> None:
        assert set(self._complete(["func", ""])) == {"builtin", "deploy"}

    def test_group_children(self) -> None:
        assert self._complete(["func", "deploy", ""]) == ["run"]

    def test_job_flags(self) -> None:
        assert "--image" in self._complete(["func", "deploy", "run", ""])

    def test_flag_prefix_narrows(self) -> None:
        assert self._complete(["func", "deploy", "run", "--im"]) == ["--image"]

    def test_enum_choices_after_a_flag(self) -> None:
        assert set(self._complete(["func", "deploy", "run", "--env", ""])) == {
            "dev",
            "prod",
        }

    def test_builtin_subcommands(self) -> None:
        assert set(self._complete(["func", "builtin", ""])) == {"cache", "history"}


def _bash_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"
