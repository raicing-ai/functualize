"""Throwaway storage for engines built outside a boot.

``JobExecutionEngine`` requires the store and the substrate it was built over
(FUN-17 spec AC-4, T12): construction without storage is impossible, so every
test that builds an engine — including the ones whose subject is the DAG, the
middleware chain or DI resolution, and which never read a document — has to
name one. This is that name.

It is deliberately the *filesystem* substrate in a private temporary directory
rather than a mock: a test that unexpectedly reads or writes storage meets a
real store that is empty, instead of an object whose behaviour under an
unplanned call is undefined. The directory is created per engine and never
cleaned up — it is empty, and a test that leaves something in it has said
something about a call it did not mean to make.

FUN-17/T13 and T14 move the recorders onto the :class:`RuntimeStore` port;
when they do, this helper is the one place a test-side store gets swapped.
"""

from __future__ import annotations

import itertools
import tempfile
from pathlib import Path

from functualize._primitives.document_store import DocumentRuntimeStore
from functualize._primitives.substrate import JsonFileSubstrate

__all__ = ["engine_storage"]

_MADE = itertools.count()


def engine_storage() -> dict[str, object]:
    """``runtime_store`` and ``substrate`` as a mapping, for ``**`` splatting.

    Splatted at the call site — ``JobExecutionEngine(..., **engine_storage())``
    — so a test that does not care which storage it hands over spells it once
    rather than three lines of path plumbing. A test that *does* care builds
    its own, and should: this one is for the engines whose subject is
    somewhere else entirely.
    """
    root = Path(tempfile.mkdtemp(prefix=f"fun17-engine-storage-{next(_MADE)}-"))
    substrate = JsonFileSubstrate(root)
    return {"runtime_store": DocumentRuntimeStore(substrate), "substrate": substrate}
