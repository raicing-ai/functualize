"""functualize-webhook: Webhook delivery adapter plugin.

Demonstrates implementing the AdapterPlugin protocol to deliver
job execution results via HTTP webhooks.
"""

from functualize_webhook._adapter import WebhookAdapter
from functualize_webhook._config import WebhookConfig

__all__ = ["WebhookAdapter", "WebhookConfig"]
