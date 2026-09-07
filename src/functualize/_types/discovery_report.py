"""What discovery could not read, retained instead of only logged.

A job module that fails to load contributes no jobs and writes one line to
stderr. By the time an operator asks "why is my job missing?", that line has
scrolled past, and ``builtin info`` shows a short list with no explanation --
so the only way to see the cause is to reproduce the boot with the logger
turned up.

Two separate stages can reject a module, and until this existed both were
invisible:

* **parse** -- the AST/pre-filter stage, which reads a file without executing
  it. A plain typo lands here, at the nine sites that catch ``SyntaxError``
  and return a default. This is the *more likely* failure and the one STATUS
  follow-up #12 is about.
* **import** -- the provider actually executing the module. A missing
  dependency lands here.

Both append to one list under one key, so a consumer never has to know which
stage rejected what. The catch sites keep catching: a broken module must stay
non-fatal to the scan, it just stops being invisible.

Why a ContextVar rather than a parameter threaded through: the parse-stage
sites live on ``ModulePreFilter`` implementations in ``_primitives``, which
have no reference to the provider running them and cannot acquire one --
``_primitives`` may not import ``_discovery``. A provider opens a collection
scope around its scan; anything that fails inside it records. Nothing records
when no scope is open, which is what keeps a stray parse elsewhere in the
process out of a discovery report.

This module is in ``_types`` because both ``_primitives`` and ``_discovery``
must reach it, and ``_types`` is the only layer beneath both. It imports
nothing internal, per the constitution.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "DiscoveryFailure",
    "collecting_discovery_failures",
    "record_discovery_failure",
]


@dataclass(frozen=True)
class DiscoveryFailure:
    """One module discovery could not read, and why.

    Attributes:
        module: The module's name -- its file stem. Not the dotted import
            path: at the parse stage no import has been attempted, so no
            dotted path exists yet, and reporting one for the import stage
            only would make the two halves of the list inconsistent.
        path: Absolute path to the file, which is the identifier an operator
            can act on.
        error_type: The exception class name. ``"SyntaxError"`` is the marker
            that separates a parse failure from an import one.
        message: ``str(exc)``, unmodified.
    """

    module: str
    path: str
    error_type: str
    message: str

    def as_dict(self) -> dict[str, str]:
        """The payload shape published by ``builtin info``."""
        return {
            "module": self.module,
            "path": self.path,
            "error_type": self.error_type,
            "message": self.message,
        }


_ACTIVE: ContextVar[list[DiscoveryFailure] | None] = ContextVar(
    "functualize_discovery_failures", default=None
)


@contextmanager
def collecting_discovery_failures() -> Generator[list[DiscoveryFailure]]:
    """Collect every failure recorded inside this scope.

    A provider wraps one scan in this and keeps the result. Scopes nest: an
    inner one collects into its own list and the outer one does not see it,
    which is deliberate -- a provider delegating to another provider should
    report what *it* scanned.
    """
    collected: list[DiscoveryFailure] = []
    token = _ACTIVE.set(collected)
    try:
        yield collected
    finally:
        _ACTIVE.reset(token)


def record_discovery_failure(source_file: Path | str, exc: BaseException) -> None:
    """Record that ``source_file`` could not be read, if anyone is collecting.

    A no-op outside a collection scope, so a catch site can call this
    unconditionally and stay free of any knowledge about who is scanning.

    Never raises. A diagnostic that can break the scan it is diagnosing is
    worse than no diagnostic, and these call sites are all inside ``except``
    blocks whose whole purpose is to keep a broken module non-fatal.
    """
    collected = _ACTIVE.get()
    if collected is None:
        return
    try:
        text = str(source_file)
        stem = text.rsplit("/", 1)[-1]
        failure = DiscoveryFailure(
            module=stem[:-3] if stem.endswith(".py") else stem,
            path=text,
            error_type=type(exc).__name__,
            message=str(exc),
        )
        # A composite pre-filter is several filters, each of which parses the
        # file itself -- so one broken module is genuinely rejected three or
        # four times in a single scan. Reporting it once per filter would tell
        # an operator there are four problems where there is one, and the
        # count is an artifact of the filter configuration rather than of the
        # tree. Identical records collapse; a *different* failure for the same
        # path (an OSError after a SyntaxError, say) is a separate fact and
        # stays.
        if failure not in collected:
            collected.append(failure)
    except Exception:  # pragma: no cover - defensive; see the docstring
        return
