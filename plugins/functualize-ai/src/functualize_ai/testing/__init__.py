"""AI testing doubles — MockAI.

Provides a deterministic, pattern-matching AI testing double for unit and
integration testing of jobs that use AI capabilities, without requiring
network calls or API keys.
"""

from functualize_ai.testing._mock_ai import MockAI, MockAICall

__all__ = [
    "MockAI",
    "MockAICall",
]
