"""Cleanup job — the only file whose stem ends in "_task".

Passes require_file_postfix = "_task"; fails the "job_" prefix, import,
marker, and decorator filters.
"""


def cleanup(days: int = 30) -> str:
    """Remove artifacts older than the given number of days."""
    print(msg := f"Cleaned artifacts older than {days} days")
    return msg
