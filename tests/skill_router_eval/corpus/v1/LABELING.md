# Labelling rubric — corpus v1

Every scenario in `scenarios.jsonl` is labelled by hand with one of the five
options the router actually has. This file is the rule that label follows, and
it is written before the corpus is drafted: a rubric fitted to the scenarios
would agree with them by construction.

Two rules govern the whole file:

- **No model labels the corpus.** Not a comparator, not a frontier model, not
  the router being measured. A label produced by the thing under test measures
  the test.
- **Only the request is read.** A label is decided from `state` alone — never
  from a tool's output, a downstream task prompt, or what a first attempt
  happened to produce.

The five clauses §1–§5 quote each option's catalog meaning verbatim: they are
what the router is shown, so they are what a label must agree with. §6 resolves
a request two clauses could claim, and §7 says which requests are not labelled
at all.


## §1 functualize

> Write, run, and debug functualize jobs — job functions, RunContext capabilities (Log, Invoke, Prompt, State, Stdout, Shell, Live), layered config, secrets, and discovery rules. Use when editing jobs.py or any file defining functualize jobs, when a job is not being discovered, when wiring job config or credentials, when listing or inspecting the jobs an app exposes — a machine-readable catalogue of every job and the arguments it takes, as JSON Schema — or when the user mentions functualize, `func run`, `func builtin`, `builtin info`, RunContext, or @job. Not for installing, upgrading, or configuring the `func` tool itself — use functualize-cli.

**Label `functualize` when** the request is Editing jobs, configuring them, debugging why one does not run, reading the
RunContext capabilities a job may use, or asking what jobs an app exposes.

## §2 functualize-app

> Build a CLI or TUI program on functualize, end to end — decide between a single-file script and a scaffolded project, author jobs, configure the FunctualizeApp (job sources, discovery filters, config presets), write tests that actually catch regressions, and verify the program renders and runs. Use when starting a new functualize project, command-line tool, or standalone script, when adding a significant feature to one, when configuring or restructuring an existing functualize app, when asked to make one "production ready" or well tested, or when packaging a functualize CLI for distribution.

**Label `functualize-app` when** the request is Starting or reshaping a whole program: the file-or-scaffold decision, the app
configuration, its tests, and whether what it builds actually runs.

## §3 functualize-cli

> Install, upgrade, inspect and configure the `func` command-line tool itself — which environment it lives in, the XDG config and data directories, settings precedence, the interactive TUI, the discovery cache and runtime state store, shell completions, and where the bundled AI agent skills are installed from. Use when `func: command not found`, when `func` is not on PATH or you are unsure which environment it lives in, when the wrong version runs, when installing or upgrading functualize, when configuring `func` or its TUI, when clearing or inspecting the cache or state, when wiring shell completions, or when asked where functualize keeps its files. Not for inspecting or authoring the jobs in a project — that is the functualize skill.

**Label `functualize-cli` when** the request is The `func` tool itself: installing it, finding it, its version, its config and
data directories, its cache and state, and shell completion.

## §4 functualize-skill

> Author an agent skill whose bundled scripts are functualize jobs — giving the skill self-contained dependencies, a discoverable --help, structured output, secret masking, and testable scripts. Also covers deciding where a skill should live and how to distribute it: personal, committed to a team repo, published via the skills CLI, or packaged as a Claude Code plugin marketplace. Use when writing a SKILL.md, when a skill needs scripts that do real work, or when asked how to share or publish a skill.

**Label `functualize-skill` when** the request is Authoring an agent skill — its `SKILL.md`, its frontmatter, or a bundled script
that does real work.

## §5 none

> No functualize skill applies; answer without loading one.

**Label `none` when** the request is A request functualize does not bear on: an unrelated library, a general
programming question, or work no skill here would change.

## §6 tie-breaks

A request can name two options. Resolve it in this order, and record the choice
in `rationale`:

1. **Tool installation, `PATH`, config directories, shell completion** ⇒
   `functualize-cli`. The `func` tool is not installed, not found, the wrong
   version, or its files are somewhere unexpected — no skill body is needed to
   answer that, and the CLI skill is the one that says where things live.
2. **Writing or debugging jobs** ⇒ `functualize`. A job function, its config,
   its credential, its discovery, the RunContext it is handed.
3. **Building a whole program** ⇒ `functualize-app`. The request is about the
   program the jobs make up: its structure, its tests, packaging, "production
   ready", or whether the CLI renders.
4. **Authoring an agent skill** ⇒ `functualize-skill`. The artifact is a skill —
   frontmatter, a `SKILL.md` body, a script bundled inside one — not a
   functualize program.
5. **A request functualize does not bear on** ⇒ `none`. Nothing here would change
   the answer; loading a body would only cost context.

Ties between §1 and §2 break toward `functualize-app` when the request names no
concrete job and toward `functualize` when it names one. Ties between §3 and
everything else break toward `functualize-cli` only when the subject is the tool
itself; a job that fails because the tool is missing is a §1 request that
mentions §3, and stays `functualize`.

## §7 two-skill requests

A request that plainly needs two skills is **not labelled**. There is no
`both` option and no multi-label corpus: the router answers with one skill or
none, so a request whose honest answer is two of them measures the question, not
the router.

Such requests are not discarded — they are the interesting failure mode, and
they are listed in `TWO_SKILL.md` with the two skills they need. They never
enter `scenarios.jsonl`, and no clause in this file may be read to squeeze one
of them into a single label.
