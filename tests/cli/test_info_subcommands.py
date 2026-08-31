"""`func builtin info` and its structured subcommands.

Job discovery used to be answerable three ways, none of them machine-readable:
a prose listing from a bare piped `func`, rich panels from `info`, and click
help per job. The only JSON lived in the MCP plugin, so an agent without that
plugin had to parse prose or walk every group's `--help` one at a time.

These tests hold the new contract: bare `info` still works (every skill and doc
points at it), the subcommands emit parseable structure, and `[cli] output`
actually selects a renderer instead of being resolved and discarded.
"""

from __future__ import annotations

import json

import pytest

JOBS = {
    "jobs.py": (
        '"""Demo jobs."""\n'
        "from functualize.job import Log, Stdout\n"
        "\n"
        'JOB_GROUP = "demo"\n'
        "\n"
        "\n"
        "def report(log: Log, out: Stdout, rows: int = 3) -> None:\n"
        '    """Emit a small report."""\n'
        "\n"
        "\n"
        "def sweep(log: Log, target: str) -> None:\n"
        '    """Sweep a target."""\n'
    )
}


def _epilog_block(stdout: str) -> list[str]:
    """The lines after the `For AI agents:` heading, in order."""
    lines = stdout.splitlines()
    start = next(i for i, line in enumerate(lines) if "For AI agents:" in line)
    return [line for line in lines[start + 1 :] if line.strip()]


@pytest.fixture
def project(project_tree):
    return project_tree(jobs=JOBS)


def test_bare_info_still_renders_the_overview(cli_run, project):
    """Every skill, doc and habit says `func builtin info` — it must not break."""
    result = cli_run(["builtin", "info"], cwd=project)
    assert result.exit_code == 0
    assert "Agent Skills" in result.stdout
    assert "demo" in result.stdout


def test_bare_info_points_at_the_machine_readable_form(cli_run, project):
    """An agent reading the overview should learn it does not have to."""
    result = cli_run(["builtin", "info"], cwd=project)
    assert "func builtin info schema" in result.stdout


def test_info_jobs_lists_every_job(cli_run, project):
    result = cli_run(["builtin", "info", "jobs"], cwd=project)
    assert result.exit_code == 0
    assert "demo.report" in result.stdout
    assert "demo.sweep" in result.stdout
    # Plain columns, not panels: safe to read through a pipe.
    assert "─" not in result.stdout
    assert "│" not in result.stdout


def test_info_jobs_json_is_parseable(cli_run, project):
    result = cli_run(["builtin", "info", "jobs", "--json"], cwd=project)
    assert result.exit_code == 0
    catalog = json.loads(result.stdout)
    names = {entry["name"] for entry in catalog}
    assert {"demo.report", "demo.sweep"} <= names
    entry = next(e for e in catalog if e["name"] == "demo.report")
    assert entry["group"] == "demo"
    assert entry["summary"] == "Emit a small report."


def test_info_jobs_detail_names_one_job(cli_run, project):
    result = cli_run(["builtin", "info", "jobs", "demo.report", "--json"], cwd=project)
    assert result.exit_code == 0
    detail = json.loads(result.stdout)
    assert detail["name"] == "demo.report"
    assert [p["name"] for p in detail["parameters"]] == ["rows"]
    assert detail["inputSchema"]["properties"]["rows"]["type"] == "integer"


def test_info_jobs_unknown_name_is_a_usage_error(cli_run, project):
    result = cli_run(["builtin", "info", "jobs", "nope"], cwd=project)
    assert result.exit_code == 2
    assert "no job named" in result.stderr


def test_info_schema_emits_every_job(cli_run, project):
    """The one command that answers "what can I call, and with what"."""
    result = cli_run(["builtin", "info", "schema"], cwd=project)
    assert result.exit_code == 0
    schemas = json.loads(result.stdout)
    by_name = {s["name"]: s for s in schemas}
    assert {"demo.report", "demo.sweep"} <= set(by_name)

    report = by_name["demo.report"]
    assert report["description"] == "Emit a small report."
    assert report["inputSchema"]["properties"]["rows"] == {
        "type": "integer",
        "default": 3,
    }


def test_info_schema_excludes_capabilities(cli_run, project):
    """`log` and `out` are engine-injected — never caller-supplied.

    The regression that motivated this: `Stdout` and `Shell` were published as
    required string arguments on the descriptor-driven surfaces.
    """
    result = cli_run(["builtin", "info", "schema"], cwd=project)
    schemas = {s["name"]: s for s in json.loads(result.stdout)}
    properties = schemas["demo.report"]["inputSchema"]["properties"]
    assert set(properties) == {"rows"}
    assert "required" not in schemas["demo.report"]["inputSchema"]


def test_info_schema_one_job_returns_an_object_not_a_list(cli_run, project):
    """Asking about one job should not make the caller index into a list."""
    result = cli_run(["builtin", "info", "schema", "demo.sweep"], cwd=project)
    assert result.exit_code == 0
    schema = json.loads(result.stdout)
    assert isinstance(schema, dict)
    assert schema["name"] == "demo.sweep"
    assert schema["inputSchema"]["required"] == ["target"]


def test_info_schema_unknown_name_is_a_usage_error(cli_run, project):
    result = cli_run(["builtin", "info", "schema", "nope"], cwd=project)
    assert result.exit_code == 2


def test_info_schema_covers_builtins_too(cli_run, project):
    """Jobs and builtins are one tree — the schema must not re-split them.

    `CommandNode`: "Nothing here distinguishes a job from a builtin; that is
    the point." Reading `app.get_jobs()` here would leave an agent walking
    `--help` for the ~30 builtin subcommands, which is the friction the job
    half already removed.
    """
    result = cli_run(["builtin", "info", "schema"], cwd=project)
    assert result.exit_code == 0
    by_name = {entry["name"]: entry for entry in json.loads(result.stdout)}

    assert "demo.report" in by_name
    assert "builtin.skills.materialize" in by_name
    assert by_name["demo.report"]["kind"] == "job"
    assert by_name["builtin.skills.materialize"]["kind"] == "builtin"


def test_builtin_flags_are_typed_not_stringly(cli_run, project):
    """Click and Python spell types differently; one map must know both.

    Before this, every builtin flag degraded to `"type": "string"` —
    `--prune` advertised as text.
    """
    result = cli_run(
        ["builtin", "info", "schema", "builtin.skills.materialize"], cwd=project
    )
    assert result.exit_code == 0
    schema = json.loads(result.stdout)["inputSchema"]
    assert schema["properties"]["prune"]["type"] == "boolean"


def test_builtin_flag_names_are_what_a_caller_types(cli_run, project):
    """`@click.option("--json", "json_out")` must publish `json`, not `json_out`.

    Publishing the Python identifier tells an agent to type `--json-out`,
    which does not exist.
    """
    result = cli_run(["builtin", "info", "schema", "builtin.info"], cwd=project)
    assert result.exit_code == 0
    properties = json.loads(result.stdout)["inputSchema"]["properties"]
    assert "json" in properties
    assert "json_out" not in properties
    assert "show-env-vars" in properties


def test_choice_flags_publish_their_enum(cli_run, project):
    result = cli_run(["builtin", "info", "schema", "builtin.parallel"], cwd=project)
    assert result.exit_code == 0
    output = json.loads(result.stdout)["inputSchema"]["properties"]["output"]
    assert output["enum"] == ["interleaved", "grouped", "prefixed"]


def test_unrepresentable_defaults_are_omitted(cli_run, project):
    """Click marks "no default" with its own sentinel, not None.

    Serialized through, it became the literal string "Sentinel.UNSET" — a
    value no caller could pass. Better omitted than published wrong.
    """
    result = cli_run(["builtin", "info", "schema"], cwd=project)
    for entry in json.loads(result.stdout):
        for name, prop in entry["inputSchema"]["properties"].items():
            assert "Sentinel" not in str(prop.get("default", "")), (
                f"{entry['name']}.{name} publishes a sentinel default"
            )


def test_pure_namespaces_are_not_published_as_runnable(cli_run, project):
    """`builtin cache` only prints usage — listing it would mislead.

    A node with children and no parameters of its own is a namespace, not a
    command. `builtin info` has children *and* `--json`, so it stays.
    """
    result = cli_run(["builtin", "info", "schema"], cwd=project)
    names = {entry["name"] for entry in json.loads(result.stdout)}
    assert "builtin.cache" not in names
    assert "builtin.cache.clear" in names
    assert "builtin.info" in names


def test_path_is_an_array_of_segments(cli_run, project):
    """Structured over opaque — a dotted string would have to be re-split."""
    result = cli_run(["builtin", "info", "schema", "builtin.skills.path"], cwd=project)
    entry = json.loads(result.stdout)
    assert entry["path"] == ["builtin", "skills", "path"]


def test_kind_job_narrows_to_the_previous_behaviour(cli_run, project):
    result = cli_run(["builtin", "info", "schema", "--kind", "job"], cwd=project)
    assert result.exit_code == 0
    entries = json.loads(result.stdout)
    assert entries
    assert {e["kind"] for e in entries} == {"job"}
    assert {e["name"] for e in entries} == {"demo.report", "demo.sweep"}


def test_kind_builtin_narrows_to_the_reserved_subtree(cli_run, project):
    result = cli_run(["builtin", "info", "schema", "--kind", "builtin"], cwd=project)
    assert result.exit_code == 0
    entries = json.loads(result.stdout)
    assert entries
    assert {e["kind"] for e in entries} == {"builtin"}
    assert all(e["path"][0] == "builtin" for e in entries)


def test_jobs_sort_before_builtins(cli_run, project):
    """A caller's own jobs are what they came for; the reserved subtree is not."""
    result = cli_run(["builtin", "info", "schema"], cwd=project)
    kinds = [entry["kind"] for entry in json.loads(result.stdout)]
    assert kinds == sorted(kinds, key=lambda k: k != "job")


def test_info_all_is_one_document(cli_run, project):
    """One fetch instead of four commands and three prose formats."""
    result = cli_run(["builtin", "info", "all", "--json"], cwd=project)
    assert result.exit_code == 0
    report = json.loads(result.stdout)
    assert set(report) >= {"functualize", "environment", "jobs", "skills", "config"}
    assert any(job["name"] == "demo.report" for job in report["jobs"])
    assert report["jobs"][0]["inputSchema"]["type"] == "object"


def test_cli_output_json_selects_the_renderer(cli_run, project):
    """`[cli] output` was resolved, validated — and read by nothing.

    Wiring it means an agent exports it once instead of passing a flag on
    every call.
    """
    result = cli_run(
        ["builtin", "info", "jobs"],
        cwd=project,
        env={"FUNCTUALIZE_CLI_OUTPUT": "json"},
    )
    assert result.exit_code == 0
    assert isinstance(json.loads(result.stdout), list)


def test_cli_output_plain_drops_box_drawing(cli_run, project):
    """`plain` is what makes piped `info` readable by something other than a human."""
    result = cli_run(
        ["builtin", "info"],
        cwd=project,
        env={"FUNCTUALIZE_CLI_OUTPUT": "plain"},
    )
    assert result.exit_code == 0
    assert "╭" not in result.stdout
    assert "│" not in result.stdout
    assert "demo.report" in result.stdout


def test_explicit_json_flag_overrides_the_setting(cli_run, project):
    """The flag is an override, not a mode — it wins over a configured default."""
    result = cli_run(
        ["builtin", "info", "jobs", "--json"],
        cwd=project,
        env={"FUNCTUALIZE_CLI_OUTPUT": "plain"},
    )
    assert result.exit_code == 0
    assert isinstance(json.loads(result.stdout), list)


def test_help_epilog_names_the_schema_command(cli_run):
    """`func --help` must answer "how do I see everything" without a hunt.

    Otherwise the only path to the job catalogue is walking each group's
    `--help` one at a time, which is the friction this exists to remove.
    """
    result = cli_run(["--help"])
    assert result.exit_code == 0
    assert "func builtin info schema" in result.stdout
    assert "func builtin skills list" in result.stdout


def test_help_epilog_names_the_output_env_var(cli_run):
    """The setting is useless to an agent that never learns it exists.

    A flag on every call is the fallback; one export is the ergonomic path,
    and `--help` is the only place an agent reliably looks first.
    """
    result = cli_run(["--help"])
    assert result.exit_code == 0
    assert "FUNCTUALIZE_CLI_OUTPUT=json" in result.stdout


#: The epilog's line budget. Raised from 4 to 6 when the `--kind` filters were
#: added, which is what this cap is for: it makes each addition a decision
#: someone takes on purpose rather than one that lands by default. Raise it
#: again only after asking whether the new line earns a place on output that
#: prints on every mistyped command.
MAX_EPILOG_LINES = 6


def test_help_epilog_stays_short(cli_run):
    """`--help` prints on every mistyped command — it is not a manual."""
    result = cli_run(["--help"])
    epilog_lines = [
        line
        for line in result.stdout.splitlines()
        if "func builtin" in line or "FUNCTUALIZE_CLI_OUTPUT" in line
    ]
    assert len(epilog_lines) <= MAX_EPILOG_LINES, (
        f"the --help epilog has grown to {len(epilog_lines)} lines:\n"
        + "\n".join(epilog_lines)
    )


def test_help_epilog_has_a_heading(cli_run):
    """Unlabelled, the block reads as a continuation of the command list.

    The heading is what lets a human skim past it and an agent know to stop.
    """
    result = cli_run(["--help"])
    assert "For AI agents:" in result.stdout
    commands_at = result.stdout.index("Commands:")
    agents_at = result.stdout.index("For AI agents:")
    assert commands_at < agents_at, "the agent block must follow the command list"


def test_help_epilog_names_both_schema_filters(cli_run):
    """An agent should not have to guess that the surface can be narrowed."""
    result = cli_run(["--help"])
    assert "--kind job" in result.stdout
    assert "--kind builtin" in result.stdout


#: The epilog is emitted verbatim, never re-wrapped — wrapping a hand-aligned
#: table destroys the columns. That makes source width the only thing standing
#: between a narrow terminal and a mangled table, so it is pinned well inside
#: 80 rather than at it.
MAX_EPILOG_COLUMNS = 72


def test_help_epilog_lines_stay_narrow(cli_run):
    """A wrapped epilog is worse than a short one — it breaks the columns."""
    result = cli_run(["--help"])
    for line in _epilog_block(result.stdout):
        assert len(line) <= MAX_EPILOG_COLUMNS, (
            f"epilog line is {len(line)} columns (max {MAX_EPILOG_COLUMNS}), so a "
            f"narrow terminal will wrap the table: {line!r}"
        )


def test_help_epilog_heading_is_at_the_left_margin(cli_run):
    """`For AI agents:` must sit level with `Commands:`, not inside it.

    Click renders `epilog` inside `formatter.indentation()`, which put the
    heading two columns in — reading as another command rather than a new
    section. `_LeftMarginEpilogGroup` is what undoes that.
    """
    result = cli_run(["--help"])
    lines = result.stdout.splitlines()

    heading = next(line for line in lines if line.rstrip() == "For AI agents:")
    commands = next(line for line in lines if line.rstrip() == "Commands:")
    assert heading == heading.lstrip(), "the heading is indented"
    assert len(heading) - len(heading.lstrip()) == len(commands) - len(
        commands.lstrip()
    )


def test_help_epilog_entries_are_indented_under_their_heading(cli_run):
    """Two columns, matching how `builtin` sits under `Commands:`."""
    result = cli_run(["--help"])
    entries = [line for line in _epilog_block(result.stdout) if line.strip()]
    assert entries
    for line in entries:
        assert len(line) - len(line.lstrip()) == 2, f"unexpected indent: {line!r}"


def test_help_epilog_is_not_rewrapped_on_a_narrow_terminal(cli_run, monkeypatch):
    """The table must render identically however wide the terminal is.

    Click's own wrapping would reflow it into prose; this is the regression
    guard on rendering the epilog verbatim.
    """
    monkeypatch.setenv("COLUMNS", "60")
    narrow = _epilog_block(cli_run(["--help"]).stdout)
    monkeypatch.setenv("COLUMNS", "200")
    wide = _epilog_block(cli_run(["--help"]).stdout)
    assert narrow == wide


def test_json_flag_help_names_the_env_var(cli_run):
    """An agent reading `info --help` should find the default-it-once path."""
    result = cli_run(["builtin", "info", "--help"])
    assert result.exit_code == 0
    assert "FUNCTUALIZE_CLI_OUTPUT" in result.stdout


def test_info_subcommands_are_registered_in_the_builtin_registry():
    """The registry drives completions and the TUI — it must not drift."""
    from functualize._cli.builtins import BUILTIN_COMMANDS

    info = next(c for c in BUILTIN_COMMANDS if c.name == "info")
    assert {s for s, _ in info.subcommands} == {"jobs", "schema", "all"}
    assert not info.requires_subcommand, "bare `func builtin info` must stay valid"
