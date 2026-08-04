"""Error classes for the Tasks Domain SDK."""


class TaskNotFoundError(Exception):
    """Raised when a task operation targets a task_id that does not exist."""

    pass
