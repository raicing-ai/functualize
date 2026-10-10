"""Relational retention, applied at prepare time instead of on step writes.

The count and age horizons come from the same policy as the document rings.
Only evictable scopes and terminal runs are eligible under the default policy.
Foreign keys cascade their database children; artifact blobs are outside this
database and this module never touches their URIs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from functualize._types.lifecycle import RUN, SCOPE
from functualize._types.retention import DEFAULT_RETENTION, RetentionPolicy
from functualize_substrate_sqlite._transaction import iso

if TYPE_CHECKING:
    from functualize_substrate_sqlite._driver import SqlDriver, Statement

__all__ = ["apply_retention"]


def apply_retention(
    driver: SqlDriver,
    namespace: str,
    policy: RetentionPolicy = DEFAULT_RETENTION,
    *,
    now: datetime | None = None,
) -> tuple[int, int]:
    """Prune eligible scopes and runs by age, then by newest-first count.

    All deletions share one driver batch. A failed statement rolls the whole
    maintenance pass back; no step writer calls this function.
    """
    if policy.max_records < 0:
        raise ValueError("retention max_records must be nonnegative")
    if policy.max_age is not None and policy.max_age.total_seconds() < 0:
        raise ValueError("retention max_age must be nonnegative")

    scope_states = sorted(SCOPE.evictable)
    run_states = sorted(RUN.absorbing)
    scope_filter = (
        " AND status IN (" + ", ".join("?" for _ in scope_states) + ")"
        if policy.evictable_only
        else ""
    )
    run_filter = (
        " AND status IN (" + ", ".join("?" for _ in run_states) + ")"
        if policy.evictable_only
        else ""
    )
    scope_args: tuple[object, ...] = (
        tuple(scope_states) if policy.evictable_only else ()
    )
    run_args: tuple[object, ...] = tuple(run_states) if policy.evictable_only else ()
    scope_clock = (
        "terminal_at" if policy.evictable_only else "COALESCE(terminal_at, updated_at)"
    )
    run_clock = (
        "ended_at" if policy.evictable_only else "COALESCE(ended_at, started_at)"
    )

    statements: list[Statement] = []
    kinds: list[str] = []
    if policy.max_age is not None:
        cutoff = iso((now or datetime.now(UTC)) - policy.max_age)
        statements.extend(
            [
                (
                    f"DELETE FROM workflow_scopes WHERE namespace_id = ?{scope_filter} "
                    f"AND {scope_clock} IS NOT NULL AND {scope_clock} < ?",
                    (namespace, *scope_args, cutoff),
                ),
                (
                    f"DELETE FROM runs WHERE namespace_id = ?{run_filter} "
                    f"AND {run_clock} IS NOT NULL AND {run_clock} < ?",
                    (namespace, *run_args, cutoff),
                ),
            ]
        )
        kinds.extend(("scope", "run"))

    statements.extend(
        [
            (
                "DELETE FROM workflow_scopes WHERE namespace_id = ? AND id IN ("
                "SELECT id FROM workflow_scopes WHERE namespace_id = ?"
                f"{scope_filter} ORDER BY {scope_clock} DESC, id DESC LIMIT -1 OFFSET ?)",
                (namespace, namespace, *scope_args, policy.max_records),
            ),
            (
                "DELETE FROM runs WHERE namespace_id = ? AND id IN ("
                f"SELECT id FROM runs WHERE namespace_id = ?{run_filter} "
                f"ORDER BY {run_clock} DESC, id DESC LIMIT -1 OFFSET ?)",
                (namespace, namespace, *run_args, policy.max_records),
            ),
        ]
    )
    kinds.extend(("scope", "run"))
    counts = driver.batch(statements)
    return (
        sum(
            count for kind, count in zip(kinds, counts, strict=True) if kind == "scope"
        ),
        sum(count for kind, count in zip(kinds, counts, strict=True) if kind == "run"),
    )
