"""Every entry point resolves a group option the same way, or says why not.

`test_group_options_injection.py` pins the ladder through one entry point and
one depth. The claim the documentation makes is wider than that:
`docs/guides/group-options.md` tells a reader that `rc.invoke` resolves the same
layers `app.execute` does, and only `app.execute` was ever tested. This module
is the matrix that makes the wider claim falsifiable.

Four axes:

* **entry point** — CLI dispatch · `app.execute` · `rc.invoke` · a `@workflow`
  step
* **winning layer** — default · file · env · group-CLI
* **declaring depth** — `[deploy]` · `[deploy.web]`
* **field kind** — plain `str` · `Secret[str]`

Not every cell is reachable, and the unreachable ones are marked rather than
faked — but **fewer are unreachable than the sibling module says**.
`test_group_options_injection.py:123-126` states that "`app.execute` deliberately
has no `group_option_values` parameter". It has one, keyword-only, and
`app/core.py:592-598` documents it: the CLI fills it from the flags it consumed
mid-path, and MCP fills it from the group fields in a tool's input schema. So the
facade reaches all four layers, and this module asserts that rather than the
docstring. The sibling module is not edited here; none of its own assertions
depend on the stale sentence.

The group-CLI layer is genuinely out of reach for the entry points that are
handed no such dict — `rc.invoke` and a `@workflow` step — and those two axes
observe before they assert (4.2, 4.3).

Every armed layer also arms the layers *below* it, so a passing cell asserts a
precedence, not merely that one source is readable in isolation.

Jobs are registered under their **dotted** paths here. The sibling module
registers flat names (`register_dynamic_job("run", ...)`), which is correct for
what it tests and means `rc.invoke("deploy.web.run")` resolves nothing there —
the reason this axis needed a new module rather than a new test.

Written without `from __future__ import annotations` for the same reason the
sibling module is: the group option classes must be resolvable as live
annotations.
"""

import sys
import textwrap
from collections.abc import Generator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from functualize._app.state import AppState
from functualize._cli.dispatch import walk_group_path
from functualize._types.descriptors import FieldDescriptor, GroupOptionsSpec
from functualize.app.core import FunctualizeApp
from functualize.app.utils import build_group_trie
from functualize.job import RunStatus

_JOB_MODULE = """
from typing import Annotated

from functualize.job import GroupOptions, Option, RunContext
from functualize.types import Secret
from functualize.workflow import END, Edge, Step, workflow


class DeployOptions(GroupOptions, group="deploy"):
    env: Annotated[str, Option("-e")] = "staging"
    token: Secret[str] = Secret("default-secret")


class WebOptions(GroupOptions, group="deploy.web"):
    region: str = "us-east-1"
    web_token: Secret[str] = Secret("default-web-secret")


def _seen(opts, web):
    # One job reports every (depth, kind) cell, so a run pins four cells at
    # once and a disagreement between them is visible in one assertion.
    return {
        "deploy/plain": opts.env,
        "deploy/secret": opts.token.get_secret_value(),
        "deploy.web/plain": web.region,
        "deploy.web/secret": web.web_token.get_secret_value(),
    }


#: What the job resolved, in call order. A workflow step's return value is
#: consumed by the walk and never surfaces as the workflow's own return, so
#: recording is the only way to read what the *step* saw rather than what the
#: epilogue returned.
SEEN = []


def run(opts: DeployOptions = None, web: WebOptions = None) -> dict:
    SEEN.append(_seen(opts, web))
    return SEEN[-1]


def caller(rc: RunContext) -> dict:
    # The `rc.invoke` axis: a real invoke through the engine's own seam.
    return rc.invoke("deploy.web.run").return_value


@workflow(
    steps=[Step("deploy.web.run")],
    edges=[Edge(source="deploy.web.run", target=END)],
)
def orchestrate(rc: RunContext) -> str:
    # The `@workflow` axis. This body is the epilogue; the step is the point.
    return "walked"
"""


def _job_module() -> ModuleType:
    """Compile the job module and register it, as the sibling module does.

    Pydantic resolves a model's annotations through
    ``sys.modules[cls.__module__].__dict__``; a module object that exists only
    as a local is unreachable from there.
    """
    module = ModuleType("combination_matrix_jobs")
    sys.modules[module.__name__] = module
    exec(
        compile(textwrap.dedent(_JOB_MODULE), module.__name__, "exec"), module.__dict__
    )
    return module


@pytest.fixture(autouse=True)
def _isolated_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None]:
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(project)
    AppState.reset()
    yield
    AppState.reset()


# --- the axes --------------------------------------------------------------

WINNING_LAYERS = ("default", "file", "env", "group-cli")
DEPTHS = ("deploy", "deploy.web")
KINDS = ("plain", "secret")

#: `(depth, kind)` -> the field's name, and the variable that sets it. A
#: dotted group path flattens with single underscores for the environment and
#: stays dotted for the config section.
FIELDS = {
    ("deploy", "plain"): ("env", "DEPLOY__ENV"),
    ("deploy", "secret"): ("token", "DEPLOY__TOKEN"),
    ("deploy.web", "plain"): ("region", "DEPLOY_WEB__REGION"),
    ("deploy.web", "secret"): ("web_token", "DEPLOY_WEB__WEB_TOKEN"),
}

DEFAULTS = {
    ("deploy", "plain"): "staging",
    ("deploy", "secret"): "default-secret",
    ("deploy.web", "plain"): "us-east-1",
    ("deploy.web", "secret"): "default-web-secret",
}


def _value(layer: str, depth: str, kind: str) -> str:
    """The value a given layer supplies, unique per cell so nothing aliases."""
    return f"{layer}-{depth.replace('.', '-')}-{kind}"


def _expected(layer: str, depth: str, kind: str) -> str:
    return DEFAULTS[(depth, kind)] if layer == "default" else _value(layer, depth, kind)


def _arm(layer: str, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Arm every layer up to and including ``layer``.

    Returns the group-CLI dict for the caller to feed to whichever entry point
    it is exercising, empty unless the CLI layer is the one that must win. The
    lower layers are armed too — a cell that only ever sets its own layer
    proves the source is *readable*, not that it *wins*.
    """
    rank = WINNING_LAYERS.index(layer)

    if rank >= WINNING_LAYERS.index("file"):
        sections: dict[str, list[str]] = {"deploy": [], "deploy.web": []}
        for (depth, kind), (field, _) in FIELDS.items():
            sections[depth].append(f'{field} = "{_value("file", depth, kind)}"')
        Path("config.base.toml").write_text(
            "\n\n".join(
                f"[{section}]\n" + "\n".join(lines)
                for section, lines in sections.items()
            )
            + "\n"
        )

    if rank >= WINNING_LAYERS.index("env"):
        for (depth, kind), (_, env_name) in FIELDS.items():
            monkeypatch.setenv(env_name, _value("env", depth, kind))

    AppState.reset()

    if rank < WINNING_LAYERS.index("group-cli"):
        return {}
    return {
        field: _value("group-cli", depth, kind)
        for (depth, kind), (field, _) in FIELDS.items()
    }


# --- the entry points ------------------------------------------------------


def _app(module: ModuleType) -> FunctualizeApp:
    """Jobs under their dotted paths, so `rc.invoke("deploy.web.run")` resolves."""
    app = FunctualizeApp(name="matrix")
    app.register_dynamic_job("deploy.web.run", module.run)
    app.register_dynamic_job("caller", module.caller)
    app.register_dynamic_job("orchestrate", module.orchestrate)
    return app


def _via_engine(
    app: FunctualizeApp, job_name: str, group_options: dict[str, Any] | None
) -> Any:
    entry = app.job_registry.get_job(job_name)
    return app._execution_engine.execute(
        job_name,
        entry.function,
        config_class=entry.config_class,
        kwargs={},
        group_option_values=group_options,
    )


def _spec(group: str, *names: str) -> GroupOptionsSpec:
    return GroupOptionsSpec(
        group=group,
        class_name="X",
        fields=[
            FieldDescriptor(
                name=name,
                type_annotation="str",
                default=None,
                description="",
                required=False,
                short_flag=None,
            )
            for name in names
        ],
    )


def _via_cli_dispatch(app: FunctualizeApp, group_options: dict[str, Any]) -> Any:
    """The real argv walk, then the engine — the two halves the binary joins.

    Not a subprocess: `test_group_options_cli_e2e.py` owns that (and is marked
    slow for it). What this axis has to prove is that the dict the walk
    produces is the dict the engine resolves, so it uses the walk's own output
    rather than one written by hand.
    """
    trie = build_group_trie(
        [("deploy.web", "deploy.web.run", "job")],
        groups=["deploy", "deploy.web"],
        builtin=False,
        group_options={
            "deploy": _spec("deploy", "env", "token"),
            "deploy.web": _spec("deploy.web", "region", "web_token"),
        },
    )
    argv = ["deploy"]
    for field in ("env", "token"):
        if field in group_options:
            argv += [f"--{field}", group_options[field]]
    argv.append("web")
    for field in ("region", "web_token"):
        if field in group_options:
            argv += [f"--{field.replace('_', '-')}", group_options[field]]
    argv.append("run")

    walk = walk_group_path(trie, argv)
    assert walk.bad_flag is None, f"the walk rejected {walk.bad_flag!r} from {argv}"
    assert walk.node.payload == "deploy.web.run", walk.node.payload
    assert walk.options == group_options, (
        "the walk did not recover the values typed on the command line: "
        f"{walk.options} != {group_options}"
    )
    return _via_engine(app, walk.node.payload, walk.options)


#: Entry points this task covers, and whether a group-CLI dict can reach them.
#: Both can: the facade takes `group_option_values` keyword-only. The remaining
#: two axes — `rc.invoke` and a `@workflow` step — are 4.3 and 4.2, in this same
#: module.
ENTRY_POINTS = {
    "cli-dispatch": True,
    "app-execute": True,
}


def _cells(entry_point: str) -> list[tuple[str, str, str]]:
    """`(layer, depth, kind)` for the reachable cells of one entry point."""
    return [
        (layer, depth, kind)
        for layer in WINNING_LAYERS
        for depth in DEPTHS
        for kind in KINDS
        if layer != "group-cli" or ENTRY_POINTS[entry_point]
    ]


# --- the matrix ------------------------------------------------------------


@pytest.mark.parametrize(
    ("layer", "depth", "kind"),
    _cells("app-execute"),
    ids=lambda v: str(v),
)
def test_app_execute_resolves_every_reachable_layer(
    layer: str, depth: str, kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The facade resolves all four layers, group-CLI included."""
    group_options = _arm(layer, monkeypatch)
    app = _app(_job_module())

    result = app.execute("deploy.web.run", group_option_values=group_options or None)

    assert result.status is RunStatus.SUCCESS, repr(result.exception)
    assert result.return_value[f"{depth}/{kind}"] == _expected(layer, depth, kind)


@pytest.mark.parametrize(
    ("layer", "depth", "kind"),
    _cells("cli-dispatch"),
    ids=lambda v: str(v),
)
def test_cli_dispatch_resolves_every_layer(
    layer: str, depth: str, kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """argv through the real walk, then the engine — including the CLI layer."""
    group_options = _arm(layer, monkeypatch)
    app = _app(_job_module())

    result = _via_cli_dispatch(app, group_options)

    assert result.status is RunStatus.SUCCESS, repr(result.exception)
    assert result.return_value[f"{depth}/{kind}"] == _expected(layer, depth, kind)


def test_the_facade_accepts_a_group_cli_layer() -> None:
    """Observed, against a claim to the contrary.

    `test_group_options_injection.py:123-126` says `app.execute` "deliberately
    has no `group_option_values` parameter". It has one, keyword-only, and
    `app/core.py:592-598` documents two callers that fill it — the CLI from the
    flags it consumed mid-path, MCP from a tool's input schema. Pinned here so
    the matrix cannot quietly go back to treating those cells as impossible.
    """
    import inspect

    parameter = inspect.signature(FunctualizeApp.execute).parameters.get(
        "group_option_values"
    )

    assert parameter is not None
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is None, (
        "omitting it must stay equivalent to passing nothing, so that a plain "
        "execute() still resolves the file/env/default layers"
    )


def test_omitting_the_facades_group_cli_layer_still_resolves_the_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`app/core.py:597-598`: a plain `execute("deploy.web.run")` is complete."""
    _arm("env", monkeypatch)
    app = _app(_job_module())

    result = app.execute("deploy.web.run")

    assert result.status is RunStatus.SUCCESS, repr(result.exception)
    assert result.return_value["deploy/plain"] == _value("env", "deploy", "plain")
    assert result.return_value["deploy.web/secret"] == _value(
        "env", "deploy.web", "secret"
    )


# ===========================================================================
# 4.2 — the workflow axis, through the real seam
# ===========================================================================
#
# Reachability (constitution): the production path is `executor.py:1011-1077`.
# A workflow job executed through the engine builds a `WorkflowRunner`, which
# builds a `WorkflowWalker`, whose `run_step` calls
# `self.execute(step_name, kwargs={}, invoke_depth=invoke_depth + 1, ...)`.
# These execute a workflow job and let that seam run.
#
# Constructing a `WorkflowWalker` directly with a hand-written `run_step` — the
# shape `tests/test_workflow_walker.py` uses, correctly, for walker unit tests —
# would bypass the exact line under test and prove nothing about it.

_NON_CLI_LAYERS = ("default", "file", "env")


def _step_cells() -> list[tuple[str, str, str]]:
    return [
        (layer, depth, kind)
        for layer in _NON_CLI_LAYERS
        for depth in DEPTHS
        for kind in KINDS
    ]


@pytest.mark.parametrize(
    ("layer", "depth", "kind"), _step_cells(), ids=lambda v: str(v)
)
def test_a_workflow_step_resolves_every_non_cli_layer(
    layer: str, depth: str, kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A step is an ordinary job run, so its group options resolve like one."""
    _arm(layer, monkeypatch)
    module = _job_module()
    app = _app(module)

    result = app.execute("orchestrate")

    assert result.status is RunStatus.SUCCESS, repr(result.exception)
    assert module.SEEN, (
        "the walk never ran the step — this cell would pass vacuously, which is "
        "the failure mode a workflow assertion has to rule out first"
    )
    assert module.SEEN[-1][f"{depth}/{kind}"] == _expected(layer, depth, kind)


def test_a_workflow_step_does_not_inherit_the_group_cli_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Observed, not predicted: `run_step` passes no `group_option_values`.

    The workflow job is given one and the step still resolves from env. The
    file/env/default layers do cross — asserted above — so this is a boundary,
    not a step that resolves nothing.
    """
    _arm("env", monkeypatch)
    module = _job_module()
    app = _app(module)

    result = app.execute(
        "orchestrate",
        group_option_values={"env": "cli-env", "region": "cli-region"},
    )

    assert result.status is RunStatus.SUCCESS, repr(result.exception)
    assert module.SEEN[-1]["deploy/plain"] == _value("env", "deploy", "plain")
    assert module.SEEN[-1]["deploy.web/plain"] == _value("env", "deploy.web", "plain")


# ===========================================================================
# 4.3 — the `rc.invoke` boundary: observed first, then asserted
# ===========================================================================
#
# `docs/guides/group-options.md:149-150` tells a reader that `rc.invoke`
# resolves the same layers `app.execute` does. It does — for every layer that
# comes from a *source*. It does not for the group-CLI layer, which is not a
# source but a dict the caller was handed, and `rc.invoke` is handed none.
#
# This was observed before it was asserted. Running the parent with
# `group_option_values={"env": "cli-env", ...}` and reading what the invoked
# child resolved returned the env value, not the CLI one.


@pytest.mark.parametrize(
    ("layer", "depth", "kind"), _step_cells(), ids=lambda v: str(v)
)
def test_rc_invoke_resolves_every_non_cli_layer(
    layer: str, depth: str, kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The half of the documented claim that is true."""
    _arm(layer, monkeypatch)
    app = _app(_job_module())

    result = app.execute("caller")

    assert result.status is RunStatus.SUCCESS, repr(result.exception)
    assert result.return_value[f"{depth}/{kind}"] == _expected(layer, depth, kind)


def test_the_group_cli_layer_does_not_cross_an_invoke_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The half that is not, pinned as observed.

    A mid-path flag belongs to the command line that typed it. `rc.invoke`
    starts no command line, so the child resolves from its own sources — here,
    env — while the parent's CLI layer stays with the parent.
    """
    _arm("env", monkeypatch)
    app = _app(_job_module())

    parent = app.execute(
        "caller",
        group_option_values={"env": "cli-env", "region": "cli-region"},
    )

    assert parent.status is RunStatus.SUCCESS, repr(parent.exception)
    assert parent.return_value["deploy/plain"] == _value("env", "deploy", "plain")
    assert parent.return_value["deploy.web/plain"] == _value(
        "env", "deploy.web", "plain"
    )


def test_the_direct_run_and_the_invoked_run_agree_on_every_source_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The claim `group-options.md` makes, stated as one comparison."""
    _arm("env", monkeypatch)
    app = _app(_job_module())

    direct = app.execute("deploy.web.run")
    invoked = app.execute("caller")

    assert direct.return_value == invoked.return_value
