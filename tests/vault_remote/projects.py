"""Two projects with the same jobs — a sender and a receiver — for the
vault-remote suite. Shared by `test_handoff.py` and `test_cli.py`."""

from __future__ import annotations

from pathlib import Path

from functualize.app import FunctualizeApp, JobSources
from functualize.app.vault import VaultIdentity

_SECRET = "correct-horse-battery-staple-9f3a"  # gitleaks:allow

_DEPLOY = '''
from pydantic import BaseModel, Field

from functualize.job import GroupOptions
from functualize.job.decorators import job
from functualize.types import Secret

JOB_GROUP = "deploy"


class DeployOptions(GroupOptions, group="deploy"):
    token: Secret[str] = Field(default="")


class AppConfig(BaseModel):
    api_key: Secret[str] = Field(default="")
    region: str = Field(default="eu-west-1")


@job
def app(config: AppConfig, options: DeployOptions) -> None:
    """Deploy the app."""
'''

_INFRA = '''
from pydantic import Field

from functualize.job import GroupOptions
from functualize.job.decorators import job
from functualize.types import Secret

JOB_GROUP = "deploy.infra"


class InfraOptions(GroupOptions, group="deploy.infra"):
    region_key: Secret[str] = Field(default="")


@job
def plan(options: InfraOptions) -> None:
    """Plan the infra."""
'''

_TOOLS = '''
from pydantic import BaseModel, Field

from functualize.job.decorators import job
from functualize.types import Secret


class MyConfig(BaseModel):
    api_key: Secret[str] = Field(default="")


@job
def myjob(config: MyConfig) -> None:
    """A job in no group."""
'''

_TOKEN = VaultIdentity("group", "deploy", "token")
_APP_KEY = VaultIdentity("job", "deploy.app", "api_key")
_REGION = VaultIdentity("group", "deploy.infra", "region_key")
_MY_KEY = VaultIdentity("job", "myjob", "api_key")


def _project(root: Path, *modules: tuple[str, str]) -> Path:
    jobs = root / "jobs"
    jobs.mkdir(parents=True)
    for name, source in modules:
        (jobs / f"{name}.py").write_text(source)
    (root / ".functualize").mkdir()
    return root


_ALL_JOBS = (("deploy", _DEPLOY), ("infra", _INFRA), ("tools", _TOOLS))


def _app(root: Path) -> FunctualizeApp:
    return FunctualizeApp(
        "handoff", job_sources=JobSources(directories=[str(root / "jobs")], lazy=False)
    )
