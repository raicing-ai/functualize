"""Extract a cacheable :class:`GroupOptionsSpec` from a ``GroupOptions`` class.

Runs inside the job scan's ``exec_module`` pass, on the already-executed
module, so a group's declared flags are cached alongside the jobs found in
the same sweep.

Field extraction reuses :func:`extract_field_descriptors` — the same
JSON-schema-driven mapping used for job config classes, which already handles
types, defaults, required-ness, and enum choices — and then overlays the CLI
marker data (``Option``'s short flag and help text) that the JSON schema
cannot carry. Markers are matched by class name, the same way
``_discovery.providers`` reads them off job signatures, so this module needs
no import of the public marker types.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

from functualize._discovery.schema_extractor import extract_field_descriptors
from functualize._types.descriptors import FieldDescriptor, GroupOptionsSpec

if TYPE_CHECKING:
    from pydantic import BaseModel


def extract_group_options_fields(
    options_class: type[BaseModel],
) -> list[FieldDescriptor]:
    """Extract the option fields declared on a ``GroupOptions`` subclass.

    Args:
        options_class: The ``GroupOptions`` subclass to read.

    Returns:
        One :class:`FieldDescriptor` per declared field, with ``short_flag``
        and marker help text overlaid from any ``Option`` annotation.
    """
    base_fields = extract_field_descriptors(options_class)
    model_fields = getattr(options_class, "model_fields", {})

    resolved: list[FieldDescriptor] = []
    for descriptor in base_fields:
        info = model_fields.get(descriptor.name)
        short_flag = descriptor.short_flag
        description = descriptor.description

        for meta in getattr(info, "metadata", ()) or ():
            # Matched by class name to keep this module free of CLI-marker
            # imports — the same convention _discovery.providers uses.
            if type(meta).__name__ != "Option":
                continue
            if getattr(meta, "short", None):
                short_flag = meta.short
            if getattr(meta, "help", None) and not description:
                description = meta.help

        resolved.append(
            dataclasses.replace(
                descriptor, short_flag=short_flag, description=description
            )
        )

    return resolved


def extract_group_options_spec(
    options_class: type[Any],
    *,
    source_file: str = "",
    source_mtime: float = 0.0,
    content_hash: str = "",
    module_path: str = "",
) -> GroupOptionsSpec:
    """Build the cacheable spec for one bound ``GroupOptions`` subclass.

    Args:
        options_class: A class that passed ``is_group_options_class``.
        source_file: Absolute path of the declaring module.
        source_mtime: os.path.getmtime() at scan time.
        content_hash: sha256 hex digest of the source at scan time.
        module_path: Dotted module path for lazy import, when known.

    Returns:
        The :class:`GroupOptionsSpec` to persist.
    """
    return GroupOptionsSpec(
        group=getattr(options_class, "__group_path__", ""),
        class_name=options_class.__name__,
        fields=extract_group_options_fields(options_class),
        source_file=source_file,
        source_mtime=source_mtime,
        content_hash=content_hash,
        module_path=module_path,
    )
