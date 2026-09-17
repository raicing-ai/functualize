"""Where a project's vault lives — and **which project that is**.

Split out of ``vault.py`` for one concrete reason: ``vault.py`` imports
``cryptography`` at module level, and ``app/config.py`` records that it is
deliberately kept off the cold boot path for every app that never opens a
vault. Boot has to answer *"does this project have a vault?"* before it decides
to import any of that, and the answer is a ``stat``. So the question lives here,
where the only dependency is ``_primitives``.

**The project is found by walking upward, not by hashing the working
directory.** That is the rule discovery already uses
(``_primitives/cache_format.resolve_cache_path``), and the vault used to
disagree with it: it hashed ``Path.cwd()`` unconditionally, so the same project
resolved to a *different vault* depending on which subdirectory you stood in.
Storing a secret from ``src/`` and running the job from the repository root
silently missed it. The store's own docstring claimed the two "agree on what
this project means"; they did not, wherever a ``.functualize/`` directory
existed.

Note what does **not** change: the vault file still lives under XDG data, never
inside ``.functualize/``. A secret store does not belong in the repository. Only
the *identity* moves — the hash is taken over the project root rather than the
working directory — which is why a vault created by running from the project
root keeps working untouched. ``compute_project_id(root)`` and
``compute_project_id(cwd)`` are the same string when cwd *is* the root, and that
is the common case. The invocations whose answer changes are the ones that were
finding the wrong vault.
"""

from __future__ import annotations

from pathlib import Path

from functualize._primitives.fresh_format import find_functualize_dir
from functualize._primitives.locator import _xdg_data_dir, compute_project_id

__all__ = ["VAULT_MODES", "project_root_for", "vault_path_for_project"]

#: The two ways a project can be identified. Pinned as exactly two strings so a
#: caller can match on them, mirroring ``fresh_format.FRESH_MODES``.
VAULT_MODES = ("project", "standalone")


def project_root_for(cwd: str | Path | None = None) -> tuple[Path, str]:
    """The project directory a vault belongs to, and which mode that is.

    Args:
        cwd: Where to start the search. Defaults to the working directory.

    Returns:
        ``(root, mode)``. ``project`` means a ``.functualize/`` directory was
        found walking upward and its parent is the root; ``standalone`` means
        none was, and the resolved starting directory is the root.

    The mode is *returned* rather than left to be re-derived, for the reason
    ``ARCHITECTURE.md`` gives about runtime storage: deriving it means repeating
    the upward walk, and two walks can disagree about which project they are in.
    A vault surface that wants to explain *why* it chose a location needs the
    mode, and asking for it a second time is how the two answers drift apart.
    """
    start = Path(cwd).resolve() if cwd is not None else Path.cwd().resolve()
    functualize_dir = find_functualize_dir(start)
    if functualize_dir is not None:
        return functualize_dir.parent, "project"
    return start, "standalone"


def vault_path_for_project(cwd: str | Path | None = None) -> Path:
    """Return the vault file path for a project directory.

    Keyed by ``compute_project_id`` of the **project root**, so every
    subdirectory of one project reaches one vault. The file need not exist.
    """
    root, _mode = project_root_for(cwd)
    return (
        _xdg_data_dir()
        / "functualize"
        / "vaults"
        / compute_project_id(str(root))
        / "vault.db"
    )
