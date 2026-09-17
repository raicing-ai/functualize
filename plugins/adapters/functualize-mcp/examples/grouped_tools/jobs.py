"""Grouped jobs served over MCP — the namespace + codegen reference.

Serve with:
    func mcp serve

`JOB_GROUP = "probe"` puts every job under the `probe` namespace, so the MCP
tool names are dotted: `probe.ping`, `probe.echo`, `probe.quote`. Dotted
names are legal MCP tool names; agents address the job by its full
functualize name, exactly as `func mcp tools` and `func mcp schema` print it.

`probe.secret` stays hidden (`visibility="internal"`).

`probe.quote` deliberately carries a docstring with triple single quotes and
a backslash — tool descriptions are attached after codegen, never
interpolated into source, so hostile docstrings cannot break registration.
"""

from functualize.job import Log, job

JOB_GROUP = "probe"


@job
def ping(log: Log) -> str:
    """Return a fixed greeting.

    The simplest callable: no arguments, always answers "pong".
    """
    log("probe.ping: called")
    return "pong"


@job
def echo(log: Log, text: str) -> str:
    """Echo the text argument back verbatim.

    One typed argument (`text: str`). The argument schema an agent sees for
    this tool is exactly what the job accepts.
    """
    log(f"probe.echo: called with text={text!r}")
    return text


@job(visibility="internal")
def secret(log: Log) -> str:
    """Internal maintenance — hidden from MCP agents.

    A `visibility="internal"` job inside a group is filtered before tool
    registration, exactly like its ungrouped sibling.
    """
    log("probe.secret: called (should never be reachable via MCP)")
    return "hidden"


@job
def quote(log: Log, text: str) -> str:
    """Wrap text in quotes. Say: ''' hostile \\ docstring, two lines:
    still one description."""

    log(f"probe.quote: called with text={text!r}")
    return f"'{text}'"
