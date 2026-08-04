"""Completion data extraction — the word lists, with no shell in sight (T44a).

`func` warm boot is ~375–520ms; a completion that boots the app on every TAB is
unusable. So completion is the direnv model: boot **once**, at generation time,
bake the answers into a static shell script (T44b), and put zero Python in the
TAB path. This module is the "boot once and read the answers" half — pure data,
no shell emission, independently testable.

Everything here is extracted from the app's own in-memory state through the
**same** primitives every other surface uses: the namespace trie for the
group/job structure and group-option inheritance (`build_group_trie`,
`group_options_on_path`), and the job descriptors for a job's own flags. That
reuse is the point. Shell completion is a *settable* surface — a place a field
name is shown — and the five leaks this feature already shipped were all one
surface disagreeing with another about what a field *is*. If completion
computed its own idea of "which flags does this job have", it would be the sixth.
`tests/group_options/test_surface_parity.py` has a probe that fails if it drifts.

The partition falls out for free: a job's own flags come from
`descriptor.config_fields`, which already excludes the `GroupOptions` injection
parameter (it is never chosen as the config class, see `_discovery/sync.py`), and
the group's flags come from the trie's inheritance walk. So an injection point
(`opts: DeployOptions`) appears in neither — exactly as it must.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["CompletionData", "extract_completion_data"]


@dataclass(frozen=True)
class CompletionData:
    """The word lists a static completion script needs.

    Attributes:
        command_tree: Space-joined command path → the words that may follow it.
            ``""`` is the top level (groups + jobs + ``builtin``); ``"deploy"``
            → its children and, if it is also runnable, its flags; a leaf job →
            its flags. Keyed by the space-separated spelling the shell matches
            against, not the dotted canonical name, so a script can look up
            ``$words`` directly.
        flag_choices: Space-joined job path → ``{flag: [choice, …]}`` for
            enum-valued flags, so ``--env <TAB>`` can offer ``dev prod`` rather
            than nothing.
    """

    command_tree: dict[str, list[str]] = field(default_factory=dict)
    flag_choices: dict[str, dict[str, list[str]]] = field(default_factory=dict)

    def paths(self) -> list[str]:
        """Every command path with completions, sorted — for a stable script."""
        return sorted(self.command_tree)


def _flag_opts(fields: list[Any]) -> list[str]:
    """The ``--long`` / ``-s`` spellings a set of fields contributes.

    Rendered through the shared click-param builder, so a completed flag spells
    exactly like the one that parses — the same helper the SmartBar and the CLI
    use (C-D1). A second copy of this loop is how a completion flag would drift
    from the flag it is supposed to complete.
    """
    from functualize.app.adapters.click_params import build_click_params_from_fields

    opts: list[str] = []
    for param in build_click_params_from_fields(fields):
        for opt in getattr(param, "opts", ()):
            if opt.startswith("-"):
                opts.append(opt)
    return opts


def _field_choices(fields: list[Any]) -> dict[str, list[str]]:
    """``{--flag: [choice, …]}`` for the enum-valued fields in ``fields``."""
    from functualize.app.adapters.click_params import build_click_params_from_fields

    params = {p.name: p for p in build_click_params_from_fields(fields)}
    choices: dict[str, list[str]] = {}
    for f in fields:
        values = getattr(f, "choices", None)
        if not values:
            continue
        param = params.get(f.name)
        long_opts = [o for o in getattr(param, "opts", ()) if o.startswith("--")]
        if long_opts:
            choices[long_opts[0]] = list(values)
    return choices


def _builtin_structure() -> tuple[list[str], dict[str, list[str]]]:
    """``builtin``'s children and each child's subcommands, from the registry.

    Read from ``BUILTIN_COMMANDS`` rather than the trie: the trie seeds the
    ``builtin`` node but not the two-level subcommand shape (``cache show``),
    and the registry is the single source of truth for that shape anyway (a
    test already pins the derived lists to it).
    """
    from functualize._cli.builtins import BUILTIN_COMMANDS

    children = [c.name for c in BUILTIN_COMMANDS]
    subcommands = {
        c.name: [name for name, _ in c.subcommands]
        for c in BUILTIN_COMMANDS
        if c.subcommands
    }
    return children, subcommands


def extract_completion_data(func_app: Any) -> CompletionData:
    """Extract the completion word lists from a **booted** app (T44a).

    The app must already be booted (its jobs discovered) — this is called once,
    from ``func builtin shell-init``, which the CLI boots for exactly this. It
    imports no job module and runs nothing: everything comes from descriptors
    and the trie.
    """
    from pathlib import Path

    from functualize.app.utils import (
        build_group_trie,
        read_group_options_from_cache,
        resolve_cache_path,
    )

    jobs = func_app.get_jobs()
    specs = read_group_options_from_cache(resolve_cache_path(Path.cwd())) or None
    trie = build_group_trie(
        [(j.group, j.name, "job") for j in jobs],
        group_options=specs,
    )

    # Descriptor by canonical dotted name, for a job's own flags/choices.
    by_name = {j.name: j for j in jobs}

    command_tree: dict[str, list[str]] = {}
    flag_choices: dict[str, dict[str, list[str]]] = {}

    def job_flags(dotted: str, segments: list[str]) -> list[str]:
        """A job's flags: its own arguments plus the group flags it inherits.

        Both through the shared builder, so the partition is exactly the one
        the CLI and TUI compute — the injection point is already absent from
        `config_fields`, so it is absent here too.
        """
        descriptor = by_name.get(dotted)
        own = list(getattr(descriptor, "config_fields", []) or []) if descriptor else []
        opts = _flag_opts(own)
        choices = _field_choices(own)
        # Inherited group options: the group path is the name minus the leaf.
        # Their enum values are choices too — `--env` is a group flag here, so
        # scanning only the job's own fields would leave it uncompletable.
        if len(segments) >= 2 and trie is not None:
            for spec in trie.group_options_on_path(segments[:-1]):
                opts.extend(_flag_opts(spec.fields))
                choices.update(_field_choices(spec.fields))
        if choices:
            flag_choices[" ".join(segments)] = choices
        return opts

    def walk(node: Any, segments: list[str]) -> None:
        from functualize.app.utils import NodeKind

        path_key = " ".join(segments)
        child_segments = sorted(node.children)
        words: list[str] = list(child_segments)

        # A runnable node also offers its flags after it. The `builtin` subtree
        # is handled separately (its shape is two-level and registry-owned), so
        # it is not recursed into here.
        if node.kind is not NodeKind.BUILTIN and node.payload is not None:
            words.extend(job_flags(node.payload, segments))

        if words:
            command_tree[path_key] = _dedupe(words)

        for child in node.children.values():
            if child.kind is NodeKind.BUILTIN:
                continue
            walk(child, [*segments, child.segment])

    walk(trie.root, [])

    # Builtin subtree, from the registry.
    builtin_children, builtin_subs = _builtin_structure()
    top = command_tree.get("", [])
    command_tree[""] = _dedupe([*top, "builtin"])
    command_tree["builtin"] = builtin_children
    for child, subs in builtin_subs.items():
        command_tree[f"builtin {child}"] = subs

    return CompletionData(command_tree=command_tree, flag_choices=flag_choices)


def _dedupe(words: list[str]) -> list[str]:
    """Order-preserving de-duplication, so a stable list reads predictably."""
    return list(dict.fromkeys(words))
