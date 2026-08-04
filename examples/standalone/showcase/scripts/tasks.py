"""Single-file jobs with zero imports — run with: func scripts/tasks.py deploy

Plain Python functions become jobs: no decorators, no framework imports.
Direct runs surface log/print output (not return values), so these print.
"""


def deploy(target: str = "staging") -> str:
    """Deploy the application to the specified environment."""
    print(f"Deployed to {target}")
    return f"Deployed to {target}"


def status() -> str:
    """Check the deployment status."""
    print("All systems operational")
    return "All systems operational"
