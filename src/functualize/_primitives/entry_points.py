"""One entry-point scan per process, shared by every discovery site.

`importlib.metadata.entry_points()` walks every installed distribution on
every call — the group argument filters the *result*, it does not narrow the
scan. Constructing a `FunctualizeApp` asks seven different questions of the
same unchanged metadata (plugins, domains, ai/state/tasks providers, format
and remote config providers), so a boot paid seven full walks of `sys.path`
to read one snapshot seven times.

Measured on a 215-distribution environment: 114.7 ms across the seven calls
out of 191 ms total construction. Collapsing them to one scan removes ~98 ms
of the ~115 ms, and every surface pays this cost — CLI, TUI, MCP, and the
direct-run path alike.

The snapshot is process-wide and deliberately never invalidated on its own:
entry points describe *installed* distributions, and nothing functualize does
installs a distribution into the running interpreter. A process that genuinely
needs to observe an install (a test that fakes one, most obviously) calls
`clear_entry_point_cache()`.

Lives in `_primitives/` (stdlib-only) because `_config`, `_discovery`, and
`_plugins` are peer-independent layers and each needs this — a shared cache in
any one of them would be an import edge the layer contracts forbid.
"""

from __future__ import annotations

import importlib.metadata
import threading
from importlib.metadata import EntryPoint

__all__ = ["clear_entry_point_cache", "entry_points"]

_lock = threading.Lock()
_snapshot: object | None = None


def entry_points(*, group: str) -> tuple[EntryPoint, ...]:
    """Return the entry points in ``group``, scanning the path at most once.

    Signature-compatible with the ``group=`` form of
    `importlib.metadata.entry_points`, which is the only form this project
    uses. Returns a tuple rather than the stdlib's view type so callers cannot
    mutate shared state, and so the result stays iterable more than once —
    the stdlib's return type has changed across 3.11–3.13 and callers should
    not have to care which one they are holding.

    Keyword-only, mirroring the stdlib, so a positional group cannot silently
    be read as something else.
    """
    global _snapshot
    with _lock:
        if _snapshot is None:
            # No-arg scan, then select per group. `.select()` is the one
            # spelling that behaves the same on 3.11 (SelectableGroups) and
            # 3.12+ (EntryPoints), and it raises no DeprecationWarning on
            # either — unlike the mapping interface it replaced.
            _snapshot = importlib.metadata.entry_points()
        snapshot = _snapshot
    return tuple(snapshot.select(group=group))  # type: ignore[attr-defined]


def clear_entry_point_cache() -> None:
    """Drop the snapshot so the next lookup rescans the path.

    For processes that change what is installed, and for tests that fake a
    distribution. Cheap to call when the cache is already empty.
    """
    global _snapshot
    with _lock:
        _snapshot = None
