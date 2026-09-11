"""CLI and MCP expose the same workflow verbs, with the same parameters.

Parity was **asserted** before and was false. The old `resume` took
`(id, gate)` and no MCP tool took both; `list` and `state` returned different
shapes from the tools that mirrored them. Stating parity in a docstring is not
enough — `contributor/reference/pitfalls.md` §19: *a docstring claiming parity
is a claim; a parity test is the parity.*

**This test enumerates; it does not sample.** Both sets are derived from the
live surfaces — the click command tree and the registered MCP tool list — so a
verb or parameter added to one side and not the other fails here **without
anyone editing this file**. A hardcoded list of verbs would just be a sixth
copy of the vocabulary (`pitfalls.md` §6), stale the first time someone adds a
verb and forgets it.

The precedent is `tests/config/test_env_name_rule_parity.py`, which derives the
value from each producer rather than checking one against a literal.
"""

from __future__ import annotations

import inspect
from collections.abc import Generator

import click
import pytest
from functualize_mcp._workflow_tools import WorkflowToolProvider

from functualize._app.state import AppState
from functualize._cli.builtins import register_builtin_commands
from functualize.app.core import FunctualizeApp

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def _reset() -> Generator[None]:
    AppState.reset()
    yield
    AppState.reset()


#: CLI verb -> MCP tool. The **only** hand-written thing here, because the two
#: surfaces legitimately name their verbs for different audiences: a CLI reads
#: `workflow show`, a tool list reads `get_workflow_state`. Everything else —
#: which verbs exist, which parameters each takes — is read off the live
#: surfaces, so this map cannot hide a missing verb: an unmapped verb on either
#: side fails below.
VERB_TO_TOOL = {
    "list": "list_workflows",
    "show": "get_workflow_state",
    "answer": "answer_gate",
    "resume": "resume_workflow",
    "gate-tool": "call_gate_tool",
    "cancel": "cancel_workflow",
    "purge": "purge_workflows",
    "reclaim": "reclaim_workflow",
}

#: Parameters that exist on one surface for a reason that is *about the
#: surface*, not about the verb. Each needs a stated reason; anything else is
#: drift.
SURFACE_ONLY = {
    # Rendering. A tool returns structured data and the client renders it; a
    # terminal has to be told how.
    "--format",
    # Click's negatable spelling of a boolean a tool takes as `commit=False`.
    "--no-commit",
    # `--set K=V` and `--input JSON` are two spellings of "values" for a shell,
    # which has only strings. A tool takes one `values` object, because JSON is
    # already its input form — so `--replace` is `mode="replace"` there.
    "--set",
    "--input",
    "--replace",
    # `get_gate_draft` is `answer --show`. A tool that changed nothing but was
    # spelled as the mutating verb would be a trap for an agent.
    "--show",
}

#: MCP tools with no CLI verb of their own, each folded into a CLI *option*.
TOOL_IS_A_CLI_OPTION = {"get_gate_draft": "answer --show"}

#: `builtin run` verb -> MCP tool (`durable-run-layer`/T3).
#:
#: A second group rather than more `workflow` verbs, because the two answer
#: different questions: a scope is a workflow's *position* and exists to be
#: resumed, a run is one *execution* and exists to be read afterwards. One
#: provider serves both, so the parity check has to span both — otherwise
#: adding a run tool would silently pass by having no CLI group to be missing
#: from.
RUN_VERB_TO_TOOL = {
    "list": "list_runs",
    "show": "get_run",
}

#: Run tools folded into a CLI *option* rather than a verb of their own.
RUN_TOOL_IS_A_CLI_OPTION = {"get_run_events": "run show --events"}


@pytest.fixture
def app() -> FunctualizeApp:
    return FunctualizeApp(name="parity")


def _builtin_group(name: str) -> dict[str, click.Command]:
    """Every subcommand of `builtin <name>`, from the live command tree."""
    root = click.Group(name="func")
    register_builtin_commands(root)
    group = root.commands["builtin"].commands[name]  # type: ignore[attr-defined]
    return dict(group.commands)  # type: ignore[attr-defined]


def cli_verbs() -> dict[str, click.Command]:
    """Every `builtin workflow` subcommand."""
    return _builtin_group("workflow")


def run_verbs() -> dict[str, click.Command]:
    """Every `builtin run` subcommand."""
    return _builtin_group("run")


def mcp_tools(app: FunctualizeApp) -> dict[str, object]:
    """Every registered workflow tool, from the live provider."""
    collected: dict[str, object] = {}

    class _Collector:
        def add_tool(self, fn: object) -> None:
            collected[getattr(fn, "__name__", "")] = fn

    WorkflowToolProvider(app).register_tools(_Collector())
    return collected


def _cli_option_names(command: click.Command) -> set[str]:
    names: set[str] = set()
    for param in command.params:
        if isinstance(param, click.Option):
            names.update(param.opts)
    return names


def _tool_param_names(fn: object) -> set[str]:
    """Named parameters of a tool coroutine.

    Filtered by **kind**, not by name: an earlier cut dropped anything called
    `args` or `kwargs` to skip `*args`/`**kwargs`, and `call_gate_tool` has a
    real parameter named `args` — so the parity check reported a gap that did
    not exist. A test that cries wolf is how a real gap gets waved through.
    """
    signature = inspect.signature(fn)  # type: ignore[arg-type]
    variadic = {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
    return {
        name
        for name, param in signature.parameters.items()
        if name != "self" and param.kind not in variadic
    }


class TestEveryVerbHasATwin:
    """AC-29. The check that fails when either surface grows alone."""

    def test_every_cli_verb_maps_to_a_tool(self, app: FunctualizeApp) -> None:
        unmapped = set(cli_verbs()) - set(VERB_TO_TOOL)
        assert not unmapped, (
            f"CLI verbs with no MCP twin: {sorted(unmapped)}. Add the tool, or "
            "add the verb to VERB_TO_TOOL with the tool it maps to."
        )

    def test_every_run_verb_maps_to_a_tool(self, app: FunctualizeApp) -> None:
        unmapped = set(run_verbs()) - set(RUN_VERB_TO_TOOL)
        assert not unmapped, (
            f"`builtin run` verbs with no MCP twin: {sorted(unmapped)}. Add "
            "the tool, or add the verb to RUN_VERB_TO_TOOL."
        )

    def test_every_tool_maps_to_a_verb(self, app: FunctualizeApp) -> None:
        """Spans **both** groups.

        One provider serves `workflow` and `run`, so checking only the workflow
        group would let a run tool pass by having no CLI group to be missing
        from — a gap that widens exactly when a new surface is added, which is
        when it is least likely to be noticed.
        """
        mapped = (
            set(VERB_TO_TOOL.values())
            | set(TOOL_IS_A_CLI_OPTION)
            | set(RUN_VERB_TO_TOOL.values())
            | set(RUN_TOOL_IS_A_CLI_OPTION)
        )
        unmapped = set(mcp_tools(app)) - mapped
        assert not unmapped, (
            f"MCP tools with no CLI twin: {sorted(unmapped)}. Add the verb, or "
            "record it in TOOL_IS_A_CLI_OPTION with the option it folds into."
        )

    def test_the_map_is_not_stale(self, app: FunctualizeApp) -> None:
        """A mapping entry naming something that no longer exists would let a
        genuinely missing verb pass unnoticed."""
        verbs, tools = cli_verbs(), mcp_tools(app)
        for verb, tool in VERB_TO_TOOL.items():
            assert verb in verbs, f"VERB_TO_TOOL names a missing CLI verb: {verb}"
            assert tool in tools, f"VERB_TO_TOOL names a missing MCP tool: {tool}"
        for tool in TOOL_IS_A_CLI_OPTION:
            assert tool in tools, f"TOOL_IS_A_CLI_OPTION names a missing tool: {tool}"

        runs = run_verbs()
        for verb, tool in RUN_VERB_TO_TOOL.items():
            assert verb in runs, f"RUN_VERB_TO_TOOL names a missing CLI verb: {verb}"
            assert tool in tools, f"RUN_VERB_TO_TOOL names a missing MCP tool: {tool}"
        for tool in RUN_TOOL_IS_A_CLI_OPTION:
            assert tool in tools, (
                f"RUN_TOOL_IS_A_CLI_OPTION names a missing tool: {tool}"
            )


class TestAddressingMatches:
    """Contracts §4.2 — every verb takes the same identifiers on both sides."""

    @pytest.mark.parametrize(
        ("verb", "tool"),
        [(v, t) for v, t in VERB_TO_TOOL.items() if v not in {"list", "purge"}],
    )
    def test_a_scope_addressed_verb_takes_the_scope_on_both(
        self, app: FunctualizeApp, verb: str, tool: str
    ) -> None:
        command = cli_verbs()[verb]
        positionals = {p.name for p in command.params if isinstance(p, click.Argument)}
        assert "workflow_id" in positionals, verb
        assert "workflow_id" in _tool_param_names(mcp_tools(app)[tool]), tool

    def test_answer_takes_both_identifiers_on_both_surfaces(
        self, app: FunctualizeApp
    ) -> None:
        """The hole this closes: `resume_gate` took a gate, `resume_workflow`
        took a scope, and each referred the caller to the other on ambiguity —
        so a caller holding both had no tool that would accept them."""
        command = cli_verbs()["answer"]
        positionals = [p.name for p in command.params if isinstance(p, click.Argument)]
        assert positionals == ["workflow_id", "gate"]

        params = _tool_param_names(mcp_tools(app)["answer_gate"])
        assert {"workflow_id", "gate"} <= params

    def test_list_takes_the_same_three_filters(self, app: FunctualizeApp) -> None:
        cli = _cli_option_names(cli_verbs()["list"])
        assert {"--workflow", "--state", "--blocked-on"} <= cli

        tool = _tool_param_names(mcp_tools(app)["list_workflows"])
        assert {"workflow_name", "state", "blocked_on"} <= tool


class TestParameterParity:
    """Every CLI option is either a tool parameter or a stated surface-only
    exception. Nothing drifts silently."""

    @pytest.mark.parametrize(("verb", "tool"), sorted(VERB_TO_TOOL.items()))
    def test_each_cli_option_has_a_tool_parameter(
        self, app: FunctualizeApp, verb: str, tool: str
    ) -> None:
        options = _cli_option_names(cli_verbs()[verb]) - {"--help"} - SURFACE_ONLY
        params = _tool_param_names(mcp_tools(app)[tool])

        missing = {
            opt
            for opt in options
            if opt.lstrip("-").replace("-", "_") not in params
            and _aliases(opt).isdisjoint(params)
        }
        assert not missing, (
            f"`{verb}` has options the `{tool}` tool cannot express: "
            f"{sorted(missing)}. Add the parameter, or record the option in "
            "SURFACE_ONLY with the reason it is surface-specific."
        )


def _aliases(option: str) -> set[str]:
    """Spellings a tool may legitimately use for one CLI option.

    The two surfaces name things for different audiences — a shell flag reads
    `--older-than DAYS`, a typed tool parameter reads `older_than_days` — so a
    strict string match would force one of them to read badly.
    """
    base = option.lstrip("-").replace("-", "_")
    return {
        base,
        f"{base}_name",  # --workflow      -> workflow_name
        f"{base}_days",  # --older-than    -> older_than_days
        f"{base}s",  # --unset         -> unset
        base.removeprefix("no_"),
    }


class TestTheHonestException:
    def test_prompt_gates_is_cli_only_and_that_is_documented(self) -> None:
        """`--prompt-gates` resolves gates interactively, inline. MCP cannot:
        its strategy is `ai_outbound`, which always blocks by design.

        So parity is on **verbs and their contracts**, not on interactive
        capability — and this is the one place functualize is ahead of
        pi-workflows, which deliberately never resolves protected decisions
        inline. Asserted here so the exception stays deliberate rather than
        becoming the first crack in the rule.
        """
        assert "--prompt-gates" not in {
            opt for cmd in cli_verbs().values() for opt in _cli_option_names(cmd)
        }, "if it ever reaches a workflow verb, MCP needs an answer for it"


class TestRunAddressingMatches:
    """The run verbs take the same identifiers and filters on both surfaces."""

    def test_show_takes_the_run_id_on_both(self, app: FunctualizeApp) -> None:
        command = run_verbs()["show"]
        positionals = {p.name for p in command.params if isinstance(p, click.Argument)}
        assert "run_id" in positionals
        assert "run_id" in _tool_param_names(mcp_tools(app)["get_run"])

    def test_events_takes_the_run_id_on_both(self, app: FunctualizeApp) -> None:
        """`--events` is an option on `run show`; `get_run_events` is a tool.

        Recorded in RUN_TOOL_IS_A_CLI_OPTION for the reason `get_gate_draft`
        is: a terminal wants one command that can show more, an agent wants a
        tool whose name says what it returns.
        """
        assert "--events" in _cli_option_names(run_verbs()["show"])
        assert "run_id" in _tool_param_names(mcp_tools(app)["get_run_events"])

    def test_list_takes_the_same_filters(self, app: FunctualizeApp) -> None:
        cli = _cli_option_names(run_verbs()["list"])
        assert {"--job", "--surface", "--state", "--scope", "--limit"} <= cli

        tool = _tool_param_names(mcp_tools(app)["list_runs"])
        assert {"job", "surface", "state", "scope_id", "limit"} <= tool

    def test_show_offers_the_tree_on_both(self, app: FunctualizeApp) -> None:
        assert "--tree" in _cli_option_names(run_verbs()["show"])
        assert "tree" in _tool_param_names(mcp_tools(app)["get_run"])
