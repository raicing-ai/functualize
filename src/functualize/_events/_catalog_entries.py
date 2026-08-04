"""Framework-defined event catalog entries.

Contains metadata for all instrumentation points defined by functualize.
These are registered during observability bootstrap so plugins can
introspect the full event catalog at registration time.
"""

from __future__ import annotations

from functualize._events._obs_types import EventMetadata


def get_framework_event_catalog() -> list[EventMetadata]:
    """Return all framework-defined event metadata entries.

    Covers domains: job, config, plugin, cli, tui.
    """
    return [
        # --- Job domain ---
        EventMetadata(
            event_name="job.execute.start",
            description="Job execution begins",
            payload_fields={"job_name": "str", "group": "str"},
            module="functualize.discovery.registry",
            domain="job",
        ),
        EventMetadata(
            event_name="job.execute.end",
            description="Job execution succeeds",
            payload_fields={"job_name": "str", "group": "str", "duration_ms": "float"},
            module="functualize.discovery.registry",
            domain="job",
        ),
        EventMetadata(
            event_name="job.execute.error",
            description="Job execution fails",
            payload_fields={
                "job_name": "str",
                "group": "str",
                "duration_ms": "float",
                "error_type": "str",
                "message": "str",
            },
            module="functualize.discovery.registry",
            domain="job",
        ),
        EventMetadata(
            event_name="job.teardown.start",
            description="Job teardown begins",
            payload_fields={"job_name": "str", "group": "str"},
            module="functualize.discovery.registry",
            domain="job",
        ),
        EventMetadata(
            event_name="job.teardown.end",
            description="Job teardown completes",
            payload_fields={"job_name": "str", "group": "str", "duration_ms": "float"},
            module="functualize.discovery.registry",
            domain="job",
        ),
        # --- Config domain ---
        EventMetadata(
            event_name="config.file.parse.start",
            description="Format_Provider parse begins",
            payload_fields={"path": "str", "extension": "str", "provider": "str"},
            module="functualize._config.providers",
            domain="config",
        ),
        EventMetadata(
            event_name="config.file.parse.end",
            description="Format_Provider parse completes",
            payload_fields={
                "path": "str",
                "provider": "str",
                "duration_ms": "float",
                "key_count": "int",
            },
            module="functualize._config.providers",
            domain="config",
        ),
        EventMetadata(
            event_name="config.remote.fetch.start",
            description="Remote_Provider fetch begins",
            payload_fields={"provider": "str", "reference": "str"},
            module="functualize._config.providers",
            domain="config",
        ),
        EventMetadata(
            event_name="config.remote.fetch.end",
            description="Remote_Provider fetch completes",
            payload_fields={
                "provider": "str",
                "reference": "str",
                "duration_ms": "float",
                "success": "bool",
            },
            module="functualize._config.providers",
            domain="config",
        ),
        EventMetadata(
            event_name="config.remote.fetch.error",
            description="Remote_Provider fetch fails",
            payload_fields={
                "provider": "str",
                "reference": "str",
                "error_type": "str",
                "message": "str",
            },
            module="functualize._config.providers",
            domain="config",
        ),
        EventMetadata(
            event_name="config.resolution.start",
            description="ResolutionChain resolves model",
            payload_fields={
                "section": "str",
                "model_class": "str",
                "field_count": "int",
            },
            module="functualize._config.chain",
            domain="config",
        ),
        EventMetadata(
            event_name="config.resolution.end",
            description="Resolution completes",
            payload_fields={
                "section": "str",
                "model_class": "str",
                "duration_ms": "float",
                "sources_consulted": "int",
            },
            module="functualize._config.chain",
            domain="config",
        ),
        EventMetadata(
            event_name="config.annotation.resolve.start",
            description="Annotation fallback begins",
            payload_fields={"key": "str", "chain_length": "int"},
            module="functualize._config.chain",
            domain="config",
        ),
        EventMetadata(
            event_name="config.annotation.resolve.end",
            description="Annotation resolved",
            payload_fields={
                "key": "str",
                "winning_provider": "str",
                "attempts": "int",
                "duration_ms": "float",
            },
            module="functualize._config.chain",
            domain="config",
        ),
        # --- Plugin domain ---
        EventMetadata(
            event_name="plugin.discovery.start",
            description="Plugin discovery begins",
            payload_fields={"group": "str"},
            module="functualize.plugins",
            domain="plugin",
        ),
        EventMetadata(
            event_name="plugin.discovery.end",
            description="Plugin discovery completes",
            payload_fields={
                "group": "str",
                "count": "int",
                "duration_ms": "float",
            },
            module="functualize.plugins",
            domain="plugin",
        ),
        EventMetadata(
            event_name="plugin.load.start",
            description="Individual plugin load begins",
            payload_fields={"plugin_name": "str", "entry_point": "str"},
            module="functualize.plugins",
            domain="plugin",
        ),
        EventMetadata(
            event_name="plugin.load.end",
            description="Individual plugin load completes",
            payload_fields={
                "plugin_name": "str",
                "version": "str",
                "duration_ms": "float",
            },
            module="functualize.plugins",
            domain="plugin",
        ),
        EventMetadata(
            event_name="plugin.registration.start",
            description="Plugin __call__(app) begins",
            payload_fields={"plugin_name": "str"},
            module="functualize.plugins",
            domain="plugin",
        ),
        EventMetadata(
            event_name="plugin.registration.end",
            description="Plugin __call__(app) completes",
            payload_fields={"plugin_name": "str", "duration_ms": "float"},
            module="functualize.plugins",
            domain="plugin",
        ),
        # --- CLI domain ---
        EventMetadata(
            event_name="cli.parse.start",
            description="CLI argument parsing begins",
            payload_fields={"argv_count": "int"},
            module="functualize.core.app",
            domain="cli",
        ),
        EventMetadata(
            event_name="cli.parse.end",
            description="CLI argument parsing completes",
            payload_fields={"command": "str", "duration_ms": "float"},
            module="functualize.core.app",
            domain="cli",
        ),
        # --- Interactivity domain ---
        EventMetadata(
            event_name="interactivity.job.submit",
            description="Trigger job execution from any interactivity backend",
            payload_fields={"job_name": "str", "kwargs": "dict[str, Any]"},
            module="functualize.core",
            domain="interactivity",
        ),
        # --- Lifecycle domain ---
        EventMetadata(
            event_name="lifecycle.registry.frozen",
            description="DI registry frozen after APP_READY hooks complete",
            payload_fields={"app": "FunctualizeApp"},
            module="functualize.core.app",
            domain="lifecycle",
        ),
        # --- TUI domain ---
        EventMetadata(
            event_name="tui.session.start",
            description="TUI session begins",
            payload_fields={"command_name": "str"},
            module="functualize.tui",
            domain="tui",
        ),
        EventMetadata(
            event_name="tui.session.end",
            description="TUI session ends",
            payload_fields={"command_name": "str", "duration_ms": "float"},
            module="functualize.tui",
            domain="tui",
        ),
        # --- Shell domain (§B.8; output chunks NOT on the bus) ---
        EventMetadata(
            event_name="shell.command.start",
            description="A shell command begins (command masked per §B.6)",
            payload_fields={"command": "str"},
            module="functualize.engine.capabilities.shell",
            domain="shell",
        ),
        EventMetadata(
            event_name="shell.command.end",
            description="A shell command finishes (command masked per §B.6)",
            payload_fields={
                "command": "str",
                "returncode": "int",
                "duration_ms": "float",
                "status": "str",
            },
            module="functualize.engine.capabilities.shell",
            domain="shell",
        ),
    ]
