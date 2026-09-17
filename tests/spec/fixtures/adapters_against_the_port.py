"""Every concrete adapter, handed to something that wants an `AdapterPlugin`.

Not a test module. `tests/spec/test_adapters_conform_to_the_port.py` runs mypy
over this file and requires the errors to land on exactly the lines marked
`# want-error`.

**Why a file like this has to exist.** `AdapterPlugin.__call__` now says
`app: PluginHost`, and that retype is *provably inert on its own*: nothing in
the repository statically accepts an `AdapterPlugin`. Its only consumer is
`validate_adapter(obj: Any)` (`app/adapters/_validation.py:30`) — which does a
runtime `isinstance`, blind to signatures by construction, and which is called
from **tests only**, never from production. So mypy had nothing to check the
retype against, and a green suite would have meant nothing at all.

`takes_an_adapter` below is that missing consumer. It is the door, and these
calls are what make the door bite.

**A marked line is a truth about today, not a wish.** Two different truths:

- `CliAdapter`, `TuiAdapter`, `HttpAdapter` and `LambdaAdapter` declare
  `app: FunctualizeApp`. A parameter type is contravariant, so an
  implementation must accept at least what the protocol promises to pass, and
  `FunctualizeApp` is *one* `PluginHost` rather than any. **T10 widens these
  four and removes their four markers.**
- `MCPAdapterPlugin` fails for an older and unrelated reason: it has **no
  `run` and no `shutdown`**, two of the protocol's three methods. It is named
  `…AdapterPlugin`, it sets `adapter_type = "mcp"`, and its docstring says
  *"Implements the AdapterPlugin protocol"* — none of which was ever true, and
  nothing checked, because it is loaded as a plain `functualize.plugins` entry
  point and never passed to `validate_adapter`. **T10 will not fix this one**;
  it is recorded for `plugin-taxonomy`, whose subject is what a plugin is.

`HttpServerPlugin` is deliberately absent. Its own docstring says *"The plugin
is NOT an adapter — it augments the CLI adapter with an HTTP serving
command."*, and it is right; T10 still widens its `app` parameter, but this
door is not the one that would notice.
"""
# ruff: noqa: E301, E302, E305, E704, ARG001, D103, TC001, I001

from __future__ import annotations

from functualize._types.protocols import AdapterPlugin
from functualize.app.adapters.cli import CliAdapter
from functualize.app.adapters.tui import TuiAdapter
from functualize_http import HttpAdapter
from functualize_lambda import LambdaAdapter
from functualize_mcp import MCPAdapterPlugin


def takes_an_adapter(adapter: AdapterPlugin) -> None: ...


# `app: FunctualizeApp` — narrower than the protocol promises. T10 widens these.
takes_an_adapter(CliAdapter())  # want-error
takes_an_adapter(TuiAdapter())  # want-error
takes_an_adapter(HttpAdapter())  # want-error
takes_an_adapter(LambdaAdapter())  # want-error

# Missing `run` and `shutdown`. Not T10's to fix — see this file's docstring.
takes_an_adapter(MCPAdapterPlugin())  # want-error
