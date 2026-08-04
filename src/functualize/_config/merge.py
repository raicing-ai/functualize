"""Deep-merge algorithm for layered configuration dictionaries.

Only imports from stdlib — no internal package dependencies.
"""

from typing import Any


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge overlay into base.

    - Nested dicts are merged recursively
    - Leaf values in overlay replace base values
    - Lists are replaced wholesale (not concatenated)
    - New keys in overlay are added to result

    Args:
        base: The lower-priority configuration dict.
        overlay: The higher-priority configuration dict.

    Returns:
        A new dict with merged values (does not mutate inputs).
    """
    result = base.copy()
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def merge_config_layers(
    layers: list[dict[str, Any]],
    *,
    root_key: str = "root",
) -> dict[str, Any]:
    """Deep-merge config layers with root-stop semantics.

    Merges layers nearest-first (index 0 = highest priority). Processing
    stops when a layer contains ``root_key`` set to ``True``. The root_key
    itself is stripped from the final output.

    This implements the "root = true" convention used by EditorConfig,
    ESLint, and similar tools that walk directory hierarchies.

    Args:
        layers: List of config dicts in priority order (index 0 = nearest/
            highest priority). Each dict represents one config file's content.
        root_key: Key that signals "stop merging" when its value is truthy.
            Defaults to ``"root"``.

    Returns:
        A new dict with merged values. The ``root_key`` is removed from output.
        Returns empty dict if layers is empty.
    """
    if not layers:
        return {}

    # Determine which layers to include (stop at root_key = True)
    active_layers: list[dict[str, Any]] = []
    for layer in layers:
        active_layers.append(layer)
        if layer.get(root_key) is True:
            break

    # Merge from lowest priority (last) to highest (first)
    result: dict[str, Any] = {}
    for layer in reversed(active_layers):
        result = deep_merge(result, layer)

    # Strip root_key from output
    result.pop(root_key, None)

    return result
