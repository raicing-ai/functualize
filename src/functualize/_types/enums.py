"""Enum definitions for the functualize shared vocabulary.

Contains RunStatus, RunType, and JobPhase enums used across all
internal layers. Zero imports from any _-prefixed internal package.
"""

from __future__ import annotations

from enum import Enum


class RunStatus(Enum):
    """Status of a run context execution."""

    SUCCESS = "Success"
    FAILURE = "Failure"
    BLOCKED = "Blocked"
    SKIPPED = "Skipped"
    RUNNING = "Running"
    CANCELLED = "Cancelled"
    TIMEOUT = "Timeout"
    UNKNOWN = "Unknown"
    #: The job declined to run because a declared precondition for running it
    #: was not met — a `Precondition` guard failed, or a declared
    #: `Fingerprint(sources=...)` resolved to no files at all.
    #:
    #: Distinct from FAILURE (the body ran and raised), from BLOCKED (a
    #: declared pause point, resumable), and above all from SKIPPED. A skip
    #: says "nothing to do" and exits 0; a refusal says "I was asked to verify
    #: something that is not there" and exits 3. Collapsing them is how a
    #: stage certifies success having verified nothing.
    REFUSED = "Refused"

    @property
    def resumable(self) -> bool:
        """True when the run stopped at a declared pause point, not an error.

        A workflow that reaches a `Gate` with no input is BLOCKED, not FAILURE:
        it did everything it was asked to, and re-invoking it with the input
        deposited continues from where it stopped. Callers that treat "not
        SUCCESS" as "broken" — CI gates, `Deps` satisfaction, TUI colouring —
        need to tell the two apart.
        """
        return self is RunStatus.BLOCKED

    @property
    def ran(self) -> bool:
        """True when the job's body actually executed.

        SKIPPED is not a failure — a guard or an up-to-date fingerprint
        answered "no work to do", which is the point of declaring them. But it
        is not SUCCESS either: a caller that treats them alike cannot tell a
        build that ran from one that was already current, and `func why`
        exists precisely to answer that.
        """
        return self is RunStatus.SUCCESS


class RunType(Enum):
    """Type of run context invocation."""

    JOB = "job"
    COMMAND = "command"
    RUN = "run"


class ConfigFileRole(Enum):
    """The role a discovered config file plays under the active environment.

    Config files are named ``config.<slot>.<ext>``. The ``base`` slot is
    always loaded; a slot matching the active environment is merged on top
    of it; any other slot belongs to a different environment and is not
    merged at all.
    """

    BASE = "base"
    """Always merged, regardless of the active environment."""

    OVERLAY = "overlay"
    """Slot matches the active environment — merged on top of BASE."""

    INERT = "inert"
    """Slot names a different environment — discovered, but never merged."""


class EnvironmentSource(Enum):
    """Where the active environment name came from.

    Delivery layers use this to distinguish "explicitly selected" from
    "fell back to the default", which are very different things to show a
    user staring at a config file that isn't taking effect.
    """

    FUNCTUALIZE_ENV = "FUNCTUALIZE_ENV"
    ENVIRONMENT = "ENVIRONMENT"
    ENV = "ENV"
    DEFAULT = "default"


class JobPhase(Enum):
    """Named phases within a job execution lifecycle."""

    DISCOVERY = "discovery"
    CONFIGURATION = "configuration"
    VALIDATION = "validation"
    EXECUTION = "execution"
    TEARDOWN = "teardown"
