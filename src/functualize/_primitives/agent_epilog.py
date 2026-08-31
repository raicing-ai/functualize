"""The `--help` block that tells an agent where the machine-readable surface is.

One builder, because there are two root groups. `func` builds its own in
`_cli/main.py`; a project's own `main.py` gets one from
`app/adapters/cli.py`. The block existed on the first only — and that is the
wrong one to have it on, since the skills tell an agent that `func` is often
not on PATH and to use the project's own entry point. So the surface an agent
actually runs was the surface with no pointer.

**Parametrised by the invoked program name**, not by a hardcoded `func`.
Telling someone running `./main.py` to type `func builtin info schema` is
advice they cannot follow. Click already knows what it was invoked as
(`ctx.find_root().info_name`), so the left column is always copy-pasteable.

Rendering rules the tests pin, and why:

- **Emitted verbatim, never re-wrapped.** It is a hand-aligned table; click's
  `wrap_text` reflows it into prose and destroys the columns.
- **Heading at the left margin, entries two columns in**, matching how
  `builtin` sits under `Commands:`. Click renders `epilog` inside
  `formatter.indentation()`, which puts the heading *under* the command list
  where it reads as another command.
- **Inside 72 columns**, since emitting verbatim means source width is the only
  thing standing between a narrow terminal and a mangled table. The description
  column is aligned against the widest *rendered* command rather than a
  constant, so the table survives both a short `func` and a longer program
  name; `epilog_width` lets a test assert the budget directly.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "AGENT_EPILOG_HEADING",
    "agent_epilog",
    "epilog_width",
    "write_agent_epilog",
]

#: Labelled, because an unlabelled paragraph after `Commands:` reads as a
#: continuation of it. The label says who the block is for, so a human skims
#: past it and an agent knows to stop.
AGENT_EPILOG_HEADING = "For AI agents:"

#: How far the entries are indented — two columns, matching how `builtin` sits
#: under `Commands:`.
_INDENT = "  "

#: `(command, description, prefixed)`. `prefixed` commands get the invoked
#: program name in front; the `export` line is a shell command in its own
#: right and takes none.
_ENTRIES: tuple[tuple[str, str, bool], ...] = (
    ("builtin info schema", "all commands, as JSON", True),
    ("builtin info schema --kind job", "jobs only", True),
    ("builtin info schema --kind builtin", "builtin commands only", True),
    ("builtin skills list", "skills for this version", True),
    ("export FUNCTUALIZE_CLI_OUTPUT=json", "make JSON the default", False),
)

#: The width the block must not exceed. Emitting verbatim means nothing will
#: re-wrap an over-long line for us, so this is the whole guard against a
#: mangled table on a narrow terminal. Pinned well inside 80 rather than at it.
#:
#: The tests import this rather than restating 72 — the constant and the
#: rendering that has to respect it belong together.
MAX_EPILOG_COLUMNS = 72


def _rendered(prog: str) -> list[tuple[str, str]]:
    """`(command, description)` with the program name already substituted."""
    return [
        (f"{prog} {command}" if prefixed else command, description)
        for command, description, prefixed in _ENTRIES
    ]


def agent_epilog(prog: str) -> str:
    """The block as click's `epilog`, with commands spelled for `prog`.

    `prog` is what the CLI was actually invoked as. Falls back to `func` when
    click reports nothing, which happens only outside a real invocation.

    **The descriptions are dropped rather than allowed to overflow.** With a
    hardcoded `func` the aligned table sat at exactly `MAX_EPILOG_COLUMNS`, so
    any longer entry point — `app.py`, `./scripts/tasks.py` — pushed it over,
    and a verbatim block that overflows is a table shredded across two lines.
    The commands are the part an agent needs; the descriptions are the part
    that can go.
    """
    prog = prog.strip() or "func"
    rendered = _rendered(prog)
    width = max(len(command) for command, _ in rendered)

    lines = [
        f"{_INDENT}{command.ljust(width)}  {description}"
        for command, description in rendered
    ]
    if max(len(line) for line in lines) > MAX_EPILOG_COLUMNS:
        lines = [f"{_INDENT}{command}" for command, _ in rendered]

    return "\n".join([AGENT_EPILOG_HEADING, *lines])


def epilog_width(prog: str) -> int:
    """Columns the widest rendered line occupies, for the narrow-terminal cap."""
    return max(len(line) for line in agent_epilog(prog).splitlines())


def write_agent_epilog(prog: str, formatter: Any) -> None:
    """Write the block to a click ``HelpFormatter``, verbatim.

    The one place the rendering rule lives, so the two root groups that need it
    (``func``'s in ``_cli/main.py`` and the adapter's in ``app/adapters/cli.py``)
    share the behaviour rather than a copied ``format_epilog``.

    ``formatter`` is duck-typed rather than imported: this module stays free of
    click so ``_primitives`` keeps its no-framework character, and so a caller
    on the lazy-boot path can reach the text without pulling click in.
    """
    formatter.write_paragraph()
    for line in agent_epilog(prog).splitlines():
        formatter.write(f"{line}\n")
