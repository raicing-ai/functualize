"""Resolution-chain assembly for the inline TUI's command panels.

Builds the ConfigTablePanel/ConfigFilesPanel/DiffViewWidget triplet for a
recognized job, and the PendingExecution used to track CLI overrides — both
by consulting the kernel's resolution chain for real per-source values
(CLI -> Env -> File -> Remote -> Default).

Under the SmartBar-as-CLI model, the SmartBar *is* the
literal CLI invocation: any bar-token value is ``"cli"``. There is no separate
"session" source in the chain.

Provenance comes from the kernel's public ``app.resolution_chain()``
accessor — the sanctioned surface for the per-source alternatives list.
Do not reach for the private ``_resolution_chain`` attribute here or
anywhere else in ``_cli/``; the accessor exists precisely so the kernel
can change its internals without breaking the TUI. The ``except
Exception`` fallbacks to field defaults remain, because ``resolve()`` can
still raise for kernel-internal reasons a panel must not crash on.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize._cli.data.pending_execution import PendingExecution
from functualize._cli.data.resolved_value_compat import ResolvedValueCompat
from functualize._cli.tui.bar import BarReadiness
from functualize._cli.tui.cli_arg_parser import parse_cli_args_to_kwargs
from functualize._cli.tui.descriptor_fields import get_descriptor_fields
from functualize._cli.tui.diff_view_widget import DiffViewWidget
from functualize._cli.tui.field_priority import sort_fields_by_priority
from functualize._cli.tui.panels.config_table import (
    ChainEntry,
    ConfigTablePanel,
    EditOrigin,
    FieldDef,
    ParamKind,
)

if TYPE_CHECKING:
    from functualize._cli.tui.app import FunctualizeInlineTUI
    from functualize.types import ConfigFileInfo


def file_resolution_disabled(func_app: Any) -> bool:
    """Return True when the kernel's chain has no FileSource.

    Presets like ``env_only()`` and ``twelve_factor()`` set an explicit
    resolution chain without file discovery; the Config Files panel should
    then say so instead of degrading to an empty file list.

    Detection is by ``source_type == "file"`` (the Source protocol's
    identifier) rather than an isinstance check — ``_cli`` must not import
    the kernel's ``_config`` internals.
    """
    # getattr on the accessor: this helper is also handed test doubles that
    # predate the public API.
    accessor = getattr(func_app, "resolution_chain", None)
    chain = accessor() if callable(accessor) else None
    sources = getattr(chain, "sources", None)
    if not sources:
        return False
    return not any(getattr(source, "source_type", None) == "file" for source in sources)


# Sources shown for PLAIN params (R5-AC2, R5-AC3) — CONFIG params show all
# ChainEntry sources instead.
_PLAIN_DETAIL_SOURCES = {"CLI", "Default"}


def _scalar_to_display(value: Any) -> str:
    """Render a parsed TOML scalar the way the chain displays it."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ",".join(str(v) for v in value)
    return str(value)


def build_command_panels(app: FunctualizeInlineTUI) -> list[tuple[str, Any]]:
    """Build command panels based on current job's field definitions.

    Looks at the SmartBar value to identify the recognized job, then
    converts its FieldDescriptors into FieldDef instances and populates
    a ConfigTablePanel. Returns a list of (title, widget) tuples suitable
    for PanelHost.set_panels().

    Returns an empty list if no job is recognized or the job has no fields.
    """
    if app._smart_bar.readiness == BarReadiness.GREY:
        return []

    tokens = app._smart_bar.value.split() if app._smart_bar.value.strip() else []
    if not tokens:
        return []

    job_name = tokens[0]
    descriptor = app._find_job_descriptor(job_name)
    if descriptor is None:
        return []

    # Use config_fields (from Pydantic model) if available, otherwise parameters
    field_descriptors = get_descriptor_fields(descriptor)
    if not field_descriptors:
        return []

    # Determine if this job has a config class (R1-AC2, R1-AC3)
    # When config_fields differs from parameters, a Pydantic model was expanded.
    raw_config_fields = getattr(descriptor, "config_fields", None) or []
    raw_parameters = getattr(descriptor, "parameters", None) or []
    has_config_class = raw_config_fields != raw_parameters

    # Parse current CLI args from SmartBar to pre-populate values
    provided = parse_cli_args_to_kwargs(
        tokens[1:] if len(tokens) > 1 else [], fields=field_descriptors
    )

    # Kernel's discovered files, fetched once for every field's chain and for
    # the Config Files panel below. Each carries its role and its own values
    # for this job's section — which is what lets the chain name the concrete
    # file behind a value instead of one lossy merged "File" bucket.
    kernel_files: list[ConfigFileInfo] | None = None
    try:
        discovered = app._func_app.config_files(job_name)
        if discovered:
            kernel_files = discovered
    except Exception as exc:
        app.log.warning(
            f"build_command_panels: config_files() failed ({type(exc).__name__}): {exc}"
        )
    # Contributing files in precedence order (winner first). INERT and
    # unparsed files never merge, so they don't appear in a value's chain.
    contributing_files = sorted(
        (info for info in (kernel_files or []) if info.precedence is not None),
        key=lambda info: info.precedence or 0,
    )

    # Convert FieldDescriptors to FieldDef instances for ConfigTablePanel
    field_defs: list[FieldDef] = []
    for fd in field_descriptors:
        default_str = (
            str(getattr(fd, "default", None) or "")
            if getattr(fd, "default", None) is not None
            else ""
        )
        # Use CLI-provided value if available, else default.
        # SmartBar-as-CLI: any bar-token value is "cli".
        cli_value = provided.get(fd.name, "")
        if cli_value:
            value = cli_value
            source = "cli"
        elif default_str:
            value = default_str
            source = "default"
        else:
            value = ""
            source = ""

        description = getattr(fd, "description", "") or ""
        field_def = FieldDef(
            name=fd.name,
            value=value,
            source=source,
            required=getattr(fd, "required", False),
            choices=getattr(fd, "choices", None),
            description=description,
            positional=getattr(fd, "positional", False),
            short_flag=getattr(fd, "short_flag", None),
            type_annotation=getattr(fd, "type_annotation", "str") or "str",
            param_kind=ParamKind.CONFIG if has_config_class else ParamKind.PLAIN,
        )

        # --- Populate resolution chain ---
        chain: list[ChainEntry] = []

        # 1. CLI source: value from parsed SmartBar tokens.
        # No "Session" chain entry — the SmartBar is the CLI.
        chain.append(ChainEntry(source="CLI", value=cli_value))

        # 2-5. Query kernel resolution chain for env/remote/default values.
        # The kernel's resolve() returns the winner + alternatives from all
        # sources; the file layer comes from config_files() instead, which
        # keeps each file's own value where resolve() collapses them into
        # one merged bucket.
        env_value = ""
        remote_value = ""
        kernel_default = ""

        # Direct env lookup (always available, doesn't need kernel)
        env_key = f"{job_name}_{fd.name}".upper().replace(".", "_").replace("-", "_")
        env_value = os.environ.get(env_key, "")

        # Try kernel resolution for remote/default
        try:
            kernel_chain = app._func_app.resolution_chain()
            if kernel_chain is not None:
                group = getattr(descriptor, "group", None)
                section = f"{group}.{job_name}" if group else job_name
                kr = kernel_chain.resolve(fd.name, section=section)
                # Collect all source values: winner + alternatives
                all_sources = [(kr.source_type, kr.value)]
                for src_type, _src_id, src_val in kr.alternatives:
                    all_sources.append((src_type, src_val))
                for src_type, src_val in all_sources:
                    val_str = str(src_val) if src_val else ""
                    if src_type == "env" and not env_value:
                        env_value = val_str
                    elif src_type == "remote":
                        remote_value = val_str
                    elif src_type == "default":
                        kernel_default = val_str
        except Exception as exc:
            # resolve() is not a query_one lookup and can raise for many
            # kernel-internal reasons; log and fall back to the field
            # defaults already populated above.
            app.log.warning(
                f"build_command_panels: kernel resolution chain lookup "
                f"failed for field {fd.name!r} ({type(exc).__name__}): {exc}"
            )

        chain.append(ChainEntry(source="Env", value=env_value))
        # One entry per contributing file (winner first), each carrying its
        # concrete path. Keeping source="File" preserves the PLAIN-param
        # source filter and every "first non-empty wins" walk below.
        for info in contributing_files:
            raw = info.values.get(fd.name)
            chain.append(
                ChainEntry(
                    source="File",
                    value=_scalar_to_display(raw) if fd.name in info.values else "",
                    path=info.path,
                )
            )
        chain.append(ChainEntry(source="Remote", value=remote_value))
        chain.append(ChainEntry(source="Default", value=kernel_default or default_str))

        # Update top-level value/source from resolution chain winner
        # (only if no CLI value already set a higher-priority source)
        if not cli_value:
            # Pick the highest-priority non-empty chain entry as the winner
            for entry in chain:
                if entry.value:
                    value = entry.value
                    source = entry.source.lower()
                    break
            # Update the FieldDef with the resolved winner
            field_def.value = value
            field_def.source = source

        field_def.chain = chain

        # Set original_value/source: if CLI value present, the "original" is
        # what the resolution chain would produce WITHOUT the CLI override.
        # This enables 'r' reset to remove the CLI value and fall back to
        # the resolved source (env, file, default, etc).
        if cli_value:
            # Find the non-CLI chain winner for original
            orig_value = ""
            orig_source = ""
            for entry in chain[1:]:  # Skip index 0 (CLI entry)
                if entry.value:
                    orig_value = entry.value
                    orig_source = entry.source.lower()
                    break
            if not orig_value and default_str:
                orig_value = default_str
                orig_source = "default"
            field_def.original_value = orig_value
            field_def.original_source = orig_source
            field_def.edit_origin = EditOrigin.VALUE
        else:
            field_def.original_value = value
            field_def.original_source = source

        field_defs.append(field_def)

    # Sort fields by priority (R3-AC1, R3-AC2)
    field_defs = sort_fields_by_priority(field_defs)

    # Build ConfigTablePanel and populate it
    app._panel_id_seq += 1
    panel = ConfigTablePanel(id=f"config-table-command-{app._panel_id_seq}")

    panel.set_fields(field_defs)

    panels: list[tuple[str, Any]] = [("Config Table", panel)]

    # Build ConfigFilesPanel with file discovery (R2-AC2)
    from functualize._cli.tui.panels.config_files import (
        ConfigFilesPanel,
        discover_config_files,
    )

    # Determine job group from the descriptor
    job_group = getattr(descriptor, "group", None)

    # Use kernel-consistent section resolution via public API
    config_section: str | None = None
    try:
        config_section = app._func_app.get_job_config_section(job_name)
    except Exception as exc:
        # Domain call, not a widget lookup — log and fall back to no
        # section (discover_config_files() tolerates None).
        app.log.warning(
            f"build_command_panels: get_job_config_section({job_name!r}) "
            f"failed ({type(exc).__name__}): {exc}"
        )

    # kernel_files (fetched once above, before the field loop) carries each
    # file's role — the only way the panel can say whether a file is
    # contributing: a config.prod.toml under ENVIRONMENT=dev exists but is
    # ignored.
    app._panel_id_seq += 1
    config_files_panel = ConfigFilesPanel(id=f"config-files-{app._panel_id_seq}")
    if file_resolution_disabled(app._func_app):
        config_files_panel.set_preset_notice(
            "File resolution disabled by preset (env_only / twelve_factor)"
        )
    else:
        files = discover_config_files(
            field_defs,
            job_name,
            job_group,
            Path.cwd(),
            kernel_files=kernel_files,
            config_section=config_section,
        )
        config_files_panel.set_files(files)
    config_files_panel.set_fields(field_defs)
    panels.append(("Config Files", config_files_panel))

    # Build DiffViewWidget as Panel 3 (R3-AC1)
    app._panel_id_seq += 1
    diff_view = DiffViewWidget(id=f"diff-view-{app._panel_id_seq}")
    panels.append(("Diff View", diff_view))

    # Show diff data when first built (R3-AC2)
    if app._pending is not None:
        previous = app._snapshot_store.get_last_snapshot(app._pending.job_name)
        history = app._snapshot_store.get_snapshots(app._pending.job_name)
        try:
            diff_view.show_diff(app._pending, previous, history)
        except Exception as exc:
            # Not a query_one lookup — show_diff builds diff/history data;
            # log so a malformed snapshot doesn't fail silently.
            app.log.warning(
                f"build_command_panels: diff_view.show_diff() failed "
                f"({type(exc).__name__}): {exc}"
            )

    return panels


def build_pending_execution(
    app: FunctualizeInlineTUI, job_name: str
) -> PendingExecution:
    """Construct a PendingExecution from a job's field descriptors.

    Queries the kernel's ResolutionChain to get real resolved values with
    accurate source_type (cli, env, file, default). Falls back to field
    defaults when the resolution chain is unavailable or raises.

    Args:
        app: The owning TUI app instance.
        job_name: The recognized job name.

    Returns:
        A new PendingExecution instance populated with resolved values.
    """
    descriptor = app._find_job_descriptor(job_name)
    resolved_values: dict[str, Any] = {}

    if descriptor is not None:
        field_descriptors = get_descriptor_fields(descriptor)
        if field_descriptors:
            # Parse current CLI args from SmartBar
            tokens = (
                app._smart_bar.value.split() if app._smart_bar.value.strip() else []
            )
            provided = parse_cli_args_to_kwargs(
                tokens[1:] if len(tokens) > 1 else [], fields=field_descriptors
            )

            # Try to get real resolution from the kernel's ResolutionChain
            kernel_resolved: dict[str, Any] = {}
            try:
                chain = app._func_app.resolution_chain()
                if chain is not None:
                    # Determine section name (job_name or group.job_name)
                    group = getattr(descriptor, "group", None)
                    section = f"{group}.{job_name}" if group else job_name
                    kernel_resolved = chain.resolve_section(section)
            except Exception as exc:
                # Same failure surface as build_command_panels() above —
                # log and fall back to field defaults.
                app.log.warning(
                    f"build_pending_execution: kernel resolution chain "
                    f"lookup failed for job {job_name!r} "
                    f"({type(exc).__name__}): {exc}"
                )

            for fd in field_descriptors:
                cli_value = provided.get(fd.name)
                default = getattr(fd, "default", None)

                if cli_value:
                    # CLI always wins
                    resolved_values[fd.name] = ResolvedValueCompat(
                        value=cli_value, source_type="cli"
                    )
                elif fd.name in kernel_resolved:
                    # Use kernel-resolved value with real source_type
                    kr = kernel_resolved[fd.name]
                    resolved_values[fd.name] = ResolvedValueCompat(
                        value=str(kr.value) if kr.value else "",
                        source_type=kr.source_type,
                    )
                elif default is not None:
                    resolved_values[fd.name] = ResolvedValueCompat(
                        value=str(default), source_type="default"
                    )
                else:
                    resolved_values[fd.name] = ResolvedValueCompat(
                        value="", source_type="default"
                    )

    return PendingExecution(job_name=job_name, resolved_values=resolved_values)


def compute_chain_detail_rows(field_def: FieldDef) -> list[str]:
    """Compute the resolution-chain drill-down detail lines for a field.

    Kind-aware rendering (R5-AC2, R5-AC3, R5-AC4):
    - CONFIG params: show all 5 sources (CLI, Env, File, Remote, Default)
    - PLAIN params: show only 2 sources (CLI, Default) with a banner

    Pure given field_def — does not touch any widget state.

    Returns:
        The lines to write to the detail view, in display order.
    """
    lines: list[str] = []
    is_plain = field_def.param_kind == ParamKind.PLAIN

    # For PLAIN params, show banner first (R5-AC4)
    if is_plain:
        lines.append("[bold]Plain parameter — resolved from CLI/default only[/bold]")
        lines.append("")

    # Field header
    lines.append(f"[bold]Detail: {field_def.name}[/bold]")

    # Field metadata (R5-AC5)
    req_str = "yes" if field_def.required else "no"
    choices_str = ", ".join(field_def.choices) if field_def.choices else "-"
    lines.append(
        f"Type: {field_def.type_annotation} | Required: {req_str} | Choices: {choices_str}"
    )
    lines.append("")

    # Determine which sources to display based on param_kind (R5-AC2, R5-AC3)
    if is_plain:
        chain_entries = [
            e for e in field_def.chain if e.source in _PLAIN_DETAIL_SOURCES
        ]
    else:
        chain_entries = field_def.chain

    # Resolution chain (R5-AC3, R5-AC4)
    # Determine the winning entry (first non-empty in precedence order).
    # Identity, not source name: several entries can share source="File"
    # (one per contributing file), and only the one that wins gets the star.
    winning_entry = next((e for e in chain_entries if e.value), None)

    for entry in chain_entries:
        marker = "★" if entry is winning_entry else "●"
        display_value = entry.value if entry.value else "(not set)"
        # A File entry names its concrete file — "File" alone cannot tell
        # config.base.toml from config.dev.toml.
        if entry.path:
            lines.append(
                f"  {marker} {entry.source:<10} {display_value}  [dim]{entry.path}[/dim]"
            )
        else:
            lines.append(f"  {marker} {entry.source:<10} {display_value}")

    # Description
    if field_def.description:
        lines.append("")
        lines.append(f"Description: {field_def.description}")

    # Manual-edit banner (R5-AC6): the field's value/source was edited in this view.
    if field_def.edit_origin != EditOrigin.NONE:
        lines.append("")
        lines.append("[bold yellow]\\[Edited][/bold yellow]")

    return lines
