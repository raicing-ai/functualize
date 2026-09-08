"""`job_tools` — whether a project publishes per-job tools at all.

An MCP client loads the full tool list at connect time and carries it for the
session. The fixed cost is ~11 tools; the variable cost is **one tool per
discovered job**, each with a full JSON Schema. There was no way to express
"generic door only": `include_tags`, `exclude_tags`, `exclude_jobs` and
`visibility` are all opt-*in* filters over a set that always started as
everything.

A per-job tool duplicates `run_job(name, config)` completely — both funnel
through the same `_execute_job`. Turning them off used to cost information
because every door was equally lossy about `JobResult.metadata`. It no longer
does, which is what makes this switch safe and why the two landed together.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from functualize_mcp._config import MCPConfig
from functualize_mcp._translator import JobToolTranslator

from functualize._app.state import AppState
from functualize.app.core import FunctualizeApp
from functualize.job import job


@pytest.fixture(autouse=True)
def _reset() -> Generator[None]:
    AppState.reset()
    yield
    AppState.reset()


@pytest.fixture
def app() -> FunctualizeApp:
    instance = FunctualizeApp(name="testapp")

    @job(tags=["mcp"])
    def deploy() -> str:
        """Ship it."""
        return "shipped"

    @job(tags=["internal-only"])
    def scrub() -> str:
        """Scrub it."""
        return "scrubbed"

    @job
    def plain() -> str:
        """Plain."""
        return "ok"

    instance.register_dynamic_job("deploy", deploy)
    instance.register_dynamic_job("scrub", scrub)
    instance.register_dynamic_job("plain", plain)
    return instance


def _names(app: FunctualizeApp, config: MCPConfig) -> set[str]:
    return {t.name for t in JobToolTranslator().translate_all(app.get_jobs(), config)}


class TestTheCandidateSet:
    """AC-26, AC-27."""

    def test_all_is_the_default_and_unchanged(self, app: FunctualizeApp) -> None:
        assert MCPConfig().job_tools == "all"
        assert _names(app, MCPConfig()) == {"deploy", "scrub", "plain"}

    def test_none_publishes_no_per_job_tools(self, app: FunctualizeApp) -> None:
        assert _names(app, MCPConfig(job_tools="none")) == set()

    def test_tagged_publishes_only_the_opted_in(self, app: FunctualizeApp) -> None:
        assert _names(app, MCPConfig(job_tools="tagged")) == {"deploy"}

    def test_the_tag_is_configurable(self, app: FunctualizeApp) -> None:
        config = MCPConfig(job_tools="tagged", job_tools_tag="internal-only")
        assert _names(app, config) == {"scrub"}


class TestItComposesWithTheExistingFilters:
    """`job_tools` decides the candidate set; the filters narrow it. They
    answer different questions, so collapsing them would make
    `include_tags=[]` ambiguous between *no filter* and *nothing*."""

    def test_exclude_jobs_still_narrows_the_tagged_set(
        self, app: FunctualizeApp
    ) -> None:
        config = MCPConfig(job_tools="tagged", exclude_jobs=["deploy"])
        assert _names(app, config) == set()

    def test_none_wins_over_an_include_filter(self, app: FunctualizeApp) -> None:
        """ "none" is not "everything the filters allow" — it is nothing."""
        config = MCPConfig(job_tools="none", include_tags=["mcp"])
        assert _names(app, config) == set()

    def test_all_with_include_tags_is_unchanged_behaviour(
        self, app: FunctualizeApp
    ) -> None:
        config = MCPConfig(include_tags=["mcp"])
        assert _names(app, config) == {"deploy"}


class TestTheGenericDoorSurvives:
    def test_turning_per_job_tools_off_does_not_touch_the_core_tools(
        self, app: FunctualizeApp
    ) -> None:
        """The whole safety argument: with per-job tools off, `run_job` still
        reaches every job — and now returns metadata, so nothing is lost."""
        from functualize_mcp._tools import MCPToolRegistry

        registry = MCPToolRegistry(app, config=MCPConfig(job_tools="none"))
        assert registry._find_job("deploy") is not None
        assert registry._find_job("plain") is not None
