"""Allow the final spec cleanup only after its parent passed PR validation.

The feature-bearing PR run cannot conclude success: the artifact gates
(``spec-artifacts-cleared``, ``research-artifacts-cleared``) must fail while
their trees are still tracked. All other CI jobs must be green. Missing API data
or an incomplete run means the cleanup must run full CI.
"""

from __future__ import annotations

import json
import os
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# The gates that refuse a tree which is cleared before merge rather than
# validated. A feature-bearing run is expected to fail them — that failure is
# the evidence that the commit carried the artifacts — so neither is required to
# be green here. At least one must have run and failed.
ARTIFACT_GATES = frozenset(
    {
        "spec-artifacts-cleared",
        "research-artifacts-cleared",
    }
)

VALIDATION_JOBS = frozenset(
    {
        "spec-only-change",
        "lint",
        "lint-imports",
        "typecheck",
        "test-fast",
        "test-full (3.11)",
        "test-full (3.12)",
        "test-full (3.13)",
        "examples",
        "plugin-mcp",
        "clean-clone-examples",
        "doc-verify",
        "docs-build",
    }
)


def validation_errors(jobs: list[dict[str, object]]) -> list[str]:
    """Return missing or non-green validation jobs from the latest run attempt."""
    by_name = {str(job.get("name")): job for job in jobs}
    missing_or_red = [
        name
        for name in sorted(VALIDATION_JOBS)
        if by_name.get(name, {}).get("conclusion") != "success"
    ]
    missing_or_red.extend(
        str(job.get("name"))
        for job in jobs
        if str(job.get("name")) not in ARTIFACT_GATES
        and job.get("conclusion") != "success"
        and str(job.get("name")) not in missing_or_red
    )
    return missing_or_red


def _get_json(url: str, token: str) -> dict[str, object]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "functualize-spec-cleanup-gate",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        url,
        headers=headers,
    )
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def main() -> int:
    parent_sha, branch = sys.argv[1:3]
    token = os.environ.get("GH_TOKEN", "")
    repository = os.environ["GITHUB_REPOSITORY"]
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    root = f"{api_url}/repos/{repository}/actions"
    query = urlencode(
        {"head_sha": parent_sha, "event": "pull_request", "per_page": 100}
    )

    try:
        runs = _get_json(f"{root}/workflows/ci.yml/runs?{query}", token)
        completed = [
            run
            for run in runs.get("workflow_runs", [])
            if run.get("head_sha") == parent_sha
            and run.get("head_branch") == branch
            and run.get("status") == "completed"
        ]
        if not completed:
            print("No completed CI run found for the cleanup commit's parent.")
            return 1

        run = max(completed, key=lambda item: item.get("created_at", ""))
        if run.get("conclusion") != "failure":
            print(
                "The prior CI run did not finish with the expected artifact-gate failure."
            )
            return 1
        jobs_data = _get_json(
            f"{root}/runs/{run['id']}/jobs?filter=latest&per_page=100", token
        )
        jobs = jobs_data.get("jobs", [])
        if jobs_data.get("total_count", len(jobs)) > len(jobs):
            print("The prior CI job list is incomplete; running full CI.")
            return 1
        failing_gates = sorted(
            str(job.get("name"))
            for job in jobs
            if str(job.get("name")) in ARTIFACT_GATES
            and job.get("conclusion") == "failure"
        )
        if not failing_gates:
            print("The prior feature-bearing run has no failing artifact gate.")
            return 1
        failures = validation_errors(jobs)
        if failures:
            print(
                "The prior CI run has missing or non-green jobs: " + ", ".join(failures)
            )
            return 1
        print(
            f"Prior PR validation is green on {parent_sha} (run {run['id']}; "
            f"{', '.join(failing_gates)} red as expected)."
        )
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Could not verify prior CI ({type(error).__name__}); running full CI.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
