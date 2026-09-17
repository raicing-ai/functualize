"""The example is the end-to-end test for `PluginHost` — AC-22.

`contributor/reference/public-api-example-coverage.md`: a symbol in a public
package's `__all__` must have at least one caller under `examples/`. `examples/`
is collected by pytest, so the example *is* the integration test for the API,
entered through the user's own door — and once every public symbol has one,
"no callers" means *dead* again rather than *unknown*.

`PluginHost` is the first symbol added under that rule. These tests load the
plugin into a real `FunctualizeApp` and let boot call it, rather than handing it
a mock: a mock answers every attribute, so it would pass whether the port
existed or not — which is exactly how two dead reaches survived in shipped
plugins for as long as they did.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from annotated_plugin import BudgetPlugin, JobBudget

from functualize.app import FunctualizeApp, JobSources, PluginSources
from functualize.plugin import PluginHost
from functualize.types import RunRequest, RunStatus

JOB_SOURCE = '''
from functualize.job import RunContext

from annotated_plugin import JobBudget


def spend(rc: RunContext, amount: int = 3) -> str:
    """Charge the budget the plugin registered, and say what happened."""
    budget = rc[JobBudget]
    return "charged" if budget.charge(amount) else "refused"
'''


@pytest.fixture
def app(tmp_path: Path) -> FunctualizeApp:
    """A real app with the example plugin loaded, booted once.

    `explicit_plugins` is how a plugin reaches an app without installing an
    entry point — the same loader path, minus the packaging.
    """
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "work.py").write_text(JOB_SOURCE)
    return FunctualizeApp(
        name="budgeted",
        job_sources=JobSources(directories=[str(jobs)]),
        plugin_sources=PluginSources(explicit_plugins=[BudgetPlugin(ceiling=10)]),
    )


class TestTheAppSatisfiesThePort:
    def test_the_thing_the_plugin_is_handed_is_a_plugin_host(
        self, app: FunctualizeApp
    ) -> None:
        """The premise, and a user can check it: the port is
        `@runtime_checkable`.

        Member presence only — `isinstance` on a Protocol never compares
        signatures. The static half is `mypy --strict annotated_plugin.py`,
        which the repository runs in `tests/types/test_plugin_host_port.py`.
        """
        assert isinstance(app, PluginHost)


class TestWhatTheJobSees:
    """`app.di.provide` reaches a job. The only way to check it from outside.

    `app.di` is **write-only** — `provide`, `provide_factory`, `provide_named`
    and no reader. So a plugin cannot confirm its own registration, and this
    test goes the way a user does: run a job that asks for the capability.
    """

    def test_the_job_receives_the_budget_the_plugin_registered(
        self, app: FunctualizeApp
    ) -> None:
        result = app.execute(RunRequest(job_name="spend", surface="app.execute"))

        assert result.status is RunStatus.SUCCESS
        assert result.return_value == "charged"

    def test_a_charge_over_the_ceiling_is_refused_not_clamped(
        self, app: FunctualizeApp
    ) -> None:
        """The ceiling is 10, so 11 cannot be spent — and is not partly spent."""
        result = app.execute(
            RunRequest(job_name="spend", surface="app.execute", kwargs={"amount": 11})
        )

        assert result.return_value == "refused"
        assert (
            app.execute(
                RunRequest(
                    job_name="spend", surface="app.execute", kwargs={"amount": 10}
                )
            ).return_value
            == "charged"
        ), "the refused charge left the budget intact"


class TestRegistrationHappened:
    def test_the_plugin_command_is_registered(self, app: FunctualizeApp) -> None:
        """`app.extensions.register_plugin_command` — the command is registered.

        Registered *on this app*, which is what the port's member does. It is
        not an invocable `func budget` here: this example is a plugin module
        plus tests, with no project config and no entry point, so there is no
        CLI for a command to appear on. Verified — `uv run func budget` in this
        directory answers "Unknown command". Getting one requires installing
        the plugin into a real project, which is what the four shipped plugins
        that register commands do.

        Read back through `get_plugin_commands()`, which is on the *facade* and
        deliberately **not** on the port: it returns `_app.models.PluginCommand`,
        a type `_types` cannot name, and no plugin source calls it. Core and
        tests do, as here.
        """
        names = [command.name for command in app.extensions.get_plugin_commands()]
        assert "budget" in names


class TestTheReadyHookRan:
    def test_it_saw_the_jobs_that_boot_discovered(self, app: FunctualizeApp) -> None:
        """`app.hooks.on_ready` fired, and `app.get_jobs()` answered inside it.

        One job is in the fixture's directory, and the count is read *in the
        handler* — which is the reason the handler exists. Reading it during
        `__call__` would run before discovery.
        """
        state = app.extensions.extension_state["budget"]
        assert state["jobs_at_boot"] == 1

    def test_it_read_the_project_root_from_the_port(self, app: FunctualizeApp) -> None:
        """`app.fresh_root` — one of the two single-client members the port
        carries anyway, because without them a shipped plugin could not adopt
        it at all."""
        state = app.extensions.extension_state["budget"]
        assert state["project_root"] == str(app.fresh_root)


class TestTheBudgetItselfWorks:
    """The example has to *do* something, or it demonstrates nothing."""

    def test_it_allows_spending_under_the_ceiling(self) -> None:
        budget = JobBudget(ceiling=10)
        assert budget.charge(4) is True
        assert budget.charge(6) is True
        assert budget.spent == 10

    def test_it_refuses_the_charge_that_would_breach(self) -> None:
        budget = JobBudget(ceiling=10)
        assert budget.charge(9) is True
        assert budget.charge(2) is False
        assert budget.spent == 9, "a refused charge must not be half-applied"
