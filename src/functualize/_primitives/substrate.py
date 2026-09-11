"""One JSON file per key — today's storage, behind the port.

`store-substrate`/T1.

The port itself is :class:`~functualize._types.protocols.StoreSubstrate`, in
`_types/` with the other ports. This module holds the implementation that ships:
the one that reproduces what the stores do today, so T2 can move them onto the
port without changing anything observable.

It is the **baseline**, not the good one. Its whole job is to be invisible — same
paths, same `flock` sidecars, same atomic replace — so that no user on a laptop
notices this feature happened (spec AC-7).

## It honours `expect` for real

The tempting shortcut is for the filesystem implementation to ignore
compare-and-swap, since `flock` already gives it mutual exclusion. That would
ship a parameter no implementation honours and no test can fail on — the shape
this branch keeps finding and deleting.

So the revision is derived from the **bytes on disk**: a write with `expect`
set re-reads and refuses if the content has moved. No on-disk format changes, no
sidecar, and the refusal is reachable — a second writer between a caller's read
and its write genuinely gets False.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any

from functualize._primitives.fresh_format import atomic_write_json, file_lock
from functualize._types.errors import SubstrateUnreadableError
from functualize._types.protocols import Stored

__all__ = ["JsonFileSubstrate"]


def _revision_of(raw: bytes) -> int:
    """An opaque revision token for exactly these bytes.

    A content hash rather than an mtime: mtime granularity is coarse enough on
    some filesystems that two writes inside the same tick are indistinguishable,
    which is precisely the window compare-and-swap exists to close. Truncated to
    64 bits because the port types a revision as an int and callers only ever
    compare it.
    """
    return int.from_bytes(hashlib.blake2b(raw, digest_size=8).digest(), "big")


class JsonFileSubstrate:
    """One JSON file per key, under a directory. Today's behaviour, exactly."""

    __slots__ = ("_root",)

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        """The directory documents live under."""
        return self._root

    def path_for(self, key: str) -> Path:
        """The file a key maps to.

        Rejects a key that could escape the root rather than sanitising it: such
        a key is a bug at its source and quietly rewriting it would hide that.
        The same call `scope_state_path` makes for scope ids.
        """
        if not key or key.startswith("/") or ".." in key.split("/"):
            raise ValueError(
                f"substrate key {key!r} must be a relative document name with "
                f"no '..' segments"
            )
        return self._root / f"{key}.json"

    def _load(self, key: str) -> Stored | None:
        path = self.path_for(key)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise SubstrateUnreadableError(key, str(exc)) from exc
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise SubstrateUnreadableError(key, str(exc)) from exc
        if not isinstance(data, dict):
            raise SubstrateUnreadableError(
                key, f"expected an object, found {type(data).__name__}"
            )
        return Stored(data=data, revision=_revision_of(raw))

    def read(self, key: str) -> Stored | None:
        return self._load(key)

    def write(
        self, key: str, payload: dict[str, Any], *, expect: int | None = None
    ) -> bool:
        """Replace the document, refusing when ``expect`` no longer matches.

        **Does not take the lock**, and that is deliberate rather than an
        omission. `file_lock` opens a fresh descriptor and `flock`s it, so a
        second acquire inside a caller that already holds the key spins for ten
        seconds, warns that concurrent writers can now lose each other, and
        proceeds — a self-inflicted stall on the ordinary path, since a store
        doing read-modify-write holds the lock across both halves.

        So the division is: :meth:`lock` is how a caller gets exclusion, and
        ``expect`` is how a caller gets it back from a substrate that has none
        to give. Under the caller's lock the compare here is exact; a
        compare-and-swap backend does it server-side. Passing ``expect``
        *without* holding the lock on this implementation narrows the window
        rather than closing it.
        """
        if expect is not None:
            try:
                current = self._load(key)
            except SubstrateUnreadableError:
                # Unreadable is not the revision the caller saw, so the compare
                # fails. Refusing is right: whatever is there was not written by
                # the caller's read-modify-write.
                return False
            if current is None or current.revision != expect:
                return False
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, payload)
        return True

    @contextmanager
    def lock(self, *keys: str) -> Iterator[None]:
        """Per-file `flock` sidecars, **acquired in sorted key order**.

        Sorting keeps the many-lock implementation from deadlocking against
        itself: two callers asking for the same set in different orders still
        acquire in one order. It does *not* help against a caller that takes one
        lock, does something, then takes another — that inversion is only
        removed by a substrate with a single lock, which is what the port makes
        expressible.

        **Not re-entrant**, because `flock` here is not: a nested acquire on
        the same key opens a second descriptor and spins until the ten-second
        timeout. :meth:`write` therefore does not take it — see there.
        """
        with ExitStack() as stack:
            for key in sorted(set(keys)):
                path = self.path_for(key)
                path.parent.mkdir(parents=True, exist_ok=True)
                stack.enter_context(file_lock(path))
            yield
