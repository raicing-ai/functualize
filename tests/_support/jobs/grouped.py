"""Job with JOB_GROUP for group routing testing."""

JOB_GROUP = "infra"


def provision():
    """Provision cloud resources."""
    print("resources provisioned")


def destroy():
    """Destroy cloud resources."""
    print("resources destroyed")
