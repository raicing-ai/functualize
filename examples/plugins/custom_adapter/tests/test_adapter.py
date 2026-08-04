"""Tests for the custom webhook adapter plugin."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from functualize_webhook import WebhookAdapter, WebhookConfig


class TestWebhookConfig:
    """Tests for the webhook configuration model."""

    def test_default_config(self):
        config = WebhookConfig(webhook_url="https://example.com/hook")
        assert config.webhook_url == "https://example.com/hook"
        assert config.timeout == 10
        assert config.retry_count == 3
        assert config.include_logs is False

    def test_custom_config(self):
        config = WebhookConfig(
            webhook_url="https://api.test.com/webhook",
            secret="my-secret",
            timeout=30,
            retry_count=5,
            include_logs=True,
        )
        assert config.secret == "my-secret"
        assert config.timeout == 30
        assert config.include_logs is True


class TestWebhookAdapter:
    """Tests for the webhook adapter behavior."""

    def test_adapter_type(self):
        adapter = WebhookAdapter(webhook_url="https://test.com")
        assert adapter.adapter_type == "webhook"

    def test_adapter_not_initialized_raises(self):
        adapter = WebhookAdapter(webhook_url="https://test.com")
        with pytest.raises(RuntimeError, match="not initialized"):
            adapter.run("some-job")

    def test_adapter_initialization(self):
        adapter = WebhookAdapter(webhook_url="https://test.com")

        class MockApp:
            pass

        adapter(MockApp())
        assert adapter._app is not None

    def test_adapter_stores_config(self):
        adapter = WebhookAdapter(
            webhook_url="https://hooks.example.com",
            secret="abc123",
            timeout=20,
        )
        assert adapter._config.webhook_url == "https://hooks.example.com"
        assert adapter._config.secret == "abc123"
        assert adapter._config.timeout == 20

    def test_delivery_tracking(self):
        adapter = WebhookAdapter(webhook_url="https://test.com")
        assert adapter.deliveries == []

        # Simulate a delivery
        payload = {"job_name": "test", "status": "success"}
        adapter._deliver(payload)

        assert len(adapter.deliveries) == 1
        assert adapter.deliveries[0]["status"] == "delivered"
        assert adapter.deliveries[0]["payload"] == payload

    def test_multiple_deliveries_tracked(self):
        adapter = WebhookAdapter(webhook_url="https://test.com")

        for i in range(3):
            adapter._deliver({"job": f"job-{i}"})

        assert len(adapter.deliveries) == 3


class TestAdapterWithApp:
    """Integration tests — adapter with a real FunctualizeApp."""

    def test_execute_and_deliver(self):
        """Full flow: execute job → deliver via webhook (mocked app)."""
        from unittest.mock import MagicMock

        # Mock the app and its execute method
        mock_app = MagicMock()
        mock_result = MagicMock()
        mock_result.status.value = "success"
        mock_result.return_value = "pong from api.example.com"
        mock_result.duration_ms = 42
        mock_app.execute.return_value = mock_result

        adapter = WebhookAdapter(webhook_url="https://hooks.test.com/results")
        adapter(mock_app)

        # Execute and deliver
        result = adapter.run("ping", kwargs={"target": "api.example.com"})

        assert result["webhook_status"] == "delivered"
        assert result["webhook_url"] == "https://hooks.test.com/results"
        assert len(adapter.deliveries) == 1

        delivery = adapter.deliveries[0]
        assert delivery["payload"]["job_name"] == "ping"
        assert delivery["payload"]["return_value"] == "pong from api.example.com"
        mock_app.execute.assert_called_once_with("ping", target="api.example.com")
