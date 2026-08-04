"""Shared error types for the functualize API surface.

These errors are raised across multiple layers and are part of the
public contract for job authors and platform developers.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class RecursionLimitError(Exception):
    """Raised when invoke_depth reaches max_invoke_depth.

    Attributes:
        depth: The current invoke depth when the limit was hit.
        max_depth: The configured maximum invoke depth.
        job_name: The name of the job that would have exceeded the limit.
    """

    def __init__(self, depth: int, max_depth: int, job_name: str) -> None:
        self.depth = depth
        self.max_depth = max_depth
        self.job_name = job_name
        super().__init__(
            f"Recursion limit reached: invoke_depth={depth} at "
            f"max_invoke_depth={max_depth} while invoking '{job_name}'"
        )


class JobDependencyError(Exception):
    """Raised at boot when a job's ``Deps`` cannot be validated (§A.4):
    an unknown/unregistered dependency reference, or a dependency cycle.

    Attributes:
        message: Human-readable description of the problem.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class WorkflowDeclarationError(Exception):
    """Raised at boot when a ``@workflow`` graph cannot be validated (§A.7):
    a `Step` referencing an unknown job, or a cycle among nested workflows.

    Structural problems provable from the declaration alone (duplicate node
    names, edges to nowhere) raise at decoration time instead — this is for
    what only the live registry can settle.

    Attributes:
        message: Human-readable description of the problem.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class GroupOptionsConflictError(Exception):
    """Raised at discovery when two modules bind ``GroupOptions`` to one group.

    A group's flags must have exactly one declaration: the flags are inherited
    by every descendant job, so two competing declarations would make
    ``func deploy --env prod …`` mean different things depending on scan
    order. Mirrors the job name-conflict check.

    Attributes:
        group: The contested dotted group path.
        existing: Path of the module that already declared it.
        conflicting: Path of the module that tried to redeclare it.
    """

    def __init__(self, group: str, existing: str, conflicting: str) -> None:
        self.group = group
        self.existing = existing
        self.conflicting = conflicting
        super().__init__(
            f"Group {group!r} has more than one GroupOptions declaration: "
            f"{existing!r} and {conflicting!r}. A group's flags must be "
            "declared exactly once — merge them into a single class."
        )


class OrphanedPluginMetadataError(Exception):
    """Raised at boot when a job carries ``__functualize_ext_*`` metadata whose
    plugin is not loaded, and ``plugins.strict`` is enabled (§A.6).

    Attributes:
        orphans: List of ``(job_name, namespace)`` pairs with no owning plugin.
    """

    def __init__(self, orphans: list[tuple[str, str]]) -> None:
        self.orphans = orphans
        detail = ", ".join(f"{job}:{ns}" for job, ns in orphans)
        super().__init__(
            "Orphaned plugin metadata (no matching loaded plugin) under "
            f"plugins.strict: {detail}"
        )


class GateResolutionError(Exception):
    """Raised when all gate strategies fail to resolve input.

    Attributes:
        gate_name: The name of the gate that failed resolution.
        strategies_attempted: The number of strategies that were tried.
        last_error: Description of the last error encountered.
    """

    def __init__(
        self, gate_name: str, strategies_attempted: int, last_error: str
    ) -> None:
        self.gate_name = gate_name
        self.strategies_attempted = strategies_attempted
        self.last_error = last_error
        super().__init__(
            f"Gate '{gate_name}': all {strategies_attempted} strategies failed. "
            f"Last error: {last_error}"
        )


class JobNotFoundError(Exception):
    """Raised when a callable is not found in the job registry.

    Attributes:
        fn_or_name: The function reference or name string that was not found.
    """

    def __init__(self, fn_or_name: str | Callable[..., Any]) -> None:
        self.fn_or_name = fn_or_name
        if callable(fn_or_name) and not isinstance(fn_or_name, str):
            name = getattr(fn_or_name, "__qualname__", None) or getattr(
                fn_or_name, "__name__", repr(fn_or_name)
            )
            msg = f"Callable '{name}' is not registered in the job registry"
        else:
            msg = f"Job '{fn_or_name}' is not registered"
        super().__init__(msg)


class JobMaterializationError(Exception):
    """Raised when a lazily-registered job's module cannot be imported.

    Raised at first use (invocation or CLI dispatch) of a job whose
    registration deferred the module import. Chains the original
    ImportError/AttributeError as __cause__.

    Attributes:
        job_name: The registered job name being materialized.
        module_path: Dotted module path that failed to import/resolve.
        source_file: Source file recorded in the descriptor, if any.
    """

    def __init__(
        self, job_name: str, module_path: str, source_file: str | None = None
    ) -> None:
        self.job_name = job_name
        self.module_path = module_path
        self.source_file = source_file
        location = f" ({source_file})" if source_file else ""
        super().__init__(
            f"Job '{job_name}': failed to import module '{module_path}'{location}"
        )


class AmbiguousJobError(Exception):
    """Raised when a bare job name matches multiple registered jobs.

    Attributes:
        name: The ambiguous bare name.
        candidates: List of qualified names that match.
    """

    def __init__(self, name: str, candidates: list[str]) -> None:
        self.name = name
        self.candidates = candidates
        super().__init__(
            f"Ambiguous job name '{name}'. "
            f"Candidates: {candidates}. Use the qualified form."
        )


class TerminalUnavailable(Exception):  # noqa: N818 — reads as a state, not an error
    """Raised when a job needs an interactive terminal but none is available.

    A job that declares ``tty: TTY`` (a hard requirement) owns the terminal for
    the duration of ``tty.run(app)``. In contexts that cannot grant terminal
    ownership — MCP, CI, piped/redirected I/O, background execution — the job is
    refused with this error (pre-flight where the router can see the
    ``requires_tty`` marker; at ``tty.run`` time otherwise), naming the fix.

    Attributes:
        job_name: The job that required a terminal, if known.
    """

    def __init__(
        self, message: str | None = None, *, job_name: str | None = None
    ) -> None:
        self.job_name = job_name
        super().__init__(
            message
            or "This job needs an interactive terminal (it declares `tty: TTY`)."
        )
