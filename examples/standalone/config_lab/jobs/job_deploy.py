"""Deploy job — discovered when require_file_prefix = "job_" (the project layer)."""


def deploy(target: str = "staging") -> str:
    """Deploy the application."""
    print(msg := f"Deployed to {target}")
    return msg
