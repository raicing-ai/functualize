"""Warehouse jobs."""

from functualize.job import job


@job
def restock(sku: str) -> str:
    """Restock a SKU."""
    return f"restocked {sku}"


# BUG (deliberate): no @job decorator, so strict discovery skips it.
def audit(sku: str) -> str:
    """Audit a SKU."""
    return f"audited {sku}"
