"""Job with typed parameters for CLI arg testing."""


def deploy(env: str, dry: bool = False, replicas: int = 1):
    """Deploy to a target environment.

    Args:
        env: Target environment (staging, production).
        dry: Dry-run mode — print actions without executing.
        replicas: Number of replicas to deploy.
    """
    mode = "DRY RUN" if dry else "LIVE"
    print(f"[{mode}] deploying to {env} with {replicas} replicas")
