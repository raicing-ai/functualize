"""Unix-style arguments: positional args, short flags, and stdin markers.

This module demonstrates the Arg(), Option(), and Stdin() annotation markers
from the cli-unix-compatibility spec. It tests how the TUI displays and handles:
- Positional arguments (shown as [arg] in the config table)
- Named options with short flags (shown as name/-s)
- Stdin-aware parameters (shown as [stdin] in the config table)

Expected TUI behavior:
- "say" has 1 positional arg (name) and 1 flag (--greeting/-g)
  → config table shows: ○ [arg]name*    ● greeting/-g = hello (default)
- "transform" has a stdin marker (--data flag, stdin fallback) + format flag
  → config table shows: ○ [stdin]data*    · format/-f
  → `echo "hi" | func transform -f title` reads data from the pipe;
    an explicit `--data` value always wins over stdin
- "ship" mixes positional + option + plain params
  → tests all three kinds together

Run: func (from the showcase directory)
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from functualize.job import Arg, Option, RunContext, Stdin


def say(
    name: Annotated[str, Arg(help="Person to greet")],
    greeting: Annotated[str, Option("-g", help="Greeting phrase")] = "hello",
    rc: RunContext = None,  # type: ignore[assignment]
) -> str:
    """Greet someone (1 positional arg, 1 option with short flag)."""
    msg = f"{greeting}, {name}!"
    if rc:
        rc.log(msg)
    return msg


def transform(
    data: Annotated[str, Stdin(flag="--data", help="Input data to transform")],
    format: Annotated[str, Option("-f", help="Output format")] = "upper",
    rc: RunContext = None,  # type: ignore[assignment]
) -> str:
    """Transform input data (positional + option)."""
    if format == "upper":
        result = data.upper()
    elif format == "lower":
        result = data.lower()
    elif format == "title":
        result = data.title()
    else:
        result = data
    if rc:
        rc.log(f"Transformed ({format}): {result}")
    return result


def ship(
    target: Annotated[str, Arg(help="Deployment target environment")],
    image: Annotated[str, Option("-i", "--image", help="Container image tag")],
    replicas: Annotated[
        int, Option("-r", help="Number of replicas"), Field(ge=1, le=20)
    ] = 3,
    dry_run: Annotated[
        bool, Option("--dry-run", help="Preview without applying")
    ] = False,
    rc: RunContext = None,  # type: ignore[assignment]
) -> str:
    """Ship with mixed positional + options (tests full parameter classification)."""
    action = "DRY RUN" if dry_run else "Shipping"
    msg = f"{action}: {image} → {target} x{replicas}"
    if rc:
        rc.log(msg)
    return msg
