"""Build job — discovered when require_file_prefix = "task_" (the global layer)."""


def build(release: bool = False) -> str:
    """Build the project."""
    mode = "release" if release else "debug"
    print(msg := f"Built ({mode})")
    return msg
