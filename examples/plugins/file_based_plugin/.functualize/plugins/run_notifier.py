"""A file-based plugin that announces job outcomes on the event bus.

Dropped into `.functualize/plugins/`, this file needs no packaging: the loader
scans the convention directory at boot, imports each top-level non-underscore
`.py` file, and calls the module-level `plugin` object with the app.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize.plugin import StructuredEvent


class RunNotifier:
    """Announces the outcome of every job run.

    The loader validates `name`, `version` and `description` as strings and
    invokes the object itself — so a plugin is any callable carrying those
    three attributes.
    """

    name = "run-notifier"
    version = "1.0.0"
    description = "Announces job success and failure on the event bus."

    def __call__(self, app: Any) -> None:
        """Registration hook — subscribe to the job lifecycle.

        Args:
            app: The FunctualizeApp instance, passed by the plugin loader.
        """
        app.event_bus.subscribe("job.execute.success", self._on_success)
        app.event_bus.subscribe("job.execute.failure", self._on_failure)
        # The two names above are the plugin's declared interest. The engine
        # publishes a single terminal event carrying the outcome as a field
        # (`job.execute.end`, `status="success"|"failure"`), so that is the
        # subscription that actually fires today.
        app.event_bus.subscribe("job.execute.end", self._on_end)

    def _on_success(self, event: StructuredEvent) -> None:
        # `resource` carries the job name; the emit kwargs land in `payload`.
        print(f"[run-notifier] {event.resource} succeeded.")

    def _on_failure(self, event: StructuredEvent) -> None:
        print(f"[run-notifier] {event.resource} failed.")

    def _on_end(self, event: StructuredEvent) -> None:
        status = event.payload.get("status")
        if status == "success":
            self._on_success(event)
        elif status == "failure":
            self._on_failure(event)


plugin = RunNotifier()
