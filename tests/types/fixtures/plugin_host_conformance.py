"""`FunctualizeApp` satisfies `PluginHost`, checked by mypy — AC-3.

Not a test module. `tests/types/test_plugin_host_port.py` runs mypy over this
file and requires **zero** errors. The file's whole content is one assignment
that only type-checks if every one of the port's eleven members matches the
app's, signature for signature.

This is the half `isinstance` cannot do. A `@runtime_checkable` Protocol's
`isinstance` checks *attribute presence* and nothing else: an app whose
`execute` took different arguments, or whose `di` returned an unrelated object,
would still pass it. The port would then be a claim about the app that the app
does not honour -- which is exactly the failure mode `app: Any` has today, with
extra ceremony.
"""
# ruff: noqa: E301, E302, E305, E704, ARG001, D103, TC001

from __future__ import annotations

from functualize._types.host import PluginHost
from functualize.app.core import FunctualizeApp


def takes_the_port(host: PluginHost) -> None: ...


def hand_it_a_real_app() -> None:
    takes_the_port(FunctualizeApp(name="probe"))
