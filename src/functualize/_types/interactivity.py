"""Interactivity vocabulary — the Surface protocol and prompt types.

How a job talks to a human. Two channels, and only two:

- **engine → UI**: ``Surface.handle_event(StructuredEvent)`` — 1:N fan-out to
  every registered surface.
- **UI → engine**: ``PromptCollector.collect(PromptRequest) -> PromptResponse``
  — 1:1 dispatch to the one *active* collector.

A job never touches either. Its entire conversational API is the RunContext
(``rc.log`` / ``rc.emit`` / ``rc.prompt_*``); the engine turns those into
events and prompt requests. That ignorance is deliberate: it is what lets one
unmodified job render in a TUI panel, in plain stdout, in a job-owned
full-screen app, as MCP gate checkpoints, or under a test double.

**Why two protocols and not one.** The channels are independent capabilities:
flow-viz renders and cannot ask questions; the stdin fallback asks and renders
nothing; a full-screen app does both. Fusing them into one protocol would
force every implementation to stub the half it does not do — and worse, break
things: an output-only renderer without a ``collect`` stub would fail the
``isinstance`` check and silently receive no events at all, while one *with* a
stub would win prompt resolution and swallow prompts it cannot answer. So a
surface declares only what it actually does, and an object may satisfy both.

Lives in ``_types`` because it is shared vocabulary — the engine, the gate
machinery, the CLI, and plugins all speak it, and none of them should have to
import each other to do so. Only stdlib imports at runtime, per the layer
contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from functualize._events.bus import StructuredEvent

__all__ = [
    "InputNotAvailable",
    "LiveConstruct",
    "PromptChoice",
    "PromptCollector",
    "PromptIntent",
    "PromptRequest",
    "PromptResponse",
    "PromptSeverity",
    "Surface",
    "needs_terminal",
]


class InputNotAvailable(Exception):  # noqa: N818 — established public name
    """Raised when input is required but nothing can collect it.

    Occurs when a job prompts with ``required=True`` and no default, but no
    PromptCollector is available — e.g. a headless context where the
    TTY-gated stdin fallback stays inert.
    """


class PromptIntent(Enum):
    """Semantic intent of a prompt, guiding surface presentation."""

    CONFIRM_DESTRUCTIVE = "confirm_destructive"
    CONFIRM_NEUTRAL = "confirm_neutral"
    CONFIRM_PROCEED = "confirm_proceed"
    SELECT = "select"
    MULTI_SELECT = "multi_select"
    TEXT_INPUT = "text_input"
    SECRET_INPUT = "secret_input"
    ACKNOWLEDGE = "acknowledge"


class PromptSeverity(Enum):
    """Visual severity level for prompt presentation.

    Largely **derivable from** :class:`PromptIntent` — a destructive
    confirmation is a danger prompt, everything else is informational — so
    prefer letting :func:`severity_for_intent` supply it rather than passing
    it by hand. It remains settable for the cases where a caller genuinely
    wants to override the styling (a warning on a non-destructive action).
    """

    INFO = "info"
    WARNING = "warning"
    DANGER = "danger"
    SUCCESS = "success"


def severity_for_intent(intent: PromptIntent) -> PromptSeverity:
    """Return the default visual severity for a prompt intent.

    Single source of truth for the intent→severity mapping, so surfaces and
    ``rc.prompt_*`` helpers cannot drift on how a destructive confirmation is
    styled.
    """
    if intent is PromptIntent.CONFIRM_DESTRUCTIVE:
        return PromptSeverity.DANGER
    return PromptSeverity.INFO


@dataclass(frozen=True)
class PromptChoice:
    """A single selectable choice within a prompt.

    Attributes:
        value: The programmatic value returned when this choice is selected.
        label: Display label (falls back to value if None).
        description: Optional longer description for the choice.
        disabled: If True, shown but not selectable.
        group: Optional group name for visual grouping of choices.
    """

    value: str
    label: str | None = None
    description: str | None = None
    disabled: bool = False
    group: str | None = None


@dataclass(frozen=True)
class PromptRequest:
    """A structured request for user input during job execution.

    The wire format between a job and whatever is rendering it. Carries
    intent, severity, choices, context, and validation rules so that one
    request can be presented as a terminal question, a Textual modal, or an
    MCP gate checkpoint without the job knowing which.

    Attributes:
        question: The prompt question text displayed to the user.
        intent: Semantic intent guiding surface presentation.
        choices: Available choices for SELECT/MULTI_SELECT intents.
        default: Default value used on timeout or when no input provided.
        severity: Visual severity level for styling.
        context_message: Optional context message displayed alongside the prompt.
        context_data: Optional structured data displayed in a context panel.
        placeholder: Placeholder text for text input fields.
        help_text: Additional help text displayed below the prompt.
        timeout: Timeout in seconds; None means wait indefinitely.
        required: If True and no Surface is available with no default, raises
            InputNotAvailable.
        validator: Regex pattern string or object with .validate_python() method.
        validation_message: Custom message shown on validation failure.
        source_job: Name of the job that initiated this prompt (auto-filled by
            rc.prompt).
        source_step: Name of the workflow step that initiated this prompt.
    """

    question: str
    intent: PromptIntent = PromptIntent.TEXT_INPUT
    choices: list[PromptChoice] | None = None
    default: Any = None
    severity: PromptSeverity = PromptSeverity.INFO
    context_message: str | None = None
    context_data: dict[str, Any] | None = None
    placeholder: str | None = None
    help_text: str | None = None
    timeout: float | None = None
    required: bool = True
    validator: str | Any | None = None
    validation_message: str | None = None
    source_job: str | None = None
    source_step: str | None = None


@dataclass(frozen=True)
class PromptResponse:
    """Response from a user prompt interaction.

    Attributes:
        value: The response value (user input, default, or None if cancelled).
        source: How the response was obtained. Constrained to:
                "user", "default", "timeout", "cancelled".
    """

    value: Any
    source: str = "user"  # "user" | "default" | "timeout" | "cancelled"

    @property
    def was_cancelled(self) -> bool:
        """True if the user cancelled the prompt."""
        return self.source == "cancelled"

    @property
    def was_timeout(self) -> bool:
        """True if the prompt timed out without user response."""
        return self.source == "timeout"

    @property
    def is_user_input(self) -> bool:
        """True if the response came from direct user input."""
        return self.source == "user"


@runtime_checkable
class Surface(Protocol):
    """Something that renders a job's events.

    Implementations include the TUI's output panel, flow-viz's plain-stdout
    tree, a job-owned Textual app, a log-file writer, and test recorders.
    Registered on the app; the engine fans every non-framework event out to
    all of them.

    An implementation that can also answer questions additionally satisfies
    :class:`PromptCollector`.

    **Threading contract — the part that bites.** ``handle_event`` is called
    from whatever thread the job runs on, which is a *worker* thread whenever
    a host owns the terminal (see ``_cli/tui/job_execution.py``). An
    implementation that touches a UI must marshal onto its own loop
    (Textual: ``post_message`` / ``call_from_thread``). Writing to a widget
    directly from ``handle_event`` freezes the app with no exception and no
    stack trace — the failure is silent, so it must be designed out here
    rather than debugged later.
    """

    def handle_event(self, event: StructuredEvent) -> None:
        """Render or record one structured event. Called on worker threads."""
        ...


@runtime_checkable
class PromptCollector(Protocol):
    """Something that can ask the user a question and return the answer.

    Exactly one collector is active at a time — whichever owns the terminal
    (or the modal) right now. Implementations include the stdin fallback, a
    TUI's input bar, and a job-owned app's modal.
    """

    def collect(self, request: PromptRequest) -> PromptResponse:
        """Ask the user, blocking until answered, timed out, or cancelled."""
        ...


@runtime_checkable
class LiveConstruct(Protocol):
    """A renderable hosted in a surface's live zone (the ``Live`` capability).

    The construct owns only its *state* and how to render it; the surface owns
    the cursor/mount and repaints. The contract is a single Rich renderable via
    ``__rich__`` (a Table / Tree / Progress / Group / Text). The "raw" fallback
    needs no second renderer — it is Rich's own degradation: a non-terminal
    ``Console`` prints plain text, and ``rich.live.Live`` off-TTY prints the
    final state only.

    Interactivity is a separate, optional capability. A construct that *also*
    implements the PanelHost action contract (``get_available_actions(focused)``
    plus Textual ``action_*`` methods, made focusable) can be mounted via
    ``Live.panel(...)`` where an event loop exists (PANEL / EXCLUSIVE); it
    degrades to passive render in STDOUT and to event-emission in MCP.

    Return type is ``Any`` because ``_types`` is stdlib-only (no Rich import);
    the value is any Rich renderable.
    """

    def __rich__(self) -> Any:
        """Return a Rich renderable for the construct's current state."""
        ...


def needs_terminal(surface: object) -> bool:
    """Whether ``surface`` draws on the terminal (default True).

    Terminal-drawing surfaces must be suspended while a job owns the screen;
    headless ones (log files, MCP progress, telemetry, test recorders) keep
    receiving events throughout, so a run stays observable even then. A
    surface opts out by setting ``needs_terminal = False`` on itself.

    This is a function rather than a ``Surface`` member because a
    ``runtime_checkable`` Protocol with a data member makes ``isinstance()``
    require that attribute to be *present* — any surface that implemented
    both methods but never set the flag would fail the check and silently
    receive no events. Defaulting here keeps conformance about behavior.
    """
    return bool(getattr(surface, "needs_terminal", True))
