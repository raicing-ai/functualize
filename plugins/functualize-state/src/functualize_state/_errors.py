"""Error classes for the State Domain SDK."""


class StateNotAvailableError(Exception):
    """Raised when a state backend is not available."""

    pass


class KeyNotFoundError(Exception):
    """Raised when a requested key is not found in the state backend."""

    pass
