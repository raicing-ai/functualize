"""What a `PluginHost`-typed parameter cannot do. The rule, as code.

Not a test module. `tests/spec/test_the_plugin_host_cannot_be_bypassed.py`
runs mypy over this file and requires the errors to land on exactly the lines
marked `# want-error`.

**This is the feature's premise, stated so it can fail.** `plugin-host-protocol`
exists because two shipped plugins reached past the facades into the app's
private DI registry, and `app: Any` reported nothing either time. The first
block below is the calls a plugin is supposed to make; everything after it is a
reach the port is supposed to refuse, including both original reaches.

A negative test that cannot fail is prose, so the marker comparison is strict
in both directions: correcting a misspelling to a real member removes its error
and **fails this file**, which is what stops it from silently becoming a list of
things that happen to be typos.
"""
# ruff: noqa: E301, E302, E305, E704, ARG001, D103, TC001, SLF001, B018

from __future__ import annotations

from functualize.plugin import PluginHost


def what_a_plugin_may_do(app: PluginHost) -> None:
    """Every one of these is a real call a shipped plugin makes."""
    app.di.provide(int, 42)
    app.di.provide_named("thing", 42)
    app.extensions.extension_state.setdefault("mine", {})
    app.configuration.resolve_model("mine", int)
    app.gates.register_gate_preset("mine", ["a"])
    app.hooks.on_ready(lambda host: None)
    app.get_jobs()
    app.get_job("build")
    app.fresh_root / "somewhere"


def a_misspelled_facade(app: PluginHost) -> None:
    """A typo in a facade name. Under `app: Any` this type-checks and fails at
    runtime, inside whatever `except Exception` happens to be in scope."""
    app.dii.provide(int, 42)  # want-error


def a_misspelled_method(app: PluginHost) -> None:
    """A typo in a method name, one level down — so the views are load-bearing
    too, not just the eleven members on the port itself."""
    app.di.provdie(int, 42)  # want-error


def the_original_reach(app: PluginHost) -> None:
    """`app._di_registry.resolve(...)` — the reach this feature exists to close.

    It stood in `functualize-ai-pydantic/_plugin.py` behind
    `except (ImportError, Exception)`, and in `functualize-mcp/_task_tools.py`
    as a `hasattr(app, "resolve")` probe. Both were permanently dead and both
    were invisible: `app: Any` accepts every one of these four lines.
    """
    app._di_registry.resolve(int)  # want-error
    app.resolve(int)  # want-error


def the_firing_half(app: PluginHost) -> None:
    """`hook_registry` is off the port because four of its seven methods *fire*
    lifecycle events. Registering is `hooks.on_ready`; firing is not a plugin's
    to do, and this is what makes that a rule rather than a paragraph."""
    app.hook_registry.register_global("app_ready", lambda a: None)  # want-error


def members_argued_off_the_port(app: PluginHost) -> None:
    """Each of these was excluded with a measured client count in
    `contracts.md` §1, and each exclusion is only real if it is checked."""
    app.execution_engine  # want-error
    app.substrate_override  # want-error
    app.run()  # want-error
    app.workflows  # want-error
