"""AI provider discovery and auto-selection.

Reads the [ai] config section and selects the appropriate AIProvider
implementation plugin from the ``functualize.ai_providers`` entry point group.

Selection logic:
1. If ``provider`` is explicitly set in config, select the matching entry point.
2. If ``provider`` is not set and exactly one implementation is installed,
   auto-select it.
3. If no implementations are installed, raise AINotAvailableError with install
   instructions.
4. If multiple implementations are installed and no provider is configured,
   raise AINotAvailableError listing available providers.
"""

from __future__ import annotations

import importlib.metadata
import logging
from typing import Any

from functualize_ai._config import AIConfig
from functualize_ai._errors import AINotAvailableError

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "functualize.ai_providers"

_INSTALL_INSTRUCTIONS = (
    "No AI provider plugin is installed. "
    "Install one with: pip install functualize-ai-pydantic"
)

_PROVIDER_NOT_FOUND_TEMPLATE = (
    "AI provider '{provider}' not found in installed plugins. "
    "Available providers: {available}. "
    "Install the desired provider or check your [ai] config section."
)

_MULTIPLE_PROVIDERS_NO_CONFIG = (
    "Multiple AI provider plugins are installed ({available}) but no "
    "'provider' is configured in the [ai] config section. "
    'Set provider = "<name>" in your config file to select one.'
)


def discover_ai_providers() -> dict[str, importlib.metadata.EntryPoint]:
    """Discover all installed AI provider entry points.

    Returns:
        Dictionary mapping provider names to their entry points.
    """
    eps = importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)
    return {ep.name: ep for ep in eps}


def select_ai_provider(
    config: AIConfig,
    *,
    available_providers: dict[str, importlib.metadata.EntryPoint] | None = None,
) -> Any:
    """Select and load the AI provider plugin based on configuration.

    Args:
        config: The AIConfig instance (read from [ai] config section).
        available_providers: Optional pre-discovered providers mapping.
            If None, discovers entry points automatically.

    Returns:
        The loaded plugin object (typically a class or callable).

    Raises:
        AINotAvailableError: If no provider can be selected or loaded.
    """
    if available_providers is None:
        available_providers = discover_ai_providers()

    # Case 1: Explicit provider configured
    if config.provider:
        return _select_explicit_provider(config.provider, available_providers)

    # Case 2: No provider configured — auto-select or error
    return _auto_select_provider(available_providers)


def _select_explicit_provider(
    provider_name: str,
    available_providers: dict[str, importlib.metadata.EntryPoint],
) -> Any:
    """Select a provider by explicit name from config.

    Args:
        provider_name: The configured provider name.
        available_providers: Available entry points.

    Returns:
        The loaded plugin object.

    Raises:
        AINotAvailableError: If the named provider is not found.
    """
    if not available_providers:
        raise AINotAvailableError(_INSTALL_INSTRUCTIONS)

    ep = available_providers.get(provider_name)
    if ep is None:
        available_names = ", ".join(sorted(available_providers.keys()))
        raise AINotAvailableError(
            _PROVIDER_NOT_FOUND_TEMPLATE.format(
                provider=provider_name, available=available_names
            )
        )

    return _load_entry_point(ep)


def _auto_select_provider(
    available_providers: dict[str, importlib.metadata.EntryPoint],
) -> Any:
    """Auto-select a provider when none is explicitly configured.

    If exactly one provider is installed, select it automatically.
    If none are installed, raise with install instructions.
    If multiple are installed, raise asking for explicit selection.

    Args:
        available_providers: Available entry points.

    Returns:
        The loaded plugin object.

    Raises:
        AINotAvailableError: If no provider or ambiguous selection.
    """
    if not available_providers:
        raise AINotAvailableError(_INSTALL_INSTRUCTIONS)

    if len(available_providers) == 1:
        name, ep = next(iter(available_providers.items()))
        logger.info(
            f"Auto-selected AI provider '{name}' (single installed implementation)"
        )
        return _load_entry_point(ep)

    # Multiple providers installed, no explicit config
    available_names = ", ".join(sorted(available_providers.keys()))
    raise AINotAvailableError(
        _MULTIPLE_PROVIDERS_NO_CONFIG.format(available=available_names)
    )


def _load_entry_point(ep: importlib.metadata.EntryPoint) -> Any:
    """Load an entry point and return the plugin object.

    Args:
        ep: The entry point to load.

    Returns:
        The loaded plugin object.

    Raises:
        AINotAvailableError: If loading fails.
    """
    try:
        loaded = ep.load()
        logger.debug(f"Loaded AI provider entry point '{ep.name}'")
        return loaded
    except Exception as exc:
        raise AINotAvailableError(
            f"Failed to load AI provider '{ep.name}': {exc}. "
            f"Ensure the package is properly installed."
        ) from exc


def resolve_ai_provider(
    app: Any | None = None,
    *,
    config: AIConfig | None = None,
) -> Any:
    """Top-level convenience: read config and select provider.

    This is the main entry point used at boot time to wire up the AI domain.

    Args:
        app: Optional FunctualizeApp instance for reading config via
            resolution chain. If provided and config is None, reads
            [ai] section from the app's config.
        config: Optional pre-built AIConfig. If provided, takes precedence
            over app-based resolution.

    Returns:
        The loaded plugin object.

    Raises:
        AINotAvailableError: If no provider can be resolved.
    """
    if config is None:
        if app is not None and hasattr(app, "resolve_model"):
            try:
                config = app.resolve_model("ai", AIConfig)
            except Exception:
                # Config section may not exist; use defaults
                config = AIConfig()
        else:
            config = AIConfig()

    return select_ai_provider(config)
