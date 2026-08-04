"""Job that always fails — for error-handling tests."""


def explode():
    """This job always raises an error."""
    raise RuntimeError("intentional failure for testing")


def bad_return():
    """This job returns a non-zero exit code."""
    return 42
