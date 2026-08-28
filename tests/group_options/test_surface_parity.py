"""Every surface must agree on what a field *is* (S6a/S6b leak detector).

**Five** leaks of one shape shipped during this feature, each invisible to a
green test suite:

1. a group's options vanished entirely (a pre-filter hid ``_group.py`` from the
   scan, so the cache section was empty);
2. a group's options leaked *into* the job's own CLI flags (six detection sites
   mistook a ``GroupOptions`` parameter for the job's config class);
3. the injection parameter itself (``opts: DeployOptions``) leaked into the MCP
   tool schema as a settable ``string`` argument;
4. …and into the TUI pre-flight field table, as a row inviting a value;
5. …and into the SmartBar completion dropdown, offered as ``--opts``.

Every one was a **cross-surface disagreement**, and every surface's own unit
tests passed — because each was internally consistent while disagreeing with
the others. A test that drives one surface cannot catch this by construction.

Leaks 4 and 5 are the sharper lesson: this harness already existed and still
missed them, because it probed the *resolvers* and not what those surfaces
**render**. A surface a user or agent can read a field name from is a surface
that can file it under the wrong kind — so the rule is now explicit: **when a
new settable surface appears, it gets a probe here, or it will leak.**

This module drives all five over one fixture and asserts they partition every
field into the same three kinds.

**The model.** A field a job could be handed is exactly one of:

- **job argument** — the job's own parameter (``image``). Settable at
  ``func … run --image``; present in the MCP schema; injected from call kwargs.
- **group option** — declared by a group on the job's path (``env``,
  ``dry_run``). Settable *mid-path* (``func deploy --env prod … run``); present
  in the group listing and the MCP schema; injected as a resolved instance.
- **injection point** — the ``GroupOptions`` parameter that receives the
  resolved instance (``opts``). Settable **nowhere** — it is an outlet, not an
  input. Absent from every settable surface.

A leak is any surface that files a field under the wrong kind. Each invariant
below is written against the *declaration*, not a hand-maintained list, so a
new field or a new group needs no edit here — only a real regression fails.

The surfaces are driven for real (``cli_run`` runs ``main()`` in-process; the
MCP translator reads the same cache the CLI does; the engine actually
executes), because all three leaks were caught by running the surface and none
by a unit probe of it. A mocked surface would re-introduce exactly the blind
spot this module exists to close.

A **sixth** surface was added with T44: the static shell-completion word lists
(`func builtin shell-init`). It is a settable surface — the leaf list is what a
user TABs through — so it partitions like the rest, with one difference noted at
`_shell_init_settable`: a shell does not distinguish *kind* at the leaf, so its
contract is the union (job arguments + inherited group options), never an
injection point.

**The interactive prompt (T45) is deliberately not a probe here.** It is
a place a value can be *supplied*, but not a place a field's **kind** is
rendered — it asks about a config-model field by name and never sees the
injection parameter, which is a job-signature parameter and not in
``model_fields``. What it could still get wrong is the adjacent question,
"does this field get asked for?", answered differently for a job-config field
than for a group option — the same cross-surface disagreement in a different
dress. That is pinned directly instead, by
``tests/group_options/test_group_options_missing_prompt.py`` (which asserts the
question is scoped to the *group path*) against
``tests/config/test_missing_config_prompt.py``; both go through one seam,
``JobExecutionEngine._resolve_with_prompt``. Adding a probe here would mean
giving this fixture a required field, which changes what all five existing
surfaces see — a real regression risk for no coverage the pair above lacks.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ── The one fixture, containing all three kinds of field ────────────────────

_GROUP_MODULE = '''\
from typing import Annotated

from functualize.job import GroupOptions, Option


class DeployOptions(GroupOptions, group="deploy"):
    """Deploy-level flags."""

    env: Annotated[str, Option("-e", help="Target environment")] = "staging"
    dry_run: Annotated[bool, Option(help="Preview only")] = False


class WebOptions(GroupOptions, group="deploy.web"):
    """Web-tier flags (a nested group, to prove inheritance is surfaced)."""

    replicas: int = 1
'''

_WEB_JOB = '''\
from _group import DeployOptions, WebOptions

JOB_GROUP = "deploy.web"


def run(
    image: str = "nginx",
    opts: DeployOptions = None,
    web: WebOptions = None,
) -> str:
    """Deploy the web tier."""
    result = f"{image}/{opts.env}/{opts.dry_run}/{web.replicas}"
    print(result)  # the CLI echoes stdout, not the return value
    return result
'''

# The declaration, named once. Every assertion references these, so the fixture
# is the single source of truth and the tests need no parallel bookkeeping.
JOB_PATH = ["deploy", "web", "run"]
JOB_ARGUMENTS = {"image"}
GROUP_OPTIONS = {"env", "dry_run", "replicas"}  # deploy's two + web's one
INJECTION_PARAMS = {"opts", "web"}  # the GroupOptions parameters themselves


@pytest.fixture(autouse=True)
def _evict_stale_job_modules() -> None:
    """Start each test with no stale ``_group``/``web`` in ``sys.modules``.

    A leak detector must give the same verdict regardless of what ran before
    it. The fixture's job files import as those generic top-level names, and
    another suite that imported identically-named files leaves entries behind
    that would shadow this fixture's — making discovery silently find nothing
    and the detector silently pass. `clean_sys_modules` only stops *this*
    module from polluting others (it snapshots at test start, so anything
    already stale is in the snapshot); eviction *before* boot is what defends
    against prior pollution.
    """
    for name in ("_group", "web"):
        sys.modules.pop(name, None)


@pytest.fixture()
def project(project_tree) -> Path:
    return project_tree(jobs={"_group.py": _GROUP_MODULE, "web.py": _WEB_JOB})


# ── Per-surface probes: "what does surface S say is settable, and as what?" ──


def _job_help_flags(cli_run, project: Path) -> set[str]:
    """The job's own settable options, as its ``--help`` advertises them."""
    result = cli_run([*JOB_PATH, "--help"], cwd=project)
    assert result.exit_code == 0, result.stderr
    flags: set[str] = set()
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped.startswith("--"):
            continue
        # "--image TEXT" -> "image"; strip a leading -- and any metavar. `--help`
        # is click's own, on every command, and not a field of this job.
        name = stripped.split()[0].lstrip("-").replace("-", "_")
        if name != "help":
            flags.add(name)
    return flags


def _group_listing_options(cli_run, project: Path, path: list[str]) -> set[str]:
    """The options a group listing documents at ``path`` (inherited included)."""
    result = cli_run(path, cwd=project)
    assert result.exit_code == 0, result.stderr
    options: set[str] = set()
    in_options = False
    for line in result.stdout.splitlines():
        if line.rstrip().endswith("Options:"):
            in_options = True
            continue
        if in_options:
            if not line.strip():
                break
            token = line.strip().split()[0].rstrip(",")
            if token.startswith("--"):
                options.add(token.lstrip("-").replace("-", "_"))
    return options


def _tui_settable(project: Path, monkeypatch) -> tuple[set[str], set[str]]:
    """What the TUI treats as settable, split into (job args, group options).

    The fourth surface (S6b). Drives the real space-separated walk every TUI
    execution and preview site calls — ``FunctualizeInlineTUI.resolve_command``
    — and reports the partition it produced. Group flags are typed *mid-path*
    (each after the group that declares it), job flags after the command, which
    is the CLI's own shape.
    """
    from functualize._cli.tui.app import FunctualizeInlineTUI
    from functualize.app.config import JobSources
    from functualize.app.core import FunctualizeApp

    monkeypatch.chdir(project)
    jobs_dir = project / ".functualize" / "jobs"
    func_app = FunctualizeApp(
        name="parity-tui", job_sources=JobSources(directories=[str(jobs_dir)])
    )
    func_app.get_jobs()  # warm the cache the trie reads
    tui = FunctualizeInlineTUI(func_app)

    # `env`/`dry_run` belong to `deploy`; `replicas` to `deploy.web`. Each is
    # typed after the group that declares it — that is what mid-path means.
    argv = [
        "deploy",
        "--env",
        "x",
        "--dry-run",
        "web",
        "--replicas",
        "3",
        "run",
        "--image",
        "x",
    ]
    resolution = tui.resolve_command(argv)
    assert resolution.job_name is not None, f"path did not resolve: {resolution.args}"
    job_kwargs = tui.job_kwargs_for(resolution.job_name, resolution.args)
    return set(job_kwargs), set(resolution.group_values)


def _tui_render_settable(project: Path, monkeypatch) -> tuple[set[str], set[str]]:
    """What the TUI *renders*, split into (job args, group options).

    The **seventh** surface, and the one the harness's own history argued for:
    ``_tui_settable`` above drives the resolver, and leaks 4 and 5 got past a
    resolver probe because a field's kind is decided again on the way to the
    screen. A row a user reads a field name from is a row that can be filed
    under the wrong kind — the config table and the pre-flight both build their
    rows from a `FieldDef`, and ``group_path`` is where the kind is recorded.

    An injection parameter must appear in neither set: it is an outlet, not an
    input, and a row inviting a value for `opts` was leak 4 verbatim.
    """
    from functualize._cli.tui.app import FunctualizeInlineTUI
    from functualize._cli.tui.chain_resolution import (
        _build_group_field_defs,
        build_command_panels,
    )
    from functualize.app.config import JobSources
    from functualize.app.core import FunctualizeApp

    monkeypatch.chdir(project)
    jobs_dir = project / ".functualize" / "jobs"
    func_app = FunctualizeApp(
        name="parity-tui-render", job_sources=JobSources(directories=[str(jobs_dir)])
    )
    func_app.get_jobs()
    tui = FunctualizeInlineTUI(func_app)

    job_name = ".".join(JOB_PATH)
    group_rows = _build_group_field_defs(tui, job_name, {})
    job_rows = [
        f.name
        for f in tui._get_job_fields(job_name)
        if f.name not in {"rc", "run_context", "log"}
    ]

    # The assembled panel is checked for ordering separately (D-1); here only
    # the partition matters, so the two halves are read from the same builders
    # the panel uses rather than from a mounted widget.
    assert build_command_panels is not None
    return set(job_rows), {f.name for f in group_rows}


def _completion_settable(project: Path, monkeypatch) -> tuple[set[str], set[str]]:
    """What the SmartBar *offers*, split into (job flags, group flags).

    The **fifth** surface, and the one that proved the harness had a hole: the
    injection parameter leaked into the completion dropdown as ``--opts`` while
    every other surface already excluded it, and nothing here noticed because
    the harness only probed the resolver, never what the dropdown renders.

    A surface a user can *type from* is a surface that can file a field under
    the wrong kind, so it belongs in the parity model like the rest.
    """
    from functualize._cli.completions.provenance import (
        CompletionProvenanceClassifier,
    )
    from functualize._cli.tui.smart_bar_autocomplete import SmartBarAutoComplete
    from functualize.app.config import JobSources
    from functualize.app.core import FunctualizeApp

    monkeypatch.chdir(project)
    jobs_dir = project / ".functualize" / "jobs"
    app = FunctualizeApp(
        name="parity-completion", job_sources=JobSources(directories=[str(jobs_dir)])
    )
    app.get_jobs()  # warm the cache the trie reads
    autocomplete = SmartBarAutoComplete(app, CompletionProvenanceClassifier(app))

    def _flags(text: str) -> set[str]:
        names: set[str] = set()
        for item in autocomplete._command_mode_candidates(text, len(text)):
            main = (
                item.get("main", "")
                if isinstance(item, dict)
                else getattr(item, "main", "")
            )
            token = str(main).split()[0] if str(main).split() else ""
            if token.startswith("--"):
                names.add(token.lstrip("-").replace("-", "_"))
        return names

    # Job flags are offered after the command; group flags mid-path, each after
    # the group that declares it (`replicas` belongs to `deploy.web`).
    job_flags = _flags("deploy web run --")
    group_flags = _flags("deploy --") | _flags("deploy web --")
    return job_flags, group_flags


def _shell_init_settable(project: Path, monkeypatch) -> set[str]:
    """The flags the **shell completion script** offers at the leaf job (T44).

    The *sixth* surface. `func builtin shell-init` bakes a static word list per
    command path; at the leaf that list is what a user TABs through, so it is a
    settable surface and it partitions like the rest — except that a shell
    completion does not distinguish *kind* at the leaf (you do not type a group
    flag in a different place from a job flag once you are at the job). So this
    surface's contract is the **union**: it offers exactly the settable fields
    (job arguments + inherited group options) and never an injection point.

    Extracted through the same `extract_completion_data` the command uses, so a
    drift here is a real drift, not a test artifact.
    """
    from functualize._cli.completions.data import extract_completion_data
    from functualize.app.config import JobSources
    from functualize.app.core import FunctualizeApp

    monkeypatch.chdir(project)
    jobs_dir = project / ".functualize" / "jobs"
    app = FunctualizeApp(
        name="parity-shellinit", job_sources=JobSources(directories=[str(jobs_dir)])
    )
    app.get_jobs()
    data = extract_completion_data(app)

    leaf = " ".join(JOB_PATH)
    names: set[str] = set()
    for flag in data.command_tree.get(leaf, []):
        if flag.startswith("--"):  # long form only, like the other probes
            names.add(flag.lstrip("-").replace("-", "_"))
    return names


def _mcp_tool(cli_run, project: Path) -> dict:
    """The job's MCP tool definition, as ``func mcp schema`` emits it.

    Driven through the real command rather than a hand-built translator: this
    is the exact JSON an agent receives, and leak 3 lived precisely in the gap
    between a translator built in a test and the one the command constructs. A
    ``pytest.importorskip`` keeps the module green where the plugin is absent.
    """
    import json

    pytest.importorskip("functualize_mcp")
    result = cli_run(["mcp", "schema"], cwd=project)
    assert result.exit_code == 0, result.stderr
    tools = json.loads(result.stdout)
    matching = [t for t in tools if t["name"] == ".".join(JOB_PATH)]
    assert matching, f"job not in schema: {[t['name'] for t in tools]}"
    return matching[0]


# ── The invariants ──────────────────────────────────────────────────────────


class TestSurfaceParity:
    """One project, every surface, asserted against the declaration."""

    def test_job_help_shows_exactly_the_job_arguments(self, cli_run, project) -> None:
        """Leaks 2 and 3, from the CLI side: a group option or an injection
        parameter appearing here is the six-site defect returning."""
        flags = _job_help_flags(cli_run, project)

        assert flags == JOB_ARGUMENTS
        assert not (flags & GROUP_OPTIONS), "a group option leaked into job --help"
        assert not (flags & INJECTION_PARAMS), "an injection param leaked into --help"

    def test_the_group_listing_shows_its_own_options(self, cli_run, project) -> None:
        """Leak 1, from the CLI side: the group's options must be *reachable*,
        not silently absent because the declaration was never scanned."""
        options = _group_listing_options(cli_run, project, ["deploy"])

        assert options == {"env", "dry_run"}

    def test_a_nested_listing_shows_inherited_options(self, cli_run, project) -> None:
        options = _group_listing_options(cli_run, project, ["deploy", "web"])

        assert options == {"env", "dry_run", "replicas"}

    def test_the_tui_renders_the_same_partition_it_resolves(
        self, project, monkeypatch
    ) -> None:
        """The seventh surface. A resolver probe cannot catch a kind decided
        again on the way to the screen — which is exactly how leaks 4 and 5
        got past this file the first time."""
        job_args, group_options = _tui_render_settable(project, monkeypatch)

        assert job_args == JOB_ARGUMENTS
        assert group_options == GROUP_OPTIONS

    def test_no_injection_parameter_is_ever_rendered(
        self, project, monkeypatch
    ) -> None:
        """Leak 4, stated against the renderer rather than the resolver."""
        job_args, group_options = _tui_render_settable(project, monkeypatch)

        assert not ((job_args | group_options) & INJECTION_PARAMS)

    def test_the_rendered_halves_are_disjoint(self, project, monkeypatch) -> None:
        """A field is one kind or the other, never both. A group option
        appearing in the job's rows would put it under the job's own flags,
        where the CLI does not accept it."""
        job_args, group_options = _tui_render_settable(project, monkeypatch)

        assert job_args.isdisjoint(group_options)

    def test_no_group_option_is_ever_a_job_flag(self, cli_run, project) -> None:
        """The invariant behind leak 2, stated directly: the job-argument set
        and the group-option set are disjoint on every CLI surface."""
        job_flags = _job_help_flags(cli_run, project)
        listing = _group_listing_options(cli_run, project, ["deploy", "web"])

        assert job_flags.isdisjoint(listing)

    def test_mcp_schema_is_job_arguments_plus_group_options(
        self, cli_run, project
    ) -> None:
        """Leak 3, and the positive half of leak 1: the schema must carry every
        settable field and *only* settable fields."""
        tool = _mcp_tool(cli_run, project)
        properties = set(tool["inputSchema"]["properties"])

        assert properties == JOB_ARGUMENTS | GROUP_OPTIONS

    def test_mcp_never_exposes_the_injection_parameter(self, cli_run, project) -> None:
        """Leak 3 exactly: ``opts``/``web`` are outlets, not arguments. Exposed,
        an agent would try to fill a bare ``string`` for the whole model."""
        tool = _mcp_tool(cli_run, project)
        properties = set(tool["inputSchema"]["properties"])

        assert properties.isdisjoint(INJECTION_PARAMS)

    def test_the_cli_and_mcp_agree_on_the_settable_set(self, cli_run, project) -> None:
        """The cross-surface invariant in one assertion: the union of what the
        CLI lets a user set (job flags + mid-path group options) equals what
        MCP advertises. Two surfaces drifting apart is the whole failure class,
        so it gets a test that names both at once."""
        cli_settable = _job_help_flags(cli_run, project) | _group_listing_options(
            cli_run, project, ["deploy", "web"]
        )
        tool = _mcp_tool(cli_run, project)
        mcp_settable = set(tool["inputSchema"]["properties"])

        assert cli_settable == mcp_settable

    def test_the_engine_injects_by_kind_not_by_leak(self, cli_run, project) -> None:
        """The runtime end of the same partition: the job argument comes from
        the call, each group option from its resolved instance, and the run
        succeeds — proving the three kinds are wired to three different
        sources, not conflated."""
        result = cli_run(
            ["deploy", "--env", "prod", "--dry-run", "web", "run", "--image", "custom"],
            cwd=project,
        )

        assert result.exit_code == 0, result.stderr
        # image=custom (job arg), env=prod + dry_run=True (deploy options),
        # replicas=1 (web option default) — every kind delivered, none crossed.
        assert "custom/prod/True/1" in result.stdout

    # ── The fourth surface: the TUI (S6b) ────────────────────────────────────

    def test_the_tui_files_job_arguments_as_job_arguments(
        self, project, monkeypatch
    ) -> None:
        """The TUI's post-name split must land the job's own flag with the job,
        not misfile it as a group option."""
        job_args, _group = _tui_settable(project, monkeypatch)

        assert job_args == JOB_ARGUMENTS

    def test_the_tui_files_group_options_as_group_options(
        self, project, monkeypatch
    ) -> None:
        """And the inherited group flags as group options — the routing that
        makes ``deploy.web.run --env prod`` set the group value rather than
        error as an unknown job flag."""
        _job_args, group = _tui_settable(project, monkeypatch)

        assert group == GROUP_OPTIONS

    def test_the_tui_never_files_the_injection_parameter(
        self, project, monkeypatch
    ) -> None:
        """``opts``/``web`` are outlets, settable on no surface — the TUI must
        not accept them as either kind."""
        job_args, group = _tui_settable(project, monkeypatch)

        assert (job_args | group).isdisjoint(INJECTION_PARAMS)

    def test_the_tui_and_cli_agree_on_the_settable_partition(
        self, cli_run, project, monkeypatch
    ) -> None:
        """The cross-surface invariant, TUI edition: what the TUI lets a user
        set, split by kind, equals what the CLI does. A fourth surface drifting
        is the exact failure the first three leaks were."""
        tui_job, tui_group = _tui_settable(project, monkeypatch)
        cli_job = _job_help_flags(cli_run, project)
        cli_group = _group_listing_options(cli_run, project, ["deploy", "web"])

        assert tui_job == cli_job
        assert tui_group == cli_group

    # ── The fifth surface: SmartBar completion (S6b T-S6b-2) ─────────────────

    def test_completion_offers_exactly_the_jobs_flags_after_the_command(
        self, project, monkeypatch
    ) -> None:
        """Position is the scope delimiter on every surface, completion too."""
        job_flags, _group = _completion_settable(project, monkeypatch)

        assert job_flags == JOB_ARGUMENTS

    def test_completion_offers_the_inherited_group_flags_mid_path(
        self, project, monkeypatch
    ) -> None:
        _job, group_flags = _completion_settable(project, monkeypatch)

        assert group_flags == GROUP_OPTIONS

    def test_completion_never_offers_the_injection_parameter(
        self, project, monkeypatch
    ) -> None:
        """The leak that motivated adding this probe: `--opts` was offered as a
        job flag, inviting the user to type a model into a flag."""
        job_flags, group_flags = _completion_settable(project, monkeypatch)

        assert (job_flags | group_flags).isdisjoint(INJECTION_PARAMS)

    def test_completion_agrees_with_the_cli_on_the_settable_partition(
        self, cli_run, project, monkeypatch
    ) -> None:
        """The whole point of the harness, now spanning five surfaces: what a
        user can type in the shell equals what they can type on the command
        line, filed under the same kinds."""
        comp_job, comp_group = _completion_settable(project, monkeypatch)
        cli_job = _job_help_flags(cli_run, project)
        cli_group = _group_listing_options(cli_run, project, ["deploy", "web"])

        assert comp_job == cli_job
        assert comp_group == cli_group

    # ── The sixth surface: shell completion data (T44) ───────────────────────

    def test_shell_init_offers_exactly_the_settable_fields(
        self, project, monkeypatch
    ) -> None:
        """The static shell script offers the union of settable fields at the
        leaf — job arguments plus inherited group options — and nothing else."""
        settable = _shell_init_settable(project, monkeypatch)

        assert settable == JOB_ARGUMENTS | GROUP_OPTIONS

    def test_shell_init_never_offers_the_injection_parameter(
        self, project, monkeypatch
    ) -> None:
        """The sixth chance to leak `opts`/`web`, closed: a static completion
        that baked the injection point in would ship the leak to every shell."""
        settable = _shell_init_settable(project, monkeypatch)

        assert settable.isdisjoint(INJECTION_PARAMS)

    def test_shell_init_agrees_with_the_cli_on_the_settable_set(
        self, cli_run, project, monkeypatch
    ) -> None:
        """Sixth surface, same invariant: what a user can TAB-complete at the
        leaf equals what the CLI lets them set there (job flags + inherited
        group options), as one set."""
        settable = _shell_init_settable(project, monkeypatch)
        cli_settable = _job_help_flags(cli_run, project) | _group_listing_options(
            cli_run, project, ["deploy", "web"]
        )

        assert settable == cli_settable
