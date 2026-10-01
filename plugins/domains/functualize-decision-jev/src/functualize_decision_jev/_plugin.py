"""The Jev decision plugin — registers the ``decision`` gate strategy.

Registered via entry point ``functualize.plugins`` with name ``"jev"``. At
``APP_READY`` it resolves ``JevConfig`` from the ``[jev]`` config section and
registers ``DecisionGateResolver(JevDecisionProvider(config))`` as the
``decision`` strategy, so a ``Gate(decide=...)`` in any workflow of the app can
be answered by a proposal that clears the workflow's own thresholds.

It registers nothing else: no preset, no DI provider, and no credential. The
key is read by the provider at call time, from the environment, never here —
so an app with the plugin installed and no key still boots, and a decision gate
records ``not_configured`` and falls through to a person.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from functualize.plugin import DecisionGateResolver

if TYPE_CHECKING:
    from functualize.plugin import PluginHost
    from functualize_decision_jev._provider import JevConfig

__all__ = ["JevPlugin"]

logger = logging.getLogger(__name__)

#: The config section `JevConfig` is resolved from.
_SECTION = "jev"


class JevPlugin:
    """Plugin that answers ``decision`` gates with the Jev provider."""

    name: str = "jev"
    version: str = "0.1.0"
    description: str = (
        "Experimental decision provider — proposes a gate's choice through Jev"
    )

    def __call__(self, app: PluginHost) -> None:
        """Defer registration to ``APP_READY``.

        Plugins load before the config resolution chain is built, so resolving
        ``[jev]`` here would always fall back to the defaults and a configured
        section would be ignored without a word. Walks start after boot, so a
        strategy registered at ``APP_READY`` is in place before any gate is
        reached.
        """
        app.hooks.on_ready(self._on_app_ready)

    def _on_app_ready(self, app: PluginHost) -> None:
        # Imported here, not at module level: the provider's transport pulls in
        # `urllib.request` and `http.client`, which the loader would otherwise
        # charge to plugin loading on every boot of every app that has this
        # package installed.
        from functualize_decision_jev._provider import JevDecisionProvider

        provider = JevDecisionProvider(self._resolve_config(app))
        app.gates.register_gate_strategy("decision", DecisionGateResolver(provider))

    def _resolve_config(self, app: PluginHost) -> JevConfig:
        """``[jev]`` as a ``JevConfig``, or the defaults when it cannot be used.

        An absent section resolves to the defaults without an error. A section
        that is present but unusable — an unknown key, a timeout that is not a
        number — falls back to the defaults as the sibling plugins do, but says
        so at warning level: a misconfiguration that silently changed nothing
        would be indistinguishable from one that worked.
        """
        from functualize_decision_jev._provider import JevConfig

        try:
            resolved = app.configuration.resolve_model(_SECTION, JevConfig)
            if not isinstance(resolved, JevConfig):
                raise TypeError(f"resolved {type(resolved).__name__}, not JevConfig")
            return JevConfig(
                model=str(resolved.model),
                endpoint=str(resolved.endpoint),
                timeout_seconds=float(resolved.timeout_seconds),
            )
        except Exception as exc:
            logger.warning(
                "JevPlugin: the [%s] config section could not be used (%s); "
                "using the defaults",
                _SECTION,
                exc,
            )
            return JevConfig()
