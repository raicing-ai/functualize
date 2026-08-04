"""Job-level (function-level) discovery filters.

The counterpart to ``pre_filter.py``. A ``ModulePreFilter`` answers *should we
import this file*; a ``JobFilter`` answers *should this function become a job*.
The two levels are deliberately separate:

- File-level settings (``require_file_*``, ``exclude_patterns``) decide which
  modules are read at all, and can short-circuit before any import happens.
- Job-level settings (``require_job_*``) decide which of an imported module's
  public functions are registered. They cannot be evaluated at file level —
  a file with one decorated function may hold ten undecorated helpers.

Filters here operate on already-extracted ``JobDescriptor``s, so they apply
identically on the cold-import path and on the cache-read path.

Only imports from ``_types/`` and Python stdlib.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence


@runtime_checkable
class JobCandidate(Protocol):
    """The minimum a job-level filter needs to judge a candidate.

    ``JobDescriptor`` satisfies this structurally. So does
    :class:`RawJobCandidate`, which lets the CLI's pre-boot routing read apply
    the same filters to raw cache JSON without paying to rebuild descriptors.
    """

    @property
    def func_name(self) -> str:
        """Bare function name (the portion after the last dot)."""
        ...

    @property
    def attribute_name(self) -> str:
        """The function's Python ``__name__``.

        Distinct from :attr:`func_name`, which is the canonical leaf of the
        address. Prefix/postfix filters judge *this* one, because they encode
        an authoring convention about how functions are spelled.
        """
        ...

    @property
    def decorators(self) -> tuple[str, ...]:
        """Decorator root names applied to the function."""
        ...


@dataclass(frozen=True)
class RawJobCandidate:
    """A JobCandidate built from raw cache-entry fields.

    Args:
        name: Job name, possibly dotted (``group.func``).
        decorators: Decorator root names recorded at extraction time.
    """

    name: str
    decorators: tuple[str, ...] = ()
    #: The function's Python ``__name__``, when the cache recorded it. Empty
    #: falls back to the canonical leaf.
    python_name: str = ""

    @property
    def func_name(self) -> str:
        """Bare function name (the portion after the last dot)."""
        return self.name.rsplit(".", 1)[-1]

    @property
    def attribute_name(self) -> str:
        """The function's own name, which prefix/postfix filters judge."""
        return self.python_name or self.func_name


@runtime_checkable
class JobFilter(Protocol):
    """Decides whether an extracted job candidate is registered."""

    def should_register(self, candidate: JobCandidate) -> bool:
        """Return True if this candidate should become a discoverable job."""
        ...


class JobPrefixFilter:
    """Require the job's function name to start with a prefix.

    Matches against ``func_name`` (the portion after the last dot), so grouped
    jobs are judged by their function name, not the ``group.name`` path.
    """

    def __init__(self, prefix: str) -> None:
        self._prefix = prefix

    def should_register(self, candidate: JobCandidate) -> bool:
        """Return True if the function name starts with the configured prefix.

        Matched against the *Python* name, not the canonical address. This
        filter expresses an authoring convention (`def run_deploy`), so a
        configured `require_job_prefix = "run_"` must keep meaning what its
        author wrote; comparing against `run-deploy` would silently match
        nothing and hide every job.
        """
        return candidate.attribute_name.startswith(self._prefix)


class JobPostfixFilter:
    """Require the job's function name to end with a postfix."""

    def __init__(self, postfix: str) -> None:
        self._postfix = postfix

    def should_register(self, candidate: JobCandidate) -> bool:
        """Return True if the function name ends with the configured postfix.

        Matched against the *Python* name for the same reason as the prefix
        filter: `require_job_postfix = "_job"` is a statement about how
        functions are written, and the canonical `deploy-job` would never
        match it.
        """
        return candidate.attribute_name.endswith(self._postfix)


class JobDecoratorFilter:
    """Require the job's function to carry one of the given decorators.

    Reads the decorator root names recorded on the descriptor at extraction
    time (see ``pre_filter.extract_function_decorators``). A descriptor with no
    recorded decorators is rejected — that is the point of the filter.

    Args:
        decorator_names: Decorator root names; any one match admits the job.
    """

    def __init__(self, decorator_names: Sequence[str]) -> None:
        self._names = set(decorator_names)

    def should_register(self, candidate: JobCandidate) -> bool:
        """Return True if the function carries any configured decorator."""
        return any(name in self._names for name in candidate.decorators)


class AllJobFilters:
    """AND-combine job filters; a descriptor must satisfy every one.

    An empty filter list admits everything, matching the pre-filter stack's
    ``AllOf`` semantics.
    """

    def __init__(self, *filters: JobFilter) -> None:
        self._filters = filters

    def should_register(self, candidate: JobCandidate) -> bool:
        """Return True if every configured filter admits the candidate."""
        return all(f.should_register(candidate) for f in self._filters)
