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
    "COMMAND_KIND_BUILTIN",
    "COMMAND_KIND_JOB",
    "COMMAND_KIND_PLUGIN",
    "ClickCommandProvider",
    "command_kind",
    "JobCommandProvider",
    "PluginCommandNode",
    "PluginCommandProvider",
    "PluginNamespaceNode",
    "job_trie_path",
    "plugin_command_path",
    "unshadowed_plugin_commands",
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

        They can differ: ``_mount`` takes the key as its own argument, so a
        command object named ``show-info`` can register under ``info``. The key
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
            name = _param_public_name(param)
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


def _param_public_name(param: object) -> str | None:
    """The name a *caller types*, not the Python identifier click binds to.

    Across the tree the invariant is "the flag is derivable from the name":
    a job parameter ``rows`` is passed as ``--rows``, so publishing the name is
    enough. Click breaks that invariant whenever a command spells the two
    differently — ``@click.option("--json", "json_out")`` binds ``json_out``
    while the flag is ``--json`` — and publishing the identifier would tell a
    caller to type ``--json-out``, which does not exist.

    So an option reports its longest declared flag with the dashes stripped,
    restoring the invariant, and an argument reports its identifier because a
    positional has no flag to disagree with.
    """
    declarations = [
        opt
        for opt in getattr(param, "opts", []) or []
        if isinstance(opt, str) and opt.startswith("-")
    ]
    if declarations:
        # Longest wins: `-p/--prune` publishes `prune`, never `p`. The short
        # form is carried separately by ``FieldDescriptor.short_flag``.
        return max(declarations, key=len).lstrip("-")
    identifier = getattr(param, "name", None)
    return identifier if isinstance(identifier, str) else None


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


def job_trie_path(job: Any) -> str:
    """The dotted path a job occupies in the namespace trie.

    Normally just ``job.name``, which already carries its group as a prefix.
    The degenerate case is a descriptor whose ``group`` is *not* a prefix of its
    ``name``: the trie nests the whole name under the group there, so a lookup
    keyed on ``name`` alone would miss it and the job would fail to shadow a
    plugin command sitting at the same path.
    """
    from functualize._primitives.command_paths import job_path

    return job_path(getattr(job, "group", None), str(getattr(job, "name", "")))


def plugin_command_path(cmd: Any) -> str:
    """Where a plugin command sits in the same namespace, as one dotted string.

    ``namespace="mcp"`` + ``name="serve"`` -> ``"mcp.serve"``; a command with no
    namespace is its own path. This is the key both precedence sites compare
    against :func:`job_trie_path`, and it is a *function* rather than an inline
    f-string in two files because the two drifting is the whole defect.
    """
    from functualize._primitives.command_paths import plugin_path

    return plugin_path(getattr(cmd, "namespace", None), str(cmd.name))


def unshadowed_plugin_commands(app: FunctualizeApp) -> list[Any]:
    """Plugin commands a job does not already occupy the path of.

    **A job wins, and the shadowed plugin command is absent rather than skipped
    at each lookup.** Resolving it once, here, is what lets every surface agree:
    the shell's command tree, the CLI's group dispatch and the click adapter all
    read this list, so a command cannot list on one surface and run on another.

    Duplicate plugin paths collapse to the first registration, matching the
    registrar's own first-wins ordering.
    """
    occupied = {job_trie_path(job) for job in app.get_jobs()}
    seen: set[str] = set()
    kept: list[Any] = []
    for cmd in app.get_plugin_commands():
        path = plugin_command_path(cmd)
        if path in occupied or path in seen:
            continue
        seen.add(path)
        kept.append(cmd)
    return kept


class PluginCommandNode:
    """One command a plugin registered, as a tree node.

    A leaf: plugin commands are a flat ``namespace`` plus a ``name``, never a
    deeper hierarchy, so there is nothing under it to navigate to.
    """

    def __init__(self, cmd: Any, *, path: tuple[str, ...]) -> None:
        self._cmd = cmd
        self._path = path

    @property
    def name(self) -> str:
        return str(self._cmd.name)

    @property
    def help_text(self) -> str:
        return (self._cmd.help_text or "").strip().split("\n")[0]

    @property
    def needs_terminal(self) -> bool:
        """The plugin author's declaration, carried straight through.

        Defaults to ``False`` for a plugin that predates the field, which is
        the safe answer: a front-end that captures output from a command that
        did not need the terminal renders it in a panel, where the reverse
        corrupts whatever protocol the command speaks on stdout.
        """
        return bool(getattr(self._cmd, "needs_terminal", False))

    def children(self) -> list[CommandNode]:
        return []

    def params(self) -> list[FieldDescriptor]:
        """The callback's own signature, bridged onto ``FieldDescriptor``.

        Reuses the builder the CLI already runs this callback through, so the
        parameters a pre-flight panel shows are the ones click will parse.
        """
        from functualize._types.descriptors import FieldDescriptor
        from functualize.app.adapters.click_params import (
            create_callback_click_command,
        )

        command = create_callback_click_command(
            self._cmd.name, self._cmd.callback, self._cmd.help_text
        )
        fields: list[FieldDescriptor] = []
        for param in getattr(command, "params", []):
            pname = _param_public_name(param)
            if not pname or pname == "help":
                continue
            param_type = getattr(param, "type", None)
            fields.append(
                FieldDescriptor(
                    name=pname,
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
        """Run the callback through click, under the path the user typed.

        ``prog_name`` is the full path rather than the bare command name, so
        ``--help`` prints ``Usage: func mcp serve`` — a line that can be copied
        and run, which ``Usage: serve`` could not.
        """
        from functualize.app.adapters.click_params import (
            create_callback_click_command,
            invoke_command_capturing,
        )

        command = create_callback_click_command(
            self._cmd.name, self._cmd.callback, self._cmd.help_text
        )
        return invoke_command_capturing(
            command,
            list(args),
            "none",
            prog_name=" ".join(self._path),
            emit_return=True,
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"PluginCommandNode({'.'.join(self._path)!r})"


class PluginNamespaceNode:
    """A plugin namespace — navigable, and not runnable on its own.

    ``func mcp`` names no command; it names the place ``serve`` and its five
    siblings live. Mirrors a pure group ``JobNode``, which likewise carries
    children and refuses to run.
    """

    def __init__(self, namespace: str, commands: list[Any]) -> None:
        self._namespace = namespace
        self._commands = commands

    @property
    def name(self) -> str:
        return self._namespace

    @property
    def help_text(self) -> str:
        n = len(self._commands)
        return f"{n} command{'' if n == 1 else 's'}"

    @property
    def needs_terminal(self) -> bool:
        """A namespace runs nothing, so it can never own the terminal."""
        return False

    def children(self) -> list[CommandNode]:
        return [
            PluginCommandNode(cmd, path=(self._namespace, str(cmd.name)))
            for cmd in sorted(self._commands, key=lambda c: str(c.name))
        ]

    def params(self) -> list[FieldDescriptor]:
        return []

    def execute(self, args: Sequence[str]) -> int:
        """Not runnable — the caller should have listed :meth:`children`."""
        return 1

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"PluginNamespaceNode({self._namespace!r})"


class PluginCommandProvider:
    """Commands registered by plugins, as top-level nodes.

    The third provider, and the reason the others stopped being enough: a
    plugin's commands were reachable through ``func <namespace> <cmd>`` and
    through ``app.cli_command``, but absent from the one tree every shell
    surface reads. So an installed ``functualize-mcp`` was invisible in the
    browser, uncompletable in the input bar, and typing ``mcp serve`` produced
    silence rather than a pre-flight or an error.

    Shadowed commands never reach here — :func:`unshadowed_plugin_commands`
    removes them, so this provider has no precedence policy of its own to drift
    from anyone else's.
    """

    def __init__(self, app: FunctualizeApp) -> None:
        self._app = app

    def nodes(self) -> list[CommandNode]:
        namespaces: dict[str, list[Any]] = {}
        top_level: list[Any] = []
        for cmd in unshadowed_plugin_commands(self._app):
            namespace = getattr(cmd, "namespace", None)
            if namespace:
                # Only the first segment is a top-level node; a dotted
                # namespace is flat here, matching `PluginCommand.namespace`,
                # which is documented as a flat name and not a dotted group.
                namespaces.setdefault(str(namespace), []).append(cmd)
            else:
                top_level.append(cmd)

        nodes: list[CommandNode] = [
            PluginCommandNode(cmd, path=(str(cmd.name),))
            for cmd in sorted(top_level, key=lambda c: str(c.name))
        ]
        nodes.extend(
            PluginNamespaceNode(namespace, commands)
            for namespace, commands in sorted(namespaces.items())
        )
        return nodes


#: What a tree node came from, for surfaces that must *say* so.
#:
#: ``CommandNode`` deliberately does not distinguish a job from a builtin --
#: "Nothing here distinguishes a job from a builtin; that is the point" -- and
#: nothing about *running* a node needs to. But two surfaces have to report
#: provenance rather than act on it: the job browser prints a source column,
#: and `builtin info schema` publishes a `kind` an agent filters on. Answering
#: that here, in one function, keeps it off the protocol and keeps the two
#: surfaces from inventing separate answers.
COMMAND_KIND_JOB = "job"
COMMAND_KIND_PLUGIN = "plugin"
COMMAND_KIND_BUILTIN = "builtin"


def command_kind(node: Any) -> str:
    """Which provider produced ``node`` — for display and filtering only.

    Never branch execution on this. A caller that needs to *do* something
    different per kind is re-introducing the special-casing the one tree
    removed; ``needs_terminal`` and ``params()`` already carry every behavioural
    difference a surface legitimately needs.
    """
    if isinstance(node, (PluginCommandNode, PluginNamespaceNode)):
        return COMMAND_KIND_PLUGIN
    if isinstance(node, ClickCommandNode):
        return COMMAND_KIND_BUILTIN
    return COMMAND_KIND_JOB


def build_command_tree(app: FunctualizeApp) -> list[CommandNode]:
    """The shell's one command tree: jobs, plugin commands, reserved subtree.

    Composing the providers here is what lets every downstream surface —
    listing, completion, preflight, execution — stop asking "is this a builtin?"
    or "is this from a plugin?". Jobs come first and the reserved node sorts
    last, matching the CLI's own help ordering.

    A job wins over a plugin command on an exact path conflict, and the
    shadowed command is absent rather than skipped at lookup — see
    :func:`unshadowed_plugin_commands`, which the CLI's own dispatch reads too.
    """
    nodes: list[CommandNode] = list(JobCommandProvider(app).nodes())
    nodes.extend(PluginCommandProvider(app).nodes())
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
