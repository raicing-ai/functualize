"""Tests for the monorepo_children example.

Verifies that the parent app correctly discovers and composes
child project jobs under their namespace prefixes.
"""

import sys
from pathlib import Path

# Add the src directory to sys.path for direct testing
src_dir = str(Path(__file__).parent.parent / "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from platform_ops.main import app  # noqa: E402


class TestChildProjectDiscovery:
    """Verify child jobs are discovered and namespaced correctly."""

    def test_parent_jobs_discovered(self) -> None:
        """Parent ops jobs are available without namespace prefix."""
        job_names = [j.name for j in app.get_jobs()]
        assert "health-check" in job_names
        assert "report" in job_names

    def test_auth_child_jobs_namespaced(self) -> None:
        """Auth child jobs appear with 'auth.' prefix."""
        job_names = [j.name for j in app.get_jobs()]
        assert "auth.login" in job_names
        assert "auth.rotate-keys" in job_names

    def test_billing_child_jobs_namespaced(self) -> None:
        """Billing child jobs appear with 'billing.' prefix."""
        job_names = [j.name for j in app.get_jobs()]
        assert "billing.invoice" in job_names
        assert "billing.reconcile" in job_names

    def test_child_projects_recorded(self) -> None:
        """Child projects are recorded on app.child_projects."""
        children = app.child_projects
        child_names = {c.name for c in children}
        assert "auth" in child_names
        assert "billing" in child_names

    def test_total_job_count(self) -> None:
        """Parent (2) + auth (2) + billing (2) = 6 jobs total."""
        jobs = app.get_jobs()
        assert len(list(jobs)) == 6
