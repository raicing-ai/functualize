"""GroupOptions — per-group declared CLI flags (S6a).

A ``GroupOptions`` subclass declares flags that are accepted at a *group*
level on the CLI and inherited by every descendant job::

    from typing import Annotated
    from functualize.job import GroupOptions, Option

    class DeployOptions(GroupOptions, group="deploy"):
        env: Annotated[str, Option("-e", help="Target environment")] = "staging"
        dry_run: Annotated[bool, Option("--dry-run")] = False

    # jobs/deploy/web.py
    def run(image: str, opts: DeployOptions = None) -> str:
        ...  # `opts` injected by the engine from the resolved config layer

The bound path is recorded on ``__group_path__`` at class-creation time via
``__init_subclass__(group=...)``. Discovery *also* extracts the path from the
source AST (see ``_discovery``) so the cached spec — the source of truth for
non-booting surfaces (completion/TUI) — never needs to import the class. The
class itself is imported only when a value must be validated/constructed
(execution), mirroring the lazy-class / cached-shape split used by
``workflow_shape_of``.

Placed in ``_types`` (the shared-vocabulary layer that imports nothing
internal) so ``_config``/``_engine``/``_cli`` can all reference the base for
``issubclass`` checks without a cycle. It is *not* re-exported from
``_types.__init__`` — that would pull ``pydantic`` into warm boot; import the
submodule directly (``from functualize._types.group_options import
GroupOptions``) or via the public re-export in ``functualize.job``.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel


class GroupOptions(BaseModel):
    """Base class for per-group option declarations.

    Subclass with a ``group=`` class keyword to bind the declaration to a
    dotted group path. Fields carry the same ``Option`` markers used on job
    parameters and are introspectable via ``model_fields``.
    """

    #: The dotted group path this options class binds to. Empty on the base;
    #: set by ``__init_subclass__`` for every subclass that passes ``group=``.
    #: A ``ClassVar`` so pydantic never treats it as a model field.
    __group_path__: ClassVar[str] = ""

    def __init_subclass__(cls, *, group: str | None = None, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if group is not None:
            cls.__group_path__ = group
