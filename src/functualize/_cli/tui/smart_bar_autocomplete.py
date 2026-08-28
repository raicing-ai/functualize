"""Context-aware autocomplete for the functualize SmartBar.

Subclasses textual-autocomplete's AutoComplete widget to provide
context-aware completion candidates based on CursorContext parsing:
- command mode → job/builtin names with provenance badges
- flag mode → --flag completions with used-flag filtering
- value mode → choices, history, and path suggestions
- positional mode → choices/history with [N] index prefix

The textual-autocomplete library is an optional dependency. This module
uses TYPE_CHECKING guards so it can be imported without the library at
analysis time. At runtime it must only be instantiated when the library
is available (inside the TUI launch path where the import is guarded).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from functualize._cli.builtins import (
    builtin_descriptions,
    builtin_subcommand_names,
    builtin_subcommands,
)
from functualize._cli.completions.cursor_context import (
    CursorContext,
    parse_cursor_context,
)
from functualize._cli.completions.flag_filtering import (
    FlagDescriptor,
    filter_used_flags,
)
from functualize._cli.completions.quote_handling import (
    quote_for_insertion,
    tokenize_smart_bar,
)
from functualize.plugin import DEFAULT_SIGIL, InputMode, InputModeRegistry

if TYPE_CHECKING:
    from functualize._cli.completions.provenance import (
        CompletionProvenanceClassifier,
    )
    from functualize._cli.data.argument_history import ArgumentHistory
    from functualize._cli.tui.path_suggestion_scanner import PathSuggestionScanner
    from functualize.app.core import FunctualizeApp
    from functualize.types import FieldDescriptor, JobDescriptor

_MAX_CANDIDATES = 50

# Builtin commands offered at command level, and their first-level
# subcommands — both derived from the single registry in _cli/builtins.py.
_BUILTIN_COMMANDS: dict[str, str] = builtin_descriptions()
_BUILTIN_SUBCOMMANDS: dict[str, dict[str, dict[str, str]]] = builtin_subcommands()
_BUILTIN_SUBCOMMAND_NAMES: dict[str, dict[str, tuple[str, ...]]] = (
    builtin_subcommand_names()
)

logger = logging.getLogger(__name__)


class SmartBarAutoComplete:
    """Context-aware autocomplete for the functualize smart bar.

    Designed to subclass textual-autocomplete's AutoComplete widget at
    runtime. When textual-autocomplete is not installed, this class can
    still be imported for type-checking and testing of its pure logic.

    At TUI launch time (inside the guarded import block), this class is
    mixed with the real AutoComplete base. The methods here implement the
    three protocol methods that textual-autocomplete expects subclasses
    to override.
    """

    def __init__(
        self,
        app: FunctualizeApp,
        provenance: CompletionProvenanceClassifier,
        history: ArgumentHistory | None = None,
        path_scanner: PathSuggestionScanner | None = None,
    ) -> None:
        self._app = app
        self._provenance = provenance
        self._history = history
        self._path_scanner = path_scanner

        # Cache job data
        self._jobs: list[JobDescriptor] | None = None
        self._job_names: list[str] | None = None
        self._job_map: dict[str, JobDescriptor] | None = None
        self._positional_params: dict[str, int] | None = None

        # The bar's mode registry. The default (command) mode is
        # shell-inherent, so it is registered here rather than contributed;
        # `!`/`?` modes register onto the same registry (C1b.3 / C1b.4).
        self.input_modes = InputModeRegistry()
        self.input_modes.register(
            InputMode(
                sigil=DEFAULT_SIGIL,
                name="command",
                candidate_source=self._command_mode_candidates,
                is_ready=lambda text: bool(text.strip()),
                submit=lambda text: None,
                history_namespace="command",
            )
        )

    # ─── Lazy cached job metadata ────────────────────────────────────────

    @property
    def _cached_jobs(self) -> list[JobDescriptor]:
        if self._jobs is None:
            self._jobs = list(self._app.get_jobs())
        return self._jobs

    @property
    def _cached_job_names(self) -> list[str]:
        if self._job_names is None:
            self._job_names = [j.name for j in self._cached_jobs]
        return self._job_names

    @property
    def _cached_job_map(self) -> dict[str, JobDescriptor]:
        if self._job_map is None:
            self._job_map = {j.name: j for j in self._cached_jobs}
        return self._job_map

    @property
    def _cached_positional_params(self) -> dict[str, int]:
        """Map job_name → count of positional (Arg-annotated) parameters."""
        if self._positional_params is None:
            self._positional_params = {}
            for job_name in self._cached_job_names:
                # Use get_job() for accurate positional metadata
                job = self._app.get_job(job_name)
                if job is None:
                    self._positional_params[job_name] = 0
                    continue
                fields = job.config_fields if job.config_fields else job.parameters
                count = sum(1 for f in fields if getattr(f, "positional", False))
                self._positional_params[job_name] = count
        return self._positional_params

    def invalidate_cache(self) -> None:
        """Clear cached job data (call when jobs change)."""
        self._jobs = None
        self._job_names = None
        self._job_map = None
        self._positional_params = None

    # ─── Core protocol methods ───────────────────────────────────────────

    def get_search_string(self, state: object) -> str:
        """Return only the partial text for the current cursor context.

        Args:
            state: A TargetState object with .text and .cursor_position attributes.

        Returns:
            The partial string the user is currently typing within the
            semantic context (not the full input text).
        """
        text = getattr(state, "text", "")
        cursor_pos = getattr(state, "cursor_position", len(text))
        ctx = self._parse_context(text, cursor_pos)
        return ctx.partial

    def get_candidates(self, state: object) -> list[object]:
        """Return up to 50 candidates based on CursorContext mode.

        Args:
            state: A TargetState object with .text and .cursor_position attributes.

        Returns:
            A list of DropdownItem objects (or dicts with equivalent data
            when textual-autocomplete is not available for testing).
        """
        # A masked field offers no completions. The dropdown renders candidate
        # text unmasked, so completing a secret would print it one row below the
        # bullets that are hiding it — the mask would be theatre.
        if getattr(getattr(self, "target", None), "_suppress_autocomplete", False):
            return []

        text = getattr(state, "text", "")
        cursor_pos = getattr(state, "cursor_position", len(text))

        mode = self.input_modes.resolve(text)
        if mode is None:  # pragma: no cover - a default is always registered
            return []
        stripped = mode.strip_sigil(text)
        offset = cursor_pos - (len(text) - len(stripped))
        return mode.candidate_source(stripped, max(offset, 0))

    # ── default (command) mode ───────────────────────────────────────────

    @property
    def _group_trie(self) -> Any:
        """The group trie (memoized) — the same one execution walks (S6b)."""
        cached = getattr(self, "_group_trie_cache", "unset")
        if cached != "unset":
            return cached
        from functualize._cli.tui.cli_arg_parser import build_group_option_trie

        trie = build_group_option_trie(self._app)
        self._group_trie_cache: Any = trie
        return trie

    def _walk_path(self, tokens: list[str]) -> tuple[Any, list[str], str | None]:
        """Walk completed tokens down the trie (S6b context resolution).

        Returns ``(node, consumed_path_segments, resolved_job_name)``. Flags and
        their values are stepped over — they are not path segments — so the walk
        answers "which node is the cursor inside" for a line that already mixes
        group flags with path tokens.
        """
        trie = self._group_trie
        if trie is None:
            return None, [], None
        node = trie.root
        segments: list[str] = []
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token.startswith("-"):
                # A group flag and (for a value flag) its value are not path.
                index += 2 if "=" not in token and index + 1 < len(tokens) else 1
                continue
            stepped = trie.step(node, token)
            if stepped is None:
                break
            node = stepped
            segments.extend(token.split("."))
            index += 1
            if getattr(node, "has_payload", False) and getattr(node, "is_leaf", False):
                return node, segments, node.payload
        return node, segments, None

    def _candidates_path(
        self, node: Any, segments: list[str], partial: str
    ) -> list[object]:
        """Children of the current node — the groups and jobs that come next.

        This is what makes the shell space-separated: at the root it offers
        top-level groups and ungrouped jobs, and inside ``deploy`` it offers
        ``web``, never the dotted ``deploy.web.run`` that execution refuses.
        """
        partial_lower = partial.lower()
        entries: list[tuple[float, str, str, str]] = []

        for child in getattr(node, "children", {}).values():
            name = child.segment
            if partial_lower and partial_lower not in name.lower():
                continue
            is_job = getattr(child, "has_payload", False) and getattr(
                child, "is_leaf", False
            )
            desc = ""
            if is_job:
                job = self._cached_job_map.get(child.payload or "")
                if job is not None and job.docstring:
                    desc = job.docstring.strip().split("\n")[0][:60]
                badge = "[dim green]job[/dim green]"
            else:
                badge = "[dim blue]group[/dim blue]"
            score = 2.0 if name.lower().startswith(partial_lower) else 1.0
            entries.append((score, name, desc, badge))

        # Builtins only at the root — they are not inside a job group. Skip any
        # the trie already yielded as a node, or `builtin` appears twice.
        if not segments:
            seen = {e[1] for e in entries}
            for name, desc in _BUILTIN_COMMANDS.items():
                if name in seen:
                    continue
                if partial_lower and partial_lower not in name.lower():
                    continue
                score = 2.0 if name.lower().startswith(partial_lower) else 1.0
                entries.append((score, name, desc, "[dim cyan]built-in[/dim cyan]"))

        entries.sort(key=lambda e: (-e[0], e[1]))
        return [
            _make_dropdown_item(main=name, prefix=badge, description=desc)
            for _, name, desc, badge in entries[:_MAX_CANDIDATES]
        ]

    def _injection_type_names(self, job_name: str) -> set[str]:
        """Declared ``GroupOptions`` class names on a job's group path.

        The cached-descriptor equivalent of the live ``issubclass`` test: a
        parameter typed with one of these is an injection point, never a flag.
        """
        from functualize._cli.tui.cli_arg_parser import group_option_specs_on_path

        return {
            spec.class_name
            for spec in group_option_specs_on_path(self._group_trie, job_name)
        }

    def _candidates_group_flags(
        self, segments: list[str], partial: str
    ) -> list[object]:
        """Flags declared by the groups already consumed on the path.

        Mid-path is where a group's flag is legal (``deploy --env prod web
        run``), so this is offered only while the walk is still inside a group.
        Rendered from the shared click-param helper, so a completed flag spells
        exactly like the one that parses (C-D1).
        """
        from functualize.app.adapters.click_params import (
            build_click_params_from_fields,
        )

        trie = self._group_trie
        if trie is None or not segments:
            return []
        specs = trie.group_options_on_path(segments)
        partial_lower = partial.lower()
        items: list[object] = []
        for spec in specs:
            for param in build_click_params_from_fields(spec.fields):
                for opt in param.opts:
                    if not opt.startswith("--"):
                        continue
                    if partial_lower and partial_lower not in opt.lower():
                        continue
                    items.append(
                        _make_dropdown_item(
                            main=opt,
                            prefix="[dim magenta]group[/dim magenta]",
                            description=(getattr(param, "help", "") or ""),
                        )
                    )
        return items[:_MAX_CANDIDATES]

    def _command_mode_candidates(self, text: str, cursor_pos: int) -> list[object]:
        """Candidates for the default command mode.

        Today's five ``CursorContext`` sub-modes are the *internals* of this one
        mode, not peers of `!` or `?`: they all answer "what comes next in a
        command", differing only in which part of it the cursor sits on. Keeping
        them here means adding a sigil mode never has to touch this chain.

        S6b routes the *path* part first: the shell navigates groups by spaces,
        so while the cursor is still inside the group tree the answer is "which
        group/job comes next" (or "which flag does a consumed group declare").
        Only once the walk reaches a leaf job does the line become
        ``<job> <args…>`` and the existing flag/value/positional chain take
        over — unchanged, and now fed a correctly resolved job name.
        """
        before = text[:cursor_pos]
        ends_open = bool(before) and not before[-1].isspace()
        raw = before.split()
        partial = raw[-1] if (raw and ends_open) else ""
        completed = raw[:-1] if (raw and ends_open) else raw

        node, segments, resolved_job = self._walk_path(completed)
        if node is not None and resolved_job is None:
            # Still inside the group tree.
            if partial.startswith("-"):
                return self._candidates_group_flags(segments, partial)
            return self._candidates_path(node, segments, partial)
        if resolved_job is not None:
            # Rewrite as `<dotted job> <args…>` so the existing chain resolves
            # the job it already knows how to look up, without learning paths.
            consumed_tokens = len(segments)
            args = completed[consumed_tokens:]
            text = " ".join([resolved_job, *args]) + (" " if not ends_open else " ")
            text += partial
            cursor_pos = len(text)

        try:
            ctx = self._parse_context(text, cursor_pos)
        except Exception as exc:
            # _parse_context() is a text-parsing call, not a query_one
            # lookup — log so cursor-context parsing failures are visible
            # instead of silently returning no candidates.
            logger.warning(
                f"get_candidates: _parse_context() failed ({type(exc).__name__}): {exc}"
            )
            return []

        if ctx.mode == "command":
            return self._candidates_command(ctx)
        elif ctx.mode == "subcommand":
            return self._candidates_subcommand(ctx)
        elif ctx.mode == "flag":
            return self._candidates_flag(ctx, text)
        elif ctx.mode == "value":
            return self._candidates_value(ctx)
        elif ctx.mode == "positional":
            return self._candidates_positional(ctx)

        return []

    def apply_completion(self, value: str) -> None:
        """Insert completion, auto-quoting values with spaces.

        Delegates quoting to quote_for_insertion which wraps values
        containing spaces in appropriate quotes.

        Args:
            value: The raw completion value to insert.
        """
        # The actual insertion into the Input widget is handled by
        # textual-autocomplete's base class. This method transforms
        # the value before insertion.
        # When integrated with the real AutoComplete widget, the base
        # class calls this to get the final insertion text.
        self._last_applied = quote_for_insertion(value)

    def get_completion_value(self, value: str) -> str:
        """Return the quoted value suitable for insertion.

        This is the pure-logic helper that apply_completion uses.
        Useful for testing without the full widget context.

        Args:
            value: The raw completion value.

        Returns:
            The value with appropriate quoting applied.
        """
        return quote_for_insertion(value)

    # ─── Private helpers ─────────────────────────────────────────────────

    def _parse_context(self, text: str, cursor_pos: int) -> CursorContext:
        """Parse cursor context using the shared module."""
        return parse_cursor_context(
            text,
            cursor_pos,
            self._cached_job_names,
            positional_params=self._cached_positional_params,
            # Every builtin, not just the ones with subcommands: the parser
            # uses membership to know it is inside a builtin invocation and
            # must stop offering top-level commands.
            builtin_subcommands=_BUILTIN_SUBCOMMAND_NAMES,
        )

    def _candidates_command(self, ctx: CursorContext) -> list[object]:
        """Generate command-mode candidates (job names + builtins)."""
        candidates: list[object] = []
        partial_lower = ctx.partial.lower()

        builtins = _BUILTIN_COMMANDS

        # Collect all command entries with scores
        entries: list[tuple[float, str, str, str]] = []  # (score, name, desc, badge)

        for job in self._cached_jobs:
            name = job.name
            if partial_lower and partial_lower not in name.lower():
                continue
            desc = ""
            if job.docstring:
                desc = job.docstring.strip().split("\n")[0][:60]
            prov = self._provenance.get_provenance(job)
            badge = f"[{prov.badge_style}]{prov.display_label}[/{prov.badge_style}]"
            # Score: prefix match > substring match
            score = 2.0 if name.lower().startswith(partial_lower) else 1.0
            entries.append((score, name, desc, badge))

        for name, desc in builtins.items():
            if partial_lower and partial_lower not in name.lower():
                continue
            badge = "[dim cyan]built-in[/dim cyan]"
            score = 2.0 if name.lower().startswith(partial_lower) else 1.0
            entries.append((score, name, desc, badge))

        # Sort by score (descending), then alphabetically
        entries.sort(key=lambda e: (-e[0], e[1]))

        for _, name, desc, badge in entries[:_MAX_CANDIDATES]:
            candidates.append(
                _make_dropdown_item(main=name, prefix=badge, description=desc)
            )

        return candidates

    def _candidates_subcommand(self, ctx: CursorContext) -> list[object]:
        """Generate subcommand-mode candidates for a builtin command.

        At depth 1 (``builtin`` → child names), uses the registry's child
        descriptions. At depth 2 (``builtin config`` → config's subcommands),
        drills into the nested subcommand map.
        """
        from functualize._cli.builtins import builtin_child_descriptions

        if ctx.field_name:
            inner = _BUILTIN_SUBCOMMANDS.get(ctx.job_name or "", {}).get(
                ctx.field_name, {}
            )
            subcommands: dict[str, str] = inner
        else:
            subcommands = builtin_child_descriptions()

        partial_lower = ctx.partial.lower()
        badge = "[dim cyan]built-in[/dim cyan]"

        entries: list[tuple[float, str, str]] = []
        for name, desc in subcommands.items():
            if partial_lower and partial_lower not in name.lower():
                continue
            score = 2.0 if name.lower().startswith(partial_lower) else 1.0
            entries.append((score, name, desc))

        entries.sort(key=lambda e: (-e[0], e[1]))

        return [
            _make_dropdown_item(main=name, prefix=badge, description=desc)
            for _, name, desc in entries[:_MAX_CANDIDATES]
        ]

    def _candidates_flag(self, ctx: CursorContext, full_text: str) -> list[object]:
        """Generate flag-mode candidates with used-flag filtering."""
        if not ctx.job_name:
            return []

        # Use get_job() for accurate field metadata (positional, short_flag)
        # because get_jobs() may return descriptors without those fields populated.
        job = self._app.get_job(ctx.job_name)
        if job is None:
            job = self._cached_job_map.get(ctx.job_name)
        if job is None:
            return []

        # Build FlagDescriptors from job parameters, extracting short names
        fields = job.config_fields if job.config_fields else job.parameters
        # The GroupOptions injection parameter is not a flag — it is where the
        # resolved group instance lands, and the flags it stands for are
        # offered mid-path. Same exclusion the CLI, MCP and pre-flight apply.
        injection_types = self._injection_type_names(ctx.job_name)
        short_names = _extract_short_names(job)
        all_flags: list[FlagDescriptor] = []
        for field in fields:
            # Skip internal parameters
            if field.name in ("rc", "run_context", "log"):
                continue
            if (getattr(field, "type_annotation", "") or "").strip() in injection_types:
                continue
            # Skip positional arguments — they don't use --flag form
            if getattr(field, "positional", False):
                continue
            is_list = field.type_annotation.startswith("list[")
            all_flags.append(
                FlagDescriptor(
                    long_name=field.name,
                    short_name=short_names.get(field.name)
                    or getattr(field, "short_flag", None),
                    is_list_type=is_list,
                )
            )

        # Get tokens for used-flag filtering
        tokens = tokenize_smart_bar(full_text)
        # Tokens after the job name are the used tokens
        used_tokens = tokens[1:] if len(tokens) > 1 else []

        # Filter out already-used single-value flags
        available_flags = filter_used_flags(all_flags, used_tokens)

        # Build candidates
        candidates: list[object] = []
        partial_lower = ctx.partial.lower().lstrip("-")

        for flag in available_flags:
            long_form = f"--{flag.long_name.replace('_', '-')}"

            # Normalize short_name: strip any leading dash(es) to get just the letter
            short_letter = flag.short_name.lstrip("-") if flag.short_name else None

            # Display as "-g/--greeting" when short flag is available
            flag_display = f"-{short_letter}/{long_form}" if short_letter else long_form

            if partial_lower and partial_lower not in flag.long_name.lower():
                continue

            # Find the corresponding field for description
            field_desc = next((f for f in fields if f.name == flag.long_name), None)
            desc = field_desc.description if field_desc else ""
            type_hint = field_desc.type_annotation if field_desc else ""

            prefix = f"[dim]{type_hint}[/dim]" if type_hint else ""

            # Display shows "-g/--greeting" but insertion is just "--greeting"
            candidates.append(
                _make_dropdown_item(
                    main=flag_display,
                    prefix=prefix,
                    description=desc,
                    insertion_value=long_form,
                )
            )

        return candidates[:_MAX_CANDIDATES]

    def _candidates_value(self, ctx: CursorContext) -> list[object]:
        """Generate value-mode candidates from choices, history, and paths."""
        if not ctx.job_name or not ctx.field_name:
            return []

        job = self._cached_job_map.get(ctx.job_name)
        if job is None:
            return []

        # Find the field descriptor
        fields = job.config_fields if job.config_fields else job.parameters
        target_field: FieldDescriptor | None = None
        for f in fields:
            if f.name == ctx.field_name:
                target_field = f
                break

        candidates: list[object] = []
        partial_lower = ctx.partial.lower()

        # Source 1: Choices (enum values)
        if target_field and target_field.choices:
            for choice in target_field.choices:
                if partial_lower and partial_lower not in choice.lower():
                    continue
                candidates.append(
                    _make_dropdown_item(
                        main=choice,
                        prefix="[bold green]choices[/bold green]",
                        description="enum value",
                    )
                )

        # Source 2: History
        if self._history and ctx.job_name and ctx.field_name:
            history_values = self._history.get_history(ctx.job_name, ctx.field_name)
            for val in history_values:
                if partial_lower and partial_lower not in val.lower():
                    continue
                # Avoid duplicates with choices
                if (
                    target_field
                    and target_field.choices
                    and val in target_field.choices
                ):
                    continue
                candidates.append(
                    _make_dropdown_item(
                        main=val,
                        prefix="[bold yellow]history[/bold yellow]",
                        description="from history",
                    )
                )

        # Source 3: Path suggestions (for Path-typed fields)
        if target_field and self._path_scanner:
            type_lower = target_field.type_annotation.lower()
            if "path" in type_lower or "dir" in type_lower:
                from pathlib import Path

                cwd = Path.cwd()
                file_filter: str | None = None
                # DirectoryPath: show only directories
                if "directorypath" in type_lower or (
                    "dir" in type_lower and "path" not in type_lower
                ):
                    file_filter = "directory"
                # FilePath: show both files and dirs for navigation,
                # but only files are selectable (filter=None shows both)

                suggestions = self._path_scanner.scan(
                    ctx.partial, cwd, path_mode=None, file_filter=file_filter
                )
                for suggestion in suggestions:
                    if len(candidates) >= _MAX_CANDIDATES:
                        break
                    candidates.append(
                        _make_dropdown_item(
                            main=suggestion.display,
                            prefix="[dim]path[/dim]",
                            description="📁" if suggestion.is_directory else "📄",
                        )
                    )

        return candidates[:_MAX_CANDIDATES]

    def _candidates_positional(self, ctx: CursorContext) -> list[object]:
        """Generate positional-mode candidates with [N] 1-based prefix.

        Requirement 19.3: Each candidate shows [N] index prefix (1-based),
        parameter name, type hint, and description.
        Requirement 19.4: Sources from choices (if defined) or history of
        previously-used values for that positional index.
        """
        if not ctx.job_name or ctx.positional_index is None:
            return []

        job = self._cached_job_map.get(ctx.job_name)
        if job is None:
            return []

        candidates: list[object] = []
        partial_lower = ctx.partial.lower()
        idx = ctx.positional_index

        # Find the positional parameter at this index
        fields = job.config_fields if job.config_fields else job.parameters
        positional_fields = [
            f for f in fields if f.name not in ("rc", "run_context", "log")
        ]

        target_field: FieldDescriptor | None = None
        if idx < len(positional_fields):
            target_field = positional_fields[idx]

        # 1-based index per requirement 19.3
        display_idx = idx + 1

        # Build prefix: [N] param_name  type_hint
        param_name = target_field.name if target_field else f"arg{display_idx}"
        type_hint = target_field.type_annotation if target_field else "str"
        prefix_badge = (
            f"[bold cyan]\\[{display_idx}][/bold cyan] "
            f"{param_name}  [dim]{type_hint}[/dim]"
        )

        # Description from the field
        field_desc = target_field.description if target_field else ""

        # Source 1: Choices for this positional parameter (Req 19.4)
        if target_field and target_field.choices:
            for choice in target_field.choices:
                if partial_lower and partial_lower not in choice.lower():
                    continue
                candidates.append(
                    _make_dropdown_item(
                        main=choice,
                        prefix=prefix_badge,
                        description=field_desc,
                    )
                )

        # Source 2: History for this positional index (Req 19.4)
        if self._history and ctx.job_name:
            # History key for positional args uses the field name or index
            field_key = target_field.name if target_field else f"_positional_{idx}"
            history_values = self._history.get_history(ctx.job_name, field_key)
            for val in history_values:
                if partial_lower and partial_lower not in val.lower():
                    continue
                # Avoid duplicates with choices
                if (
                    target_field
                    and target_field.choices
                    and val in target_field.choices
                ):
                    continue
                candidates.append(
                    _make_dropdown_item(
                        main=val,
                        prefix=prefix_badge,
                        description=field_desc or "from history",
                    )
                )

        # If no choices or history, show a hint candidate with the parameter info
        if not candidates and target_field:
            candidates.append(
                _make_dropdown_item(
                    main=f"<{param_name}>",
                    prefix=prefix_badge,
                    description=field_desc,
                )
            )

        return candidates[:_MAX_CANDIDATES]


# ─── Helper for creating DropdownItem-compatible objects ─────────────────


def _extract_short_names(job: JobDescriptor) -> dict[str, str]:
    """Extract short flag names from a job's Option markers.

    Prefers the cached FieldDescriptor metadata (available without a live
    function on warm boots); falls back to inspecting the live function's
    type annotations for Option markers (e.g., Option("-t", "--target")).

    Args:
        job: The JobDescriptor to inspect.

    Returns:
        A dict mapping parameter name → short flag letter (without dash).
        Empty dict if no short flags are declared or discoverable.
    """
    cached_shorts = {
        f.name: flag.lstrip("-")
        for f in (job.config_fields or [])
        if (flag := getattr(f, "short_flag", None))
    }
    if cached_shorts:
        return cached_shorts

    if job.function is None:
        return {}

    import inspect

    try:
        sig = inspect.signature(job.function)
    except (ValueError, TypeError):
        return {}

    short_names: dict[str, str] = {}

    # Resolved, not raw: a job module using PEP 563 stores every annotation as
    # a string, and unwrap_annotated() finds no metadata in a string, so every
    # short flag would silently vanish from completion.
    from functualize.app.utils import resolved_hints

    hints = resolved_hints(job.function)

    for param_name, param in sig.parameters.items():
        annotation = hints.get(param_name, param.annotation)
        if annotation is inspect.Parameter.empty:
            continue

        # Unwrap Annotated[T, ...] to get metadata
        try:
            from functualize._cli.annotation_utils import unwrap_annotated

            _, metadata = unwrap_annotated(annotation)
        except TypeError:
            # unwrap_annotated() can raise TypeError on malformed/exotic
            # generic annotations; narrower than Exception since this is
            # not a query_one lookup and no logger is available at
            # module scope — skip this parameter's short-flag extraction.
            continue

        # Look for Option marker in metadata
        for meta in metadata:
            if type(meta).__name__ == "Option" and hasattr(meta, "short"):
                if meta.short and len(meta.short) == 2 and meta.short.startswith("-"):
                    short_names[param_name] = meta.short[1]
                break

    return short_names


class _DropdownItemStub:
    """Lightweight stand-in for DropdownItem when textual-autocomplete is unavailable.

    At runtime inside the TUI, the real DropdownItem from
    textual_autocomplete is used. This stub allows the module's logic
    to be tested independently.
    """

    __slots__ = ("main", "prefix", "description")

    def __init__(self, main: str, prefix: str = "", description: str = "") -> None:
        self.main = main
        self.prefix = prefix
        self.description = description

    def __repr__(self) -> str:
        return (
            f"_DropdownItemStub(main={self.main!r}, "
            f"prefix={self.prefix!r}, description={self.description!r})"
        )


def _make_dropdown_item(
    main: str,
    prefix: str = "",
    description: str = "",
    insertion_value: str | None = None,
) -> object:
    """Create a FunctualizeDropdownItem or stub depending on library availability.

    Display format (with Rich styling):
      command_name  (source)  — description
      Bold name, dim source badge, italic description.

    Insertion value: the insertion_value if provided, otherwise main.

    Args:
        main: The display text for the dropdown item.
        prefix: Source badge with Rich markup (e.g., "[bold green]local[/bold green]").
        description: Short description of what this item does.
        insertion_value: The value to insert on selection. Defaults to main if not given.
    """
    insert_val = insertion_value if insertion_value is not None else main
    try:
        from rich.text import Text
        from textual.content import Content

        from functualize._cli.tui.functualize_autocomplete import (
            FunctualizeDropdownItem,
        )

        # Build a Rich-formatted display string
        display = Text()
        display.append(main, style="bold")
        if prefix:
            badge = _strip_markup(prefix)
            display.append(f"  ({badge})", style="dim cyan")
        if description:
            display.append(f"  {description}", style="dim italic")

        # Convert Rich Text to Textual Content for the dropdown
        display_content = Content.from_rich_text(display)

        return FunctualizeDropdownItem(
            main=display_content,
            insertion_value=insert_val,
        )
    except (ImportError, TypeError, AttributeError):
        # Fallback: try without Content.from_rich_text (older Textual)
        try:
            from functualize._cli.tui.functualize_autocomplete import (
                FunctualizeDropdownItem,
            )

            badge = _strip_markup(prefix) if prefix else ""
            parts = [main]
            if badge:
                parts.append(f"({badge})")
            if description:
                parts.append(f"— {description}")
            display_text = "  ".join(parts)
            return FunctualizeDropdownItem(
                main=display_text, insertion_value=insert_val
            )
        except (ImportError, TypeError):
            return _DropdownItemStub(
                main=insert_val, prefix=prefix, description=description
            )


def _strip_markup(text: str) -> str:
    """Remove Rich markup tags from a string, returning plain text.

    e.g. "[bold green]local[/bold green]" → "local"

    Backslash-escaped brackets (Rich's own convention for literal, non-tag
    text, e.g. "\\[1]") are preserved as literal text with the escape
    backslash removed, rather than being stripped like a real markup tag —
    otherwise a literal index marker like "\\[1]" would be erased entirely
    instead of rendering as "[1]".
    """
    import re

    stripped = re.sub(r"(?<!\\)\[/?[^\]]*\]", "", text)
    return stripped.replace("\\[", "[")
