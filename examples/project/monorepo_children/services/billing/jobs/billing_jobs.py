"""Billing service jobs — discovered by the parent and namespaced as "billing.*".

These appear in the CLI as:
  platform-ops billing.invoice
  platform-ops billing.reconcile
"""

from pydantic import BaseModel, Field

from functualize.job.context import RunContext
from functualize.job.decorators import job


class BillingConfig(BaseModel):
    """Configuration for billing jobs."""

    currency: str = Field(default="USD", description="Currency code")
    tax_rate: float = Field(default=0.08, description="Tax rate as decimal")


@job(
    extra_description="Generate an invoice for a customer",
    category="billing",
    tags=["write"],
)
def invoice(config: BillingConfig, rc: RunContext) -> str:
    """Generate a customer invoice."""
    rc.log(f"Generating invoice in {config.currency}...")
    rc.log(f"Tax rate: {config.tax_rate * 100:.1f}%")
    rc.log("Invoice #INV-2024-001 created")
    return "invoice_created"


@job(
    extra_description="Reconcile billing records against payments",
    category="billing",
    tags=["safe", "read-only"],
)
def reconcile(config: BillingConfig, rc: RunContext) -> str:
    """Reconcile billing records with payment processor."""
    rc.log("Reconciling billing records...")
    rc.log(f"Currency: {config.currency}")
    rc.log("3 payments matched, 0 discrepancies")
    return "reconciliation_complete"
