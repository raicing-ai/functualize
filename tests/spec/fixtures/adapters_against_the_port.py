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

**A marked line is a truth about today, not a wish.** Three marks remain after
T10, for two different reasons, and neither is an oversight.

`CliAdapter` and `TuiAdapter` keep `app: FunctualizeApp` **by decision**, and
they are the two adapters that live in `src/functualize/` rather than in a
plugin. T10 measured what each reaches by widening the annotation and reading
mypy:

- `CliAdapter.__call__` reads `app.name` — to name the click group — and hands
  `app` to `register_discovered_jobs` and `register_plugin_commands`, two core
  helpers that take the whole `FunctualizeApp`. `name` is **not** on the port,
  and the census says it should not be: `rg 'app[.]name' plugins/*/src
  examples/*/*/src` finds **zero** plugin clients, so it fails the same
  client-count rule every other member had to pass.
- `TuiAdapter.__call__` reads *nothing* — it only stores the reference — but
  `run()` hands it to `launch_inline_tui(app: FunctualizeApp)`, deep `_cli`
  machinery with its own steering document.

`tasks.md` for T10 authorised exactly this: *"If it reaches an app member the
11-member port lacks, the port does not grow: `CliAdapter` is core, not a
plugin, and may keep `FunctualizeApp` with T9's assertion scoped to the plugin
adapters."* The same argument covers `TuiAdapter`, and the line it draws is the
honest one — the port is the **plugin** boundary, and core code that is handed
the whole application may name the whole application. It does mean AC-18's
"four adapters" is really two; that deviation is recorded in `tasks.md`.

`MCPAdapterPlugin` fails for an older and unrelated reason: it has **no `run`
and no `shutdown`**, two of the protocol's three methods. It is named
`…AdapterPlugin`, it sets `adapter_type = "mcp"`, and its docstring says
*"Implements the AdapterPlugin protocol"* — none of which was ever true, and
nothing checked, because it is loaded as a plain `functualize.plugins` entry
point and never passed to `validate_adapter`. Recorded for `plugin-taxonomy`,
whose subject is what a plugin is.

**`HttpAdapter` and `LambdaAdapter` widened cleanly** — the two unmarked calls
below. Both reach nothing outside the eleven members, measured the same way,
and neither package imports `FunctualizeApp` any more at all.

`HttpServerPlugin` is deliberately absent from this door. Its own docstring
says *"The plugin is NOT an adapter — it augments the CLI adapter with an HTTP
serving command."*, and it is right; T10 widened its `app` parameter too, but
this door is not the one that would notice.
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


# Widened by T10. Nothing in either reaches past the port's eleven members.
takes_an_adapter(HttpAdapter())
takes_an_adapter(LambdaAdapter())

# Core adapters, keeping `app: FunctualizeApp` by decision — see the docstring.
takes_an_adapter(CliAdapter())  # want-error
takes_an_adapter(TuiAdapter())  # want-error

# Missing `run` and `shutdown`. A different defect — see the docstring.
takes_an_adapter(MCPAdapterPlugin())  # want-error
