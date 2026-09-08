"""Where a job or a plugin command sits in the command namespace, as one string.

Two derivations, both pure string logic, kept here for one reason: **three
layers need to compare them and they must never disagree.** The CLI's group
dispatch, the shell's command tree, the click adapter and the boot-time
collision warning all ask "does a job already occupy this path?", and when that
question was answered by an inline f-string in each place, the answers diverged
— a plugin command silently displaced a job on one surface, lost to it on
another, and aborted the run on a third.

String-in, string-out so ``_primitives`` needs no descriptor type and every
layer above can reach it. The object-taking wrappers live in
``functualize.app.commands``, where the descriptors do.
"""

from __future__ import annotations

__all__ = ["job_path", "plugin_path"]


def job_path(group: str | None, name: str) -> str:
    """The dotted path a job occupies in the namespace trie.

    Normally just ``name``, which already carries its group as a prefix. The
    degenerate case is a descriptor whose ``group`` is *not* a prefix of its
    ``name``: the trie nests the whole name under the group there, so a lookup
    keyed on ``name`` alone would miss it and the job would fail to shadow a
    plugin command sitting at the same path.
    """
    if group and not name.startswith(f"{group}."):
        return f"{group}.{name}"
    return name


def plugin_path(namespace: str | None, name: str) -> str:
    """The dotted path a plugin command occupies.

    ``namespace="mcp"`` + ``name="serve"`` -> ``"mcp.serve"``; a command with
    no namespace is its own path.
    """
    return f"{namespace}.{name}" if namespace else name
