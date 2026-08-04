"""The runtime command tree the shell drives — ``CommandNode`` + providers.

The namespace **trie** (``_types/naming.py``) owns the *shape* of the command
namespace: which paths exist and how a typed token resolves to one. This module
owns the *runtime behavior* at a resolved path — what a node is called, what it
takes, whether running it needs the terminal, and how to run it.

Keeping the two apart is deliberate. The trie is built from cached rows and
imports no job module; a ``CommandNode`` may have to materialize one to answer
:meth:`CommandNode.params`. Fusing them would drag imports into the ~3ms
pre-boot routing read.

The shell composes **providers** into one tree, which is what finally removes
the "builtins are a separate hidden namespace" special-casing: a job subtree and
the reserved ``builtin`` subtree arrive as the same node type, from
``JobCommandProvider`` and ``ClickCommandProvider`` respectively.

This module lives in ``_types`` and therefore imports nothing internal beyond
its own package (import-linter contract "Types import nothing internal").
Public re-export lives in ``functualize.plugin``, alongside ``Surface`` and
``PromptCollector`` — the shell-facing protocols this one sits beside.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from functualize._types.descriptors import FieldDescriptor

__all__ = ["CommandNode", "CommandProvider"]


@runtime_checkable
class CommandNode(Protocol):
    """One runnable-or-navigable position in the shell's command tree.

    A node may be runnable (``execute``), navigable (``children``), or **both** —
    the duality case the trie already models (a ``deploy`` job that also has
    ``deploy web`` beneath it). Nothing here distinguishes a job from a builtin;
    that is the point.

    Attributes:
        name: The node's own segment as typed, not its full path.
        help_text: One-line description for listings and completion.
        needs_terminal: True when running this node takes over the controlling
            terminal, so a TUI front-end must suspend itself around it rather
            than capture its output. Read by the orchestrator handoff, and by
            nothing else.

    **Decision — ``needs_terminal`` is a plain bool, not a predicate over args.**
    It exists today in two incompatible shapes: a **method** on
    ``_cli/builtins.BuiltinCommand`` (``needs_terminal(args) -> bool``, computed
    as ``any(arg in self.terminal_subcommands for arg in args)``) and a **bool
    field** on ``_cli/tui/panel_live_zone``'s surface. The method form exists
    only because ``BuiltinCommand`` models a whole command *family*: ``config``
    carries ``terminal_subcommands=("edit",)``, so the answer depends on which
    subcommand was typed.

    A ``CommandNode`` is not a family — the tree splits ``config`` into distinct
    ``config edit`` and ``config show`` nodes, and at that granularity the answer
    is **static**. So the bool wins, and the args-dependence is resolved *once,
    at node construction*: a provider wrapping ``BuiltinCommand`` evaluates
    ``needs_terminal([segment])`` for each child it emits (this is
    ``ClickCommandProvider``'s job). No information is lost and the consumer —
    the orchestrator handoff — stops re-deriving it per invocation.

    Distinct from a descriptor's ``requires_tty``, which is a *job author's*
    declaration about the job function; ``needs_terminal`` is a property of the
    command node the shell is about to run.
    """

    # Read-only on purpose: every implementation exposes these as a computed
    # ``@property`` (``JobNode`` derives them from its trie node,
    # ``ClickCommandNode`` from the click command). Declaring them as plain
    # mutable attributes would require a settable variable, which no
    # implementation offers — and nothing anywhere assigns to them.
    @property
    def name(self) -> str:
        """The node's own segment as typed, not its full path."""
        ...

    @property
    def help_text(self) -> str:
        """One-line description for listings and completion."""
        ...

    @property
    def needs_terminal(self) -> bool:
        """True when running this node takes over the controlling terminal."""
        ...

    def children(self) -> list[CommandNode]:
        """Direct children, for drill-down. Empty for a leaf.

        Backed by ``GroupTrie.children()`` for job nodes; by the click group's
        registered subcommands for builtin nodes.
        """
        ...

    def params(self) -> list[FieldDescriptor]:
        """The node's CLI-facing parameters.

        Deliberately the **existing** ``FieldDescriptor`` — the same type
        ``build_click_params`` consumes — rather than a parallel param model
        invented for the shell. There is one description of a job's parameters
        and every surface reads it.

        May be expensive: for a lazily-cached job this can force materialization
        (one module import). Callers that must stay import-free — completion of
        a *command name*, drill-down listing — must not call it.
        """
        ...

    def execute(self, args: Sequence[str]) -> int:
        """Run this node with ``args``; return a process-style exit code."""
        ...


@runtime_checkable
class CommandProvider(Protocol):
    """A source of top-level :class:`CommandNode` s the shell composes into one tree."""

    def nodes(self) -> list[CommandNode]:
        """This provider's top-level nodes, in display order."""
        ...
