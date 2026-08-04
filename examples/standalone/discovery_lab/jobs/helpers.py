"""Helper visible only in baseline convention mode.

A plain public function in a plain public file: discovered when no filters
are configured, gone as soon as any file-level require_* filter is enabled.
"""


def helper_info() -> str:
    """Show which helpers are available."""
    print(msg := "helpers: none configured")
    return msg
