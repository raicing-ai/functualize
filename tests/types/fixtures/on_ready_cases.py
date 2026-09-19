"""The eight `on_ready` cases from `contracts.md` §5, as a mypy fixture.

Not a test module and not imported by one: `tests/types/test_on_ready_signature.py`
runs mypy over this file and checks that the errors land on exactly the lines
marked `# want-error`. Nothing here is executed.

Four cases must type-check and four must not, and the marker is the assertion —
so a case that stops being an error fails the test, and so does a case that
starts being one.

`tool.mypy` checks `packages = ["functualize"]`, so the deliberate errors below
are invisible to the repository's own mypy run. They are only ever seen by the
test that wants them.
"""
# ruff: noqa: E301, E302, E305, E704, ARG001, D103, D101, D102, TC001

from __future__ import annotations

from typing import Any

from functualize._types.host import PluginHost
from functualize.app.core import FunctualizeApp

app = FunctualizeApp(name="probe")


# 1 · a handler typed against the port
def typed(host: PluginHost) -> None: ...


app.hooks.on_ready(typed)


# 2 · a bound method — the form all five shipped plugins use
class Plugin:
    def _on_app_ready(self, host: PluginHost) -> None: ...


app.hooks.on_ready(Plugin()._on_app_ready)


# 3 · a handler still annotated `app: Any` — every shipped handler today.
#     Must keep passing, or AC-5 would force T11's sweep into this wave.
def anyish(host: Any) -> None: ...


app.hooks.on_ready(anyish)


# 4 · the bare decorator form, which must leave the name bound to the function
@app.hooks.on_ready
def decorated(host: PluginHost) -> None: ...


# 5 · not callable at all
app.hooks.on_ready("not a function")  # want-error

# 6 · wrong arity
app.hooks.on_ready(lambda a, b, c: None)  # want-error


# 7 · wrong parameter type. The case the port exists for: `Callable[[Any], None]`
#     would accept this, because `Any` is compatible in both directions.
def wrong_param(host: int) -> None: ...


app.hooks.on_ready(wrong_param)  # want-error


# 8 · returns a value. `APP_READY`'s return is discarded at both firing sites
#     (`_app/boot.py:464` and `:862`), so a handler that returns something is
#     saying something untrue.
def returns_str(host: PluginHost) -> str:
    return "x"


app.hooks.on_ready(returns_str)  # want-error
