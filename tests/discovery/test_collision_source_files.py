"""Which file a strict collision record names for each claimant.

`contracts.md` § C5 / AC-6: the record names both definitions *and both source
files*. ``<entry_point>`` and ``<dynamic>`` say where a descriptor came from,
not which file defines it, so they are not files: the live callable is asked
first, through ``__wrapped__`` for a job class's proxy. The marker is kept only
when nothing names a file — the unreadable-source case D10 accepts.
"""

from __future__ import annotations

import inspect
from functools import wraps
from typing import Any

from functualize._discovery.collisions import strict_collision
from functualize._types.descriptors import JobDescriptor


def _method() -> None:
    """A stand-in for the method a job class's proxy wraps."""


class _Proxy:
    """Shaped like a job class's proxy: callable, not a function, wrapping one."""

    def __init__(self, wrapped: Any) -> None:
        self.__wrapped__ = wrapped

    def __call__(self) -> None:  # pragma: no cover - never called here
        return None


THIS_FILE = inspect.getsourcefile(_method)


def _claimant(source_file: str, function: Any) -> JobDescriptor:
    return JobDescriptor(
        name="pg.start",
        group="pg",
        function=function,
        source_file=source_file,
        python_name="start",
        owner_class="Postgres",
    )


def _files(*claimants: JobDescriptor) -> list[str]:
    record = strict_collision("pg.start", claimants)
    return [file for _, file in record.collision.claimants]


class TestTheFileARecordNames:
    def test_a_real_file_is_kept(self) -> None:
        assert _files(
            _claimant("/x/jobs/pg.py", None), _claimant("/y/pg.py", None)
        ) == [
            "/x/jobs/pg.py",
            "/y/pg.py",
        ]

    def test_an_entry_point_marker_yields_to_the_proxy_s_file(self) -> None:
        files = _files(
            _claimant("/x/jobs/pg.py", None),
            _claimant("<entry_point>", _Proxy(_method)),
        )

        assert files == ["/x/jobs/pg.py", THIS_FILE]

    def test_a_dynamic_marker_yields_to_a_wrapped_function_s_file(self) -> None:
        @wraps(_method)
        def wrapper() -> None: ...

        files = _files(_claimant("<dynamic>", wrapper), _claimant("/y/pg.py", None))

        assert files == [THIS_FILE, "/y/pg.py"]

    def test_the_marker_stays_when_no_file_is_knowable(self) -> None:
        """D10's case: an entry point whose source cannot be read."""
        files = _files(
            _claimant("/x/jobs/pg.py", None), _claimant("<entry_point>", None)
        )

        assert files == ["/x/jobs/pg.py", "<entry_point>"]
