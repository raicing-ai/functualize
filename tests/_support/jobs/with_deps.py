"""Job that uses DI capabilities — for execution engine testing."""

from functualize.job import Log


def migrate(log: Log):
    """Run database migrations."""
    log("starting migration")
    log("migration complete")
    print("migrated successfully")
