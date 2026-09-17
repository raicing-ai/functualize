"""Error classes for the AI Domain SDK."""


class AINotAvailableError(Exception):
    """Raised when no AI provider is configured or available."""

    pass


class BudgetExceededError(Exception):
    """Raised when cumulative AI spend reaches or exceeds the budget limit."""

    pass


class ToolNotPermittedError(Exception):
    """Raised when a tool call is not permitted by the current ToolScope."""

    pass
