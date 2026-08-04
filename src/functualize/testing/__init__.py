"""Public test helpers for functualize job testing.

Provides test doubles and builders for unit testing jobs:

    from functualize.testing import TestRunContext, CapturingLog, MockInvoke, AutoPrompt, NoopPerf
    from functualize.testing import FakeShell, FakeStdout
"""

from functualize.testing.builder import TestRunContext
from functualize.testing.doubles import AutoPrompt, CapturingLog, MockInvoke, NoopPerf
from functualize.testing.shell import FakeShell, FakeShellCall
from functualize.testing.stdout import FakeStdout

__all__ = [
    "AutoPrompt",
    "CapturingLog",
    "FakeShell",
    "FakeShellCall",
    "FakeStdout",
    "MockInvoke",
    "NoopPerf",
    "TestRunContext",
]
