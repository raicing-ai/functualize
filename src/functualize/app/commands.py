"""Concrete :class:`CommandNode` providers — the shell's one command tree.

The protocols live in ``_types/commands.py`` (re-exported from
``functualize.plugin``); they import nothing, because ``_types`` may not. The
*implementations* need a booted app — the trie, the discovery cache, the
execution engine — so they live here, in the public ``app`` package, which is
also the only door ``_cli`` is allowed through ("_cli uses public API only").

``JobCommandProvider`` covers the user namespace. ``ClickCommandProvider`` (C1.3)
will cover the reserved ``builtin`` subtree. The shell composes both into one
tree, which is what finally deletes the "builtins are a separate hidden
namespace" special-casing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from functualize._types.naming import BUILTIN_SEGMENT, NodeKind
from functualize.app.utils import build_group_trie

if TYPE_CHECKING:
    from collections.abc import Sequence

    from functualize._types.descriptors import FieldDescriptor, JobDescriptor
    from functualize._types.naming import TrieNode
    from functualize.app.core import FunctualizeApp
    from functualize.plugin import CommandNode

__all__ = [
    "ClickCommandProvider",
    "JobCommandProvider",
    "build_command_tree",
    "builtin_context_obj",
    "resolve_command_path",
]


class JobNode:
    """A :class:`~functualize.plugin.CommandNode` over one namespace-trie node.

    Wraps a ``TrieNode``, so the *shape* answers (``children``) come straight
    from the trie and cost no imports. The runtime answers (``params``,
    ``execute``) resolve against the descriptor the node's payload names.

    A node may be runnable, navigable, or **both** — the duality case
    (``deploy`` the job, with ``deploy web`` beneath it). ``children()`` and a
    runnable payload are independent here, exactly as they are in the trie.
    """

    def __init__(
        self,
        node: TrieNode,
        jobs_by_path: dict[str, JobDescriptor],
        app: FunctualizeApp,
    ) -> None:
        self._node = node
        self._jobs_by_path = jobs_by_path
        self._app = app

    # ── identity ─────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return self._node.segment

    @property
    def help_text(self) -> str:
        descriptor = self._descriptor
        if descriptor is not None and descriptor.docstring:
            return descriptor.docstring.strip().split("\n")[0]
        if self._node.children:
            return f"{self._node.segment} commands"
        return ""

    @property
    def needs_terminal(self) -> bool:
        """True when the job takes over the terminal.

        For a job node this is the descriptor's ``requires_tty`` — the job
        author's declaration is exactly the fact the shell needs. A pure group
        runs nothing, so it never needs the terminal.
        """
        descriptor = self._descriptor
        return bool(descriptor is not None and descriptor.requires_tty)

    # ── tree ─────────────────────────────────────────────────────────────

    def children(self) -> list[CommandNode]:
        """Direct children, sorted — straight off the trie, no imports."""
        return [
            JobNode(child, self._jobs_by_path, self._app)
            for child in sorted(self._node.children.values(), key=lambda c: c.segment)
        ]

    def params(self) -> list[FieldDescriptor]:
        """CLI-facing parameters, read from **cached** descriptor metadata.

        Deliberately does not materialize: ``config_fields``/``parameters`` are
        serialized into the discovery cache, so a warm boot answers this without
        importing the job module. Prefers ``config_fields`` (the expanded
        Pydantic model) over the raw signature params, matching how the CLI and
        the in-process introspector already choose.
        """
        descriptor = self._descriptor
        if descriptor is None:
            return []
        return descriptor.config_fields or descriptor.parameters

    def execute(self, args: Sequence[str]) -> int:
        """Run this node's job. **This is the call that imports the module.**"""
        from functualize.app.adapters.click_params import (
            create_job_click_command,
            invoke_command_capturing,
        )

        descriptor = self._descriptor
        if descriptor is None:
            return 1

        registered = self._app.execution_engine.materialize_job(descriptor.name)
        command = create_job_click_command(
            name=descriptor.name,
            function=registered.function,
            job_config_class=registered.config_class,
            app=self._app,
            command_name=descriptor.func_name,
        )
        return invoke_command_capturing(
            command, list(args), "none", prog_name=descriptor.func_name
        )

    # ── internals ────────────────────────────────────────────────────────

    @property
    def _descriptor(self) -> JobDescriptor | None:
        payload = self._node.payload
        if payload is None:
            return None
        return self._jobs_by_path.get(payload)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"JobNode({'.'.join(self._node.path)!r})"


class JobCommandProvider:
    """Top-level command nodes over the job/group namespace.

    Builds the trie from the booted app's descriptors — the same rows
    ``register_discovered_jobs`` mirrors into click — so the shell's tree and
    the CLI's group tree cannot disagree about shape.

    ``builtin=False``: this provider owns the *user* namespace only. The
    reserved subtree arrives from ``ClickCommandProvider``, so composing the two
    is what produces the full tree.
    """

    def __init__(self, app: FunctualizeApp) -> None:
        self._app = app

    def nodes(self) -> list[CommandNode]:
        jobs: list[Any] = list(self._app.get_jobs())
        jobs_by_path = {descriptor.name: descriptor for descriptor in jobs}
        trie = build_group_trie(
            [(d.group, d.name, NodeKind.JOB.value) for d in jobs],
            builtin=False,
        )
        return [
            JobNode(child, jobs_by_path, self._app)
            for child in sorted(trie.root.children.values(), key=lambda c: c.segment)
        ]


class ClickCommandNode:
    """A :class:`~functualize.plugin.CommandNode` over a ``click`` command.

    Wraps the reserved ``builtin`` subtree so it enters the shell's tree as the
    same node type a job does. Nothing downstream needs to know which provider a
    node came from — that is what removes the builtin special-casing.
    """

    def __init__(
        self,
        command: Any,
        *,
        path: tuple[str, ...],
        needs_terminal: bool,
        app: FunctualizeApp | None = None,
    ) -> None:
        self._command = command
        self._path = path
        self._needs_terminal = needs_terminal
        self._app = app

    @property
    def name(self) -> str:
        """The **registration key**, not ``click.Command.name``.

        They can differ: ``_mount(show_info_command, "info")`` registers under
        ``info`` while the command object keeps the name ``show-info``. The key
        is what a user types, so it is what the tree exposes.
        """
        return self._path[-1] if self._path else str(self._command.name or "")

    @property
    def help_text(self) -> str:
        return (self._command.get_short_help_str(limit=200) or "").strip()

    @property
    def needs_terminal(self) -> bool:
        """Resolved once, at construction — see the ``CommandNode`` docstring.

        ``BuiltinCommand.needs_terminal`` is a predicate over args because it
        models a command *family*; this node is a single path, so the provider
        answers it per-child while building the tree.
        """
        return self._needs_terminal

    def children(self) -> list[CommandNode]:
        commands = getattr(self._command, "commands", None)
        if not commands:
            return []
        family = self._path[1] if len(self._path) > 1 else None
        return [
            ClickCommandNode(
                child,
                path=(*self._path, segment),
                needs_terminal=_builtin_needs_terminal(family or segment, segment),
                app=self._app,
            )
            for segment, child in sorted(commands.items())
        ]

    def params(self) -> list[FieldDescriptor]:
        """Bridge click's own params onto ``FieldDescriptor``.

        Not a parallel param model: the shell reads one param type regardless of
        whether a node came from a job signature or a click command.
        """
        from functualize._types.descriptors import FieldDescriptor

        fields: list[FieldDescriptor] = []
        for param in getattr(self._command, "params", []):
            name = getattr(param, "name", None)
            if not name or name == "help":
                continue
            param_type = getattr(param, "type", None)
            fields.append(
                FieldDescriptor(
                    name=name,
                    type_annotation=getattr(param_type, "name", "str") or "str",
                    default=getattr(param, "default", None),
                    description=(getattr(param, "help", "") or ""),
                    required=bool(getattr(param, "required", False)),
                    choices=list(getattr(param_type, "choices", []) or []) or None,
                    positional=getattr(param, "param_type_name", "") != "option",
                )
            )
        return fields

    def execute(self, args: Sequence[str]) -> int:
        """Run this command through click, with the context the builtins expect.

        The ``obj`` matters: invoking a leaf directly never runs the root
        group's callback, so nothing would populate ``ctx.obj`` and
        ``builtin info`` — which reads ``ctx.find_root().obj["app"]`` — failed
        with "No app context available." A node that cannot run itself is not
        the self-contained node the protocol promises.
        """
        from functualize.app.adapters.click_params import invoke_command_capturing

        return invoke_command_capturing(
            self._command,
            list(args),
            "none",
            prog_name=" ".join(self._path),
            obj=builtin_context_obj(self._app),
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ClickCommandNode({'.'.join(self._path)!r})"


def builtin_context_obj(app: FunctualizeApp | None) -> dict[str, Any]:
    """The click context object the builtin commands read.

    ``builtin info`` reads ``ctx.find_root().obj["app"]``; ``cli_config`` only
    enriches its "Config Resolution" section, so a failure there degrades that
    section rather than the whole invocation.
    """
    import logging

    obj: dict[str, Any] = {"app": app}
    try:
        from functualize._cli.config import resolve_cli_config

        obj["cli_config"] = resolve_cli_config()
    except Exception as exc:
        logging.getLogger(__name__).warning(
            f"builtin_context_obj: resolve_cli_config() failed "
            f"({type(exc).__name__}): {exc}"
        )
    return obj


def _builtin_needs_terminal(family: str, segment: str) -> bool:
    """Does ``func builtin <family> <segment>`` take over the terminal?

    Collapses ``BuiltinCommand``'s family-level predicate to this one path.
    """
    from functualize._cli.builtins import get_builtin

    command = get_builtin(family)
    if command is None:
        return False
    return bool(command.needs_terminal([segment]))


class ClickCommandProvider:
    """The reserved ``builtin`` subtree, as command nodes.

    Reads the group **B2b already mounted** on ``app.cli_command`` rather than
    building a second one, so the shell and the CLI cannot drift about what
    ``func builtin …`` contains.
    """

    def __init__(self, app: FunctualizeApp) -> None:
        self._app = app

    def nodes(self) -> list[CommandNode]:
        group = self._app.cli_command.commands.get(BUILTIN_SEGMENT)
        if group is None:  # pragma: no cover - B2b mounts it unconditionally
            return []
        return [
            ClickCommandNode(
                group, path=(BUILTIN_SEGMENT,), needs_terminal=False, app=self._app
            )
        ]


def build_command_tree(app: FunctualizeApp) -> list[CommandNode]:
    """The shell's **one** command tree: user jobs plus the reserved subtree.

    Composing the two providers here is what lets every downstream surface —
    listing, completion, preflight, execution — stop asking "is this a builtin?".
    Jobs come first so the reserved node sorts last in listings, matching the
    CLI's own help ordering.
    """
    nodes: list[CommandNode] = list(JobCommandProvider(app).nodes())
    nodes.extend(ClickCommandProvider(app).nodes())
    return nodes


def resolve_command_path(
    nodes: Sequence[CommandNode], tokens: Sequence[str]
) -> tuple[CommandNode | None, list[str]]:
    """Walk ``tokens`` down the tree, returning ``(deepest_node, leftovers)``.

    Stops at the first token that matches no child, so a trailing argument does
    not invalidate the command that precedes it. **Leftovers are returned, not
    discarded**, because the caller needs them to tell "``builtin cache`` — pick
    a subcommand" apart from "``builtin config bogus`` — no such subcommand".
    """
    current: CommandNode | None = None
    candidates = list(nodes)
    consumed = 0
    for token in tokens:
        match = next((n for n in candidates if n.name == token), None)
        if match is None:
            break
        current = match
        candidates = match.children()
        consumed += 1
    return current, list(tokens[consumed:])
