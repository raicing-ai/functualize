"""A plugin annotated against `PluginHost` — the whole point, in one file.

Plugin authors used to write `def __call__(self, app: Any)`, and 40 of the 44
`app` parameters across the twelve shipped plugins did exactly that. Under
`Any`, every line below type-checks whether or not the member exists: two
shipped plugins reached `app._di_registry` and one probed
`hasattr(app, "resolve")`, and **all three reaches were permanently dead** —
against members `FunctualizeApp` has never had — with no test and no type
error to say so.

`PluginHost` is the eleven members a plugin is meant to use. Annotate with it
and a typo is a type error at the line you wrote it on, rather than an
`AttributeError` inside whichever `except Exception` happens to be in scope.

Run `mypy --strict annotated_plugin.py` from this directory to see that; the
misspellings it would catch are listed at the bottom of this module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from functualize.plugin import PluginHost


class JobBudget:
    """What this plugin contributes to the app's DI registry.

    A job asks for it by type — `budget = rc[JobBudget]` — and gets this
    instance, because the plugin handed it to `app.di.provide` at boot.

    Note what a plugin *cannot* do: read it back. `app.di` is write-only
    (`provide`, `provide_factory`, `provide_named`), which is why two shipped
    plugins reached into `app._di_registry` instead — and why `di.resolve` was
    considered for this port and **dropped**, both reaches being dead. The
    consumer is a job, through `RunContext`, and the example's test drives one.
    """

    def __init__(self, ceiling: int) -> None:
        self.ceiling = ceiling
        self.spent = 0

    def charge(self, amount: int) -> bool:
        """Spend, unless it would breach the ceiling."""
        if self.spent + amount > self.ceiling:
            return False
        self.spent += amount
        return True


class BudgetPlugin:
    """Registers a job budget, a CLI command, and a boot-time report.

    Five of the port's eleven members and four of its view members, which is
    what an ordinary plugin actually touches:

    - `app.di.provide` — hand a capability to jobs
    - `app.extensions.register_plugin_command` — add `func budget`
    - `app.extensions.extension_state` — the sanctioned place to keep state
      that belongs to this plugin rather than to the kernel
    - `app.hooks.on_ready` — run once, after boot, when jobs are discoverable
    - `app.get_jobs()` and `app.fresh_root` — read the project, at the moment
      there is one to read
    """

    name = "budget"
    version = "1.0.0"
    description = "A per-run spending ceiling for jobs that ask for one."

    def __init__(self, ceiling: int = 100) -> None:
        self._budget = JobBudget(ceiling)

    def __call__(self, app: PluginHost) -> None:
        """Registration. Called once, during boot, with the host.

        Registration only — nothing is *read* from the app here. A plugin that
        reads the project during `__call__` reads it before every plugin has
        loaded; that is what `on_ready` is for, below.
        """
        app.di.provide(JobBudget, self._budget)
        app.extensions.register_plugin_command(
            "budget",
            self._report_command,
            help_text="Show the remaining job budget.",
        )
        app.hooks.on_ready(self._on_app_ready)

    def _on_app_ready(self, app: PluginHost) -> None:
        """Boot is complete: jobs are discoverable and storage is decided.

        The signature is checked. `app.hooks.on_ready` is typed
        `Callable[[OnReadyHandler], OnReadyHandler]`, so a handler taking the
        wrong number of arguments — or returning a value, when the return is
        discarded — is an error at the registration line above.
        """
        state = app.extensions.extension_state.setdefault("budget", {})
        state["jobs_at_boot"] = len(app.get_jobs())
        state["project_root"] = str(app.fresh_root)

    def _report_command(self) -> None:
        """The body of `func budget`."""
        print(f"budget: {self._budget.spent}/{self._budget.ceiling} spent")


# What the port refuses, and `Any` did not
# ---------------------------------------
# Each line below is a `mypy --strict` error against `app: PluginHost`, and
# silently fine against `app: Any`. The first two are the reaches that
# motivated the port; the rest are members deliberately kept off it.
#
#     app._di_registry.resolve(JobBudget)   # the private reach, twice shipped
#     app.resolve(JobBudget)                # the `hasattr` probe, as a call
#     app.hook_registry.invoke_start(...)   # firing events is not a plugin's
#     app.execution_engine.materialize_job  # one client; not worth the seat
#     app.dii.provide(JobBudget, budget)    # a typo in a facade name
#     app.di.provdie(JobBudget, budget)     # a typo one level down, in a view
#
# `tests/spec/test_the_plugin_host_cannot_be_bypassed.py` asserts every one of
# them, so this comment is a summary of a check rather than a claim.
