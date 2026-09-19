"""Shared across every app under this root — one file, no packaging.

Lives in the root's `.functualize/plugins/`, which is the *convention*
directory: nothing declares it, and both `billing/` and `shipping/` pick it up
because the loader walks up from wherever you are to the project root.
"""

from __future__ import annotations

from typing import Any


class AuditLog:
    """Announces every job that finishes, for every app under this root."""

    name = "audit-log"
    version = "1.0.0"
    description = "Logs job completion across every app in the monorepo."

    def __call__(self, app: Any) -> None:
        """Registration hook — the loader calls this with the app."""
        app.event_bus.subscribe("job.execute.end", self._on_end)

    def _on_end(self, event: Any) -> None:
        status = event.payload.get("status", "unknown")
        print(f"[audit] {event.resource}: {status}")


plugin = AuditLog()
