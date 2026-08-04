"""CLI delivery layer — imports ONLY from public API.

This package implements the ``func`` CLI entry point using exclusively
the public API surface (``functualize.app``, ``functualize.job``,
``functualize.plugin``, ``functualize.types``, ``functualize.testing``).

It must NEVER import from any underscore-prefixed internal package
(``_types``, ``_primitives``, ``_events``, ``_discovery``, ``_config``,
``_engine``, ``_plugins``, ``_app``). If ``_cli/`` cannot accomplish
something via the public API, that capability is added to the public API.
"""
