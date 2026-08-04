"""CLI annotation markers for functualize job parameters.

These markers control how function parameters appear on the CLI.
Non-CLI adapters (Lambda, HTTP, MCP) ignore these markers entirely —
they see only the base type and any Field constraints.

Public API:
- ``Arg`` — mark a parameter as a positional CLI argument
- ``Option`` — mark a parameter as a named CLI option with optional short flag
- ``Stdin`` — mark a parameter as stdin-aware (reads from pipe when available)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Arg:
    """Mark a parameter as a positional CLI argument.

    Non-CLI adapters ignore this marker — they see only the base type.

    Usage::

        from typing import Annotated
        from functualize.job import Arg

        def deploy(target: Annotated[str, Arg(help="Deploy target")]):
            ...
    """

    help: str | None = None
    metavar: str | None = None
    show_default: bool = True


@dataclass(frozen=True, slots=True, init=False)
class Option:
    """Mark a parameter as a named CLI option with optional short flag.

    Non-CLI adapters ignore this marker — they see only the base type.

    Usage::

        from typing import Annotated
        from functualize.job import Option

        def deploy(target: Annotated[str, Option("-t", "--target", help="Deploy target")]):
            ...

        # Short flag only — long flag derived from param name:
        def deploy(verbose: Annotated[bool, Option("-v")]):
            ...
    """

    short: str | None
    long: str | None
    help: str | None
    hidden: bool
    envvar: str | None

    def __init__(
        self,
        *args: str,
        help: str | None = None,
        hidden: bool = False,
        envvar: str | None = None,
    ) -> None:
        """Accept positional strings as flag names: Option("-t", "--target").

        Positional arg detection:
        - Single dash + one char (e.g. ``-t``) → short flag
        - Double dash + name (e.g. ``--target``) → long flag
        - Two positional args: detect by dash count, assign accordingly

        Args:
            *args: Flag name strings (short like ``-t``, long like ``--target``).
            help: Help text for the option.
            hidden: Whether to hide this option from --help output.
            envvar: Environment variable name to read as fallback.
        """
        short: str | None = None
        long: str | None = None

        for arg in args:
            if arg.startswith("--"):
                long = arg
            elif arg.startswith("-") and len(arg) == 2:
                short = arg
            else:
                # Not a recognized short flag format — treat as long
                long = arg

        object.__setattr__(self, "short", short)
        object.__setattr__(self, "long", long)
        object.__setattr__(self, "help", help)
        object.__setattr__(self, "hidden", hidden)
        object.__setattr__(self, "envvar", envvar)


@dataclass(frozen=True, slots=True)
class Stdin:
    """Mark a parameter as stdin-aware.

    When stdin is piped and no explicit CLI value provided, reads from stdin.
    Flag value always wins over stdin (explicit > implicit).

    Usage::

        from typing import Annotated
        from functualize.job import Stdin

        def transform(data: Annotated[str, Stdin(flag="--data", help="Input data")]):
            ...

        # Pipe usage: echo "hello" | func transform
    """

    flag: str | None = None
    help: str | None = None
    encoding: str = "utf-8"
