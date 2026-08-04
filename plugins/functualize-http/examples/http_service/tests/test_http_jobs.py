"""Tests for HTTP service jobs — prove they work without the HTTP adapter."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

# Add the src directory so we can import the jobs directly
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from http_service.jobs.deploy import DeployConfig, Environment
from http_service.jobs.deploy import run as deploy_run
from http_service.jobs.healthcheck import HealthcheckConfig
from http_service.jobs.healthcheck import run as healthcheck_run


def _make_rc():
    """Create a minimal mock RunContext for testing."""
    rc = MagicMock()
    rc.log = MagicMock()
    return rc


class TestHealthcheck:
    """Tests for the healthcheck job."""

    def test_returns_healthy_status(self):
        rc = _make_rc()
        config = HealthcheckConfig(service_url="https://api.example.com")
        result = healthcheck_run(config, rc)

        assert result["status"] == "healthy"
        assert result["url"] == "https://api.example.com"
        assert result["status_code"] == 200

    def test_respects_timeout_config(self):
        rc = _make_rc()
        config = HealthcheckConfig(service_url="https://slow.example.com", timeout=10)
        result = healthcheck_run(config, rc)

        assert result["timeout_configured"] == 10

    def test_custom_expected_status(self):
        rc = _make_rc()
        config = HealthcheckConfig(
            service_url="https://api.example.com", expected_status=204
        )
        result = healthcheck_run(config, rc)

        assert result["status_code"] == 204


class TestDeploy:
    """Tests for the deploy job."""

    def test_deploy_to_staging(self):
        rc = _make_rc()
        config = DeployConfig(version="v1.0.0", environment=Environment.staging)
        result = deploy_run(config, rc)

        assert result["version"] == "v1.0.0"
        assert result["environment"] == "staging"
        assert result["status"] == "deployed"
        assert result["changes_applied"] is True

    def test_deploy_dry_run(self):
        rc = _make_rc()
        config = DeployConfig(version="v2.0.0", dry_run=True)
        result = deploy_run(config, rc)

        assert result["status"] == "dry_run"
        assert result["changes_applied"] is False

    def test_deploy_to_production(self):
        rc = _make_rc()
        config = DeployConfig(version="v1.5.0", environment=Environment.production)
        result = deploy_run(config, rc)

        assert result["environment"] == "production"
        assert result["changes_applied"] is True

    def test_deploy_logs_steps(self):
        rc = _make_rc()
        config = DeployConfig(version="v3.0.0")
        deploy_run(config, rc)

        log_calls = [str(call) for call in rc.log.call_args_list]
        assert any("Deploying" in call for call in log_calls)
        assert any("container image" in call for call in log_calls)
