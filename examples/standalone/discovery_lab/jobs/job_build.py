"""Build job — passes the prefix filter ("job_") but nothing else.

No functualize import, no marker variable, no decorators: under the import,
marker, or decorator filters this file contributes no jobs.
"""


def build(optimize: bool = False) -> str:
    """Build the project."""
    mode = "optimized" if optimize else "debug"
    print(msg := f"Build complete ({mode})")
    return msg
