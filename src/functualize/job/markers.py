"""CLI annotation markers for functualize job parameters — public door.

The implementations live in :mod:`functualize._types.cli_markers`, the same
split ``FromJob`` already uses (`_types/from_job.py`, re-exported from
``functualize.job``). The engine has to recognise a ``Stdin`` marker in order
to resolve stdin at execution time (run-request/T11), and "Internal never
imports public" forbids ``_engine`` reaching ``functualize.job``. A marker is a
*type*, so ``_types`` is where it belongs; this module stays as the name users
import.

Public API:
- ``Arg`` — mark a parameter as a positional CLI argument
- ``Option`` — mark a parameter as a named CLI option with optional short flag
- ``Stdin`` — mark a parameter as stdin-aware (reads from pipe when available)
"""

from __future__ import annotations

from functualize._types.cli_markers import Arg, Option, Stdin

__all__ = ["Arg", "Option", "Stdin"]
