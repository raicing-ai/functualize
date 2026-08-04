"""Static completion scripts — the shell half of the direnv model (T44b).

Consumes :class:`CompletionData` (T44a) and emits a self-contained bash, zsh, or
fish script. The hard rule, and the one a test greps for: **the emitted script
contains no `func` and no `__complete` invocation**. A completion that shells
out to Python on every TAB pays the ~400ms warm-boot cost per keystroke; this
bakes the word lists in as literals, so TAB is pure `compgen`/`compadd`/`complete
-c` and costs nothing measurable. The price is that the script is a snapshot —
regenerate it when jobs change — which is exactly the direnv trade and is what
the source-file hook is for.

The word lists come pre-computed and partition-correct from T44a, so nothing
here decides what a flag *is*; this module only turns a `{path: words}` map into
the shell each shell wants. Values are quoted defensively even though they are
generated (a job name is a canonical identifier), because a script that builds
a shell case-statement from data is a script one careless field away from
injection, and the discipline is cheaper than the audit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from functualize._cli.completions.data import CompletionData

__all__ = ["SHELLS", "render_completion_script"]

SHELLS: tuple[str, ...] = ("bash", "zsh", "fish")
"""The shells `func builtin shell-init` can emit for."""


def render_completion_script(data: CompletionData, shell: str) -> str:
    """Render a static completion script for ``shell`` from ``data`` (T44b)."""
    if shell == "bash":
        return _render_bash(data)
    if shell == "zsh":
        return _render_zsh(data)
    if shell == "fish":
        return _render_fish(data)
    raise ValueError(f"unsupported shell {shell!r}; choose one of {', '.join(SHELLS)}")


#: Every bash/zsh associative-array key is prefixed with this, because the
#: top-level path is the empty string and bash rejects an empty array subscript
#: (`_func_tree['']` → "bad array subscript"). A fixed non-empty prefix sidesteps
#: it without a special case, and cannot collide — no command path starts with
#: it. fish needs none of this: it matches with `complete -n` conditions, not
#: array lookups.
_KEY_PREFIX = ":"


def _sh_squote(value: str) -> str:
    """POSIX single-quote a value for bash/zsh — safe for arbitrary content."""
    return "'" + value.replace("'", "'\\''") + "'"


# ── bash ────────────────────────────────────────────────────────────────────


def _render_bash(data: CompletionData) -> str:
    """A bash completion driven by an associative array of word lists.

    The completer walks the words before the cursor, joins them into the same
    space-path key T44a produced, and offers ``$_func_tree[$key]``. A flag whose
    previous word is a known enum offers that flag's choices instead. All pure
    bash builtins — no subprocess.
    """
    lines: list[str] = [
        "# functualize completion (bash) — generated, do not edit.",
        "# Regenerate with: func builtin shell-init bash --install",
        "declare -A _func_tree",
        "declare -A _func_choices",
    ]
    for key in data.paths():
        words = " ".join(data.command_tree[key])
        lines.append(f"_func_tree[{_sh_squote(_KEY_PREFIX + key)}]={_sh_squote(words)}")
    for job_path, choices in sorted(data.flag_choices.items()):
        for flag, values in sorted(choices.items()):
            ckey = f"{_KEY_PREFIX}{job_path}\x1f{flag}"
            lines.append(
                f"_func_choices[{_sh_squote(ckey)}]={_sh_squote(' '.join(values))}"
            )

    lines.append(_BASH_COMPLETER)
    lines.append("complete -F _func_complete func")
    return "\n".join(lines) + "\n"


_BASH_COMPLETER = r"""
_func_complete() {
    local cur prev words_before path key cand
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    # The path is every completed word after `func`, minus the one being typed.
    local -a segs=()
    local i
    for ((i=1; i<COMP_CWORD; i++)); do
        case "${COMP_WORDS[i]}" in
            -*) ;;                      # flags do not extend the command path
            *) segs+=("${COMP_WORDS[i]}") ;;
        esac
    done
    path=":${segs[*]}"

    # If the previous word is a flag with known choices, offer those.
    local ckey="${path}"$'\x1f'"${prev}"
    if [[ -n "${_func_choices[$ckey]:-}" ]]; then
        cand="${_func_choices[$ckey]}"
        COMPREPLY=( $(compgen -W "${cand}" -- "${cur}") )
        return 0
    fi

    cand="${_func_tree[$path]:-}"
    COMPREPLY=( $(compgen -W "${cand}" -- "${cur}") )
    return 0
}
"""


# ── zsh ─────────────────────────────────────────────────────────────────────


def _render_zsh(data: CompletionData) -> str:
    """A zsh completion over the same word-list map, using ``compadd``.

    Written to be `source`-able directly (it calls ``compdef``), matching how
    the bash and fish scripts are used — the source-file hook, not a file
    dropped in ``$fpath``.
    """
    lines: list[str] = [
        "# functualize completion (zsh) — generated, do not edit.",
        "# Regenerate with: func builtin shell-init zsh --install",
        "typeset -gA _func_tree",
        "typeset -gA _func_choices",
    ]
    for key in data.paths():
        words = " ".join(data.command_tree[key])
        lines.append(f"_func_tree[{_sh_squote(_KEY_PREFIX + key)}]={_sh_squote(words)}")
    for job_path, choices in sorted(data.flag_choices.items()):
        for flag, values in sorted(choices.items()):
            ckey = f"{_KEY_PREFIX}{job_path}\x1f{flag}"
            lines.append(
                f"_func_choices[{_sh_squote(ckey)}]={_sh_squote(' '.join(values))}"
            )

    lines.append(_ZSH_COMPLETER)
    lines.append("compdef _func_complete func")
    return "\n".join(lines) + "\n"


_ZSH_COMPLETER = r"""
_func_complete() {
    local -a segs
    local w path ckey
    # words[1] is `func`; words[CURRENT] is the token being typed.
    local i
    for (( i = 2; i < CURRENT; i++ )); do
        w="${words[i]}"
        case "$w" in
            -*) ;;
            *) segs+=("$w") ;;
        esac
    done
    path=":${(j: :)segs}"

    local prev="${words[CURRENT-1]}"
    ckey="${path}"$'\x1f'"${prev}"
    if [[ -n "${_func_choices[$ckey]:-}" ]]; then
        compadd -- ${=_func_choices[$ckey]}
        return 0
    fi
    compadd -- ${=_func_tree[$path]:-}
    return 0
}
"""


# ── fish ────────────────────────────────────────────────────────────────────


def _render_fish(data: CompletionData) -> str:
    """A fish completion as a set of ``complete -c func`` conditions.

    fish has no path-indexed builtin like bash's assoc array, so each command
    path becomes a ``complete`` line guarded by ``__fish_func_path``, a helper
    that reconstructs the current space-path from the command line. Still zero
    subprocess-to-Python: the helper is pure fish string work.
    """
    lines: list[str] = [
        "# functualize completion (fish) — generated, do not edit.",
        "# Regenerate with: func builtin shell-init fish --install",
        _FISH_PATH_HELPER,
    ]
    for key in data.paths():
        words = data.command_tree[key]
        cond = _fish_cond(key)
        for word in words:
            lines.append(
                f"complete -c func -f -n {_fish_squote(cond)} -a {_fish_squote(word)}"
            )
    for job_path, choices in sorted(data.flag_choices.items()):
        for flag, values in sorted(choices.items()):
            cond = (
                f"__fish_func_path {_fish_arg(job_path)}; and __fish_prev_arg_is {flag}"
            )
            for value in values:
                lines.append(
                    f"complete -c func -f -n {_fish_squote(cond)} "
                    f"-a {_fish_squote(value)}"
                )
    return "\n".join(lines) + "\n"


_FISH_PATH_HELPER = r"""
function __fish_func_path
    # True when the completed command path (tokens after `func`, minus flags and
    # the token being typed) equals the arguments given.
    set -l tokens (commandline -opc)
    set -l segs
    for tok in $tokens[2..-1]
        switch $tok
            case '-*'
            case '*'
                set -a segs $tok
        end
    end
    set -l want (string join ' ' $argv)
    set -l have (string join ' ' $segs)
    test "$want" = "$have"
end

function __fish_prev_arg_is
    set -l tokens (commandline -opc)
    test (count $tokens) -ge 1; and test $tokens[-1] = $argv[1]
end
""".strip()


def _fish_cond(key: str) -> str:
    """The `-n` condition matching command path ``key`` (``""`` = top level)."""
    if not key:
        return "__fish_func_path"
    return f"__fish_func_path {_fish_arg(key)}"


def _fish_arg(key: str) -> str:
    """Split a space-path into space-separated, individually-quoted fish args."""
    return " ".join(_fish_squote(seg) for seg in key.split(" "))


def _fish_squote(value: str) -> str:
    """Single-quote for fish (backslash-escapes ``\\`` and ``'``)."""
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return "'" + escaped + "'"
