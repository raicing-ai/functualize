"""Override application to a persistence target (file or env).

Dispatches pending overrides from PendingExecution to a single caller-supplied
persistence target before job execution. File write failures are reported as
warnings.

Under the SmartBar-as-CLI model there is no "session"
target and no SessionOverlaySource: the whole call writes every override to the
one ``target`` the caller chose.

This module is in the ``_cli/data/`` layer — it imports only from public API
and stdlib.
"""

from __future__ import annotations

import configparser
import contextlib
import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from functualize._cli.data.pending_execution import PendingExecution

logger = logging.getLogger(__name__)


# NOTE: target is a single call-wide Literal["file", "env"], not a
# per-field lookup. Rationale: the function has
# zero production call sites and remains documented-but-unwired; a per-call
# target is the smallest coherent shape that keeps the "apply everything in
# pending.overrides to one target" semantics without resurrecting the per-field
# override_targets bookkeeping this SPEC removes. A future Save-action SPEC can
# widen it (e.g. dict[str, Literal["file", "env"]]) with its own justification.
async def apply_overrides_to_targets(
    pending: PendingExecution,
    config_file_path: Path | None,
    target: Literal["file", "env"],
) -> list[str]:
    """Apply all pending overrides to a single persistence target.

    Dispatches every entry in ``pending.overrides`` to ``target``:

    - ``"file"``: writes to the config file (atomic rename); a missing path or
      a write failure is reported as a warning (the value is not persisted).
    - ``"env"``: sets a process-local environment variable.

    Args:
        pending: The PendingExecution containing overrides.
        config_file_path: Path to the config file for the ``"file"`` target,
            or None if no config file is available.
        target: The persistence destination for the whole call.

    Returns:
        List of warning messages for overrides that could not be persisted.
    """
    section = pending.job_name
    warnings: list[str] = []

    for field, value in pending.overrides.items():
        if target == "file":
            if config_file_path is None:
                logger.warning(
                    "No config file path available for field %r; not saved.",
                    field,
                )
                warnings.append(f"{field}: no config file — not saved")
            else:
                try:
                    _write_to_config_file(config_file_path, section, field, value)
                except (OSError, PermissionError):
                    logger.warning(
                        "Failed to write field %r to config file %s; not saved.",
                        field,
                        config_file_path,
                        exc_info=True,
                    )
                    warnings.append(f"{field}: file write failed — not saved")

        elif target == "env":
            env_key = f"{section}_{field}".upper()
            os.environ[env_key] = str(value)

    return warnings


def _write_to_config_file(path: Path, section: str, field: str, value: Any) -> None:
    """Write a single field value to the config file using atomic rename.

    Reads the existing config (if any), updates the specified section/field,
    and writes atomically using a temporary file + ``os.replace``.

    Args:
        path: Path to the INI-style config file.
        section: The config section (job name).
        field: The field name within the section.
        value: The value to write (will be converted to str).

    Raises:
        OSError: If the temporary file cannot be created or os.replace fails.
        PermissionError: If the file or directory is not writable.
    """
    parser = configparser.ConfigParser(interpolation=None)

    # Read existing config if file exists
    if path.exists():
        parser.read(str(path), encoding="utf-8")

    # Ensure section exists
    if not parser.has_section(section):
        parser.add_section(section)

    # Set the value
    parser.set(section, field, str(value))

    # Write atomically: tempfile in same directory + os.replace
    dir_path = path.parent
    dir_path.mkdir(parents=True, exist_ok=True)

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=dir_path,
            prefix=".functualize_cfg_",
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        ) as fd:
            tmp_path = fd.name
            parser.write(fd)
        os.replace(tmp_path, str(path))
    except BaseException:
        # Clean up temp file on any failure
        if tmp_path is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
        raise
