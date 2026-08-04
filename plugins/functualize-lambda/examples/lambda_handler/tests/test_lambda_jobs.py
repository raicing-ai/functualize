"""Tests for Lambda service jobs — prove they work without AWS."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from lambda_service.jobs import (
    NotificationConfig,
    ProcessOrderConfig,
    process_order,
    send_notification,
)


def _make_rc():
    """Create a minimal mock RunContext for testing."""
    rc = MagicMock()
    rc.log = MagicMock()
    return rc


class TestProcessOrder:
    """Tests for the process_order job."""

    def test_processes_order_successfully(self):
        rc = _make_rc()
        config = ProcessOrderConfig(order_id="ORD-001", amount=49.99)
        result = process_order(config, rc)

        assert result["order_id"] == "ORD-001"
        assert result["status"] == "processed"
        assert result["amount"] == 49.99
        assert result["confirmation_code"] == "CONF--001"

    def test_priority_processing(self):
        rc = _make_rc()
        config = ProcessOrderConfig(order_id="ORD-VIP", amount=199.99, priority=True)
        result = process_order(config, rc)

        assert result["priority"] is True
        log_calls = [str(call) for call in rc.log.call_args_list]
        assert any("Priority" in call for call in log_calls)

    def test_zero_amount_order(self):
        rc = _make_rc()
        config = ProcessOrderConfig(order_id="ORD-FREE", amount=0.0)
        result = process_order(config, rc)

        assert result["amount"] == 0.0
        assert result["status"] == "processed"


class TestSendNotification:
    """Tests for the send_notification job."""

    def test_sends_email_notification(self):
        rc = _make_rc()
        config = NotificationConfig(
            recipient="user@example.com", message="Your order is ready!"
        )
        result = send_notification(config, rc)

        assert result["recipient"] == "user@example.com"
        assert result["channel"] == "email"
        assert result["status"] == "sent"

    def test_sends_sms_notification(self):
        rc = _make_rc()
        config = NotificationConfig(
            recipient="+1234567890", message="Delivery arriving", channel="sms"
        )
        result = send_notification(config, rc)

        assert result["channel"] == "sms"

    def test_message_preview_truncated(self):
        rc = _make_rc()
        long_message = "A" * 100
        config = NotificationConfig(recipient="user@test.com", message=long_message)
        result = send_notification(config, rc)

        assert len(result["message_preview"]) == 50
