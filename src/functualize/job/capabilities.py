"""Public capability protocols and classes for job authors.

Re-exports the capability types from their source locations so that
job authors can import everything from `functualize.job`:

    from functualize.job import Log, Invoke, Prompt, Perf, State, JobContext, JobConfigView
    from functualize.job import JobResult, InvokeResult

These types are used for:
- Type annotations in job function signatures (DI injection)
- Runtime interaction within job bodies (logging, invoking, prompting, etc.)
- Configuration access via JobConfigView
- Result types for invocation return values
"""

from functualize._config.job_config import JobConfigView
from functualize._engine.capabilities.live import Live
from functualize._engine.capabilities.prompt import Prompt
from functualize._engine.capabilities.tty import TTY
from functualize._types.descriptors import JobResult
from functualize._types.errors import TerminalUnavailable
from functualize._types.interactivity import (
    PromptChoice,
    PromptRequest,
    PromptResponse,
)
from functualize.job._invoke import Invoke, InvokeResult
from functualize.job._job_context import JobContext
from functualize.job._log import Log
from functualize.job._perf import Perf, Phase
from functualize.job._shell import (
    FailingResponder,
    Responder,
    Shell,
    ShellError,
    ShellResult,
)
from functualize.job._state import State
from functualize.job._stdout import Stdout

__all__ = [
    # Core capabilities for DI injection
    "Invoke",
    "JobContext",
    "JobConfigView",
    "Live",
    "Log",
    "Perf",
    "Prompt",
    "Shell",
    "State",
    "Stdout",
    "TTY",
    # Supporting types (useful for job authors)
    "InvokeResult",
    "JobResult",
    "Phase",
    "FailingResponder",
    "Responder",
    "ShellError",
    "ShellResult",
    "PromptChoice",
    "PromptRequest",
    "PromptResponse",
    "TerminalUnavailable",
]
