# Research: Standalone Distribution & Self-Management

**Feature**: `standalone-distribution`
**Date**: 2026-09-03
**Status**: Findings. **Never a gate** — nothing here is an acceptance criterion. Decisions
that flow from it live in `spec.md` and `contracts.md`.

Two investigations, both requested during the Specify phase:

1. [Output-flag consistency audit](#1--output-flag-consistency-audit)
2. [Testing and isolation strategy](#2--testing-and-isolation-strategy)

---

# 1 — Output-flag consistency audit

**Question**: are `--format json`, `--output json` and `--json` used consistently across
jobs, builtins and early-parse flags?

**Answer**: no. There are **four vocabularies**, the word "output" carries **three unrelated
meanings**, and the audit surfaced **two live defects** unrelated to this feature.

## 1.1 The complete inventory

Every output-shaping flag in `src/` and `plugins/`, verified 2026-09-03 at `39a0be2`.
`plugins/` declares none.

| Surface | Spelling | Type | Vocabulary | Means |
|---|---|---|---|---|
| Global, job path | `--output` | optional-value | `auto`, `json`, `ndjson`, `raw`, `none` | **Serialization** of what a job emits via `out.emit()` |
| Global | `--perf-report` | optional-value | `text`, `json` | Serialization of the perf report |
| `builtin workflow list` | `--format` | `click.Choice` | `table`, `json` | Table-or-JSON rendering |
| `builtin workflow state` | `--format` | `click.Choice` | `table`, `json` | Table-or-JSON rendering |
| `builtin why` | `--json` | bool flag | — | Rendering override |
| `builtin info` | `--json` | bool flag | — | Rendering override |
| `builtin info jobs` | `--json` | bool flag | — | Rendering override |
| `builtin info all` | `--json` | bool flag | — | Rendering override |
| `builtin parallel` | `--output` | `click.Choice` | `interleaved`, `grouped`, `prefixed` | **Layout** of concurrent job output |
| Config / env | `[cli] output`, `FUNCTUALIZE_CLI_OUTPUT` | setting | `rich`, `plain`, `json` | Default renderer |

Early-parse flags (`scan_early_setting_flags`) shape **settings**, not output, and no
shipped setting declares `phase="early"` today. **Not implicated.**

## 1.2 "Output" means three different things

- **Serialization** — global `--output`: how a job's emitted value is written
- **Layout** — `builtin parallel --output`: how concurrent streams are arranged
- **Renderer** — `[cli] output` / `FUNCTUALIZE_CLI_OUTPUT`: rich vs plain vs json

Three unrelated axes, one word. `builtin parallel --output grouped` and
`func --output json <job>` share a spelling and nothing else.

**Not all three are equally accidental.** Serialization and rendering are a *principled*
separation, documented and deliberate — see §1.3b. Layout reusing the same word is the
arbitrary one.

## 1.3 Rendering has two spellings with different vocabularies

Six commands answer the same question — "text or JSON?" — in two ways:

- **`--json`** (bool), on `why`, `info`, `info jobs`, `info all`. Resolves through
  `resolve_renderer(json_flag, cli_config)`, which honours the config/env default when the
  flag is absent — deliberately an *override*, not a mode.
- **`--format`** (choice of `table`/`json`), on `workflow list`, `workflow state`. Ignores
  the configured renderer entirely.

So `FUNCTUALIZE_CLI_OUTPUT=json func builtin info` emits JSON, while
`FUNCTUALIZE_CLI_OUTPUT=json func builtin workflow list` emits a table. Same intent, two
outcomes.

## 1.3b Why `info` did not reuse the global `--output` — it could not

The obvious question: `--output json` already existed, so why was `builtin info --json`
invented? Four answers, and together they say reusing `--output` would have been **wrong**,
not merely inconvenient.

**1. `--output` is not a rendering flag.** It is plumbed to exactly one consumer:

```
dispatch parses --output → app._output_format
    → _engine/capabilities/stdout.py:156  (the Stdout capability)
        → _primitives/stdout_emitter.py   (the §C.2 serialization engine)
```

It decides how `out.emit(value)` serializes **a job's emitted value**. A builtin has no
`Stdout` capability and never calls `out.emit()`, so `--output` would have had nothing to
act on. `docs/guides/composition.md:56` states the boundary from the job side: "`out.emit()`
honours `--output`; `print` does not."

**2. It is architecturally unreachable from a builtin.** `--output` is parsed in the dispatch
layer before click and is never declared on the click root group, which is why
`func builtin … --output json` is a hard usage error (defect A below). The builtin route
never receives the value.

**3. The distinction is documented.** `docs/cli/workflow.md:37-40`:

> `--format` is **domain-aware**: the command knows its items are workflow scopes, so `json`
> emits structured scope objects (id, workflow, status, position, pending gates) rather than
> a serialized log line. This is distinct from the global `--output`, which only formats the
> dispatch layer's return value.

**4. The chronology rules out oversight.** `--output` shipped in `dispatch.py` at v0.1.0
(`a7704fe`) for job emission. `--json` arrived later and separately: `builtin why` in #13
(`2af8a07`), then `info` plus `resolve_renderer` in #14 (`b6ea7f3`). By the time a builtin
needed JSON, `--output` already meant something else.

### What this does and does not justify

| Split | Verdict |
|---|---|
| `--output` vs a builtin's own JSON flag | **Justified and documented.** Different axes: serializing a job's emitted value is not the same act as rendering a diagnostic report. Preserve it |
| `--json` vs `--format` | **Not justified.** Same axis, same question, two spellings — and different behavior, since `--json` honours the configured renderer and `--format` ignores it. The workflow doc distinguishes `--format` from `--output`, never from `--json` |

So the inventory's real defect is narrower than "three vocabularies": **the
serialization/rendering boundary is principled, and only the `--json` / `--format` split
inside the rendering axis is accidental.** `builtin parallel --output` remains a genuine
reuse of the word for a third thing (layout), unrelated to both.

## 1.4 Live defect A — the global `--output` hard-errors on every builtin

`--output` is declared in the **dispatch layer** but not on click's root group, so it is
stripped before click on the job path and never learned on the builtin path.

```
$ func --log-level ERROR builtin version    → OK
$ func --log-level ERROR forecast           → OK
$ func --output json forecast               → OK
$ func --output json builtin version        → Error: No such option '--output'.
$ func --output json builtin workflow list  → Error: No such option '--output'.
```

`--log-level` works on both routes; `--output` works on one. A user cannot know which
globals are universal without trying them.

Arguably correct in intent — `--output` governs `out.emit()`, which builtins do not use — but
the failure mode is a hard usage error rather than an ignored flag or a targeted message.

**Out of scope for this feature.** Recorded because `contracts.md` §2 commits to exit-code
behavior on the builtin path, and this is the adjacent surface.

## 1.5 Live defect B — `--perf-report` misparses before a builtin

The dispatch layer treats `--perf-report` as **optional-value** (lookahead: if the next token
is not in `{text, json}`, assume `text`). Click's root group declares it as
`--perf-report TEXT` — **always** requiring a value. The two disagree:

```
$ func --perf-report builtin version        → Error: No such command 'version'.
$ func --perf-report=text builtin version   → works
$ func --perf-report text builtin version   → works
```

`builtin` is swallowed as the flag's value, leaving `version` as the command. The documented
bare form is the one that breaks, and only on the builtin route.

**Out of scope.** File separately.

## 1.6 Terminology collision — `builtin info` already prints "Mode:"

`builtin info` prints, under *Runtime State*:

```
Mode:       standalone (no .functualize/ found; create one to keep state in the project)
```

That is **state storage** mode, and `standalone` there means "no project directory". This
feature adds an install mode whose value is also `standalone` and means "the pre-baked
binary" — into the same command's output.

Two `Mode:` lines, both saying `standalone`, meaning unrelated things. The shape intent
flagged the `standalone` overload for `examples/standalone/`, `tests/standalone/` and
developer Mode D, but **not** this one, which is the most damaging because both strings land
in one screen.

**In scope.** Resolved in `spec.md` B6 and `contracts.md` §3: the new field is labelled
**`Install mode:`**, never `Mode:`, and its JSON key is nested under `install` rather than
sitting at the top level.

## 1.7 Convention adopted for this feature

Recorded in `contracts.md` §1. Chosen to add no new inconsistency while not expanding scope
into normalizing six existing commands.

| Situation | Spelling | Why |
|---|---|---|
| New commands (`self doctor`, `plugin list`) | `--format json` | The command-owned idiom, matching `workflow` — the closest analog and the only *choice*-typed precedent |
| Fields added to `builtin info` | ride the existing `--json` | Adding `--format` to a command that already ships `--json` creates two spellings **on one command**, which is worse than the existing cross-command split |
| Anything job-emitted | untouched | `--output` is a different axis; this feature emits no job values |

**This leaves the `--json` / `--format` split intact.** Normalizing it is a separate,
breaking change across `why`, `info`, `info jobs`, `info all`, `workflow list`, and
`workflow state` — see the open question in `spec.md`.

Per §1.3b, that normalization is the **only** part of the inventory that should collapse.
The global `--output` must stay separate from all six: it serializes a job's emitted value
and has no meaning for a builtin. Any future normalization that folds builtin rendering into
`--output` would be a regression, not a cleanup.

Written up as [`output-flag-normalization.md`](../../shape-intents/output-flag-normalization.md)
(2026-09-03) — including a measured matrix showing the split is **three** behaviors, not two:
`builtin why` declares `--json` but never calls `resolve_renderer`, so it ignores the
configured default just as `--format` does.

---

# 1.8 — Which functualize runs, and reaching the binary's environment

**Question**: with a standalone binary on `PATH`, working in a repo that declares functualize
as a dependency — does it work, and which functualize is used?

**Answer**: the one the user's `PATH` selects, which is already the right answer. There is no
dispatch defect. The real gap is narrower: **a deliberately-invoked standalone binary has no
supported way to gain the packages a project's jobs import.**

> **Corrected 2026-09-03 after maintainer review.** An earlier draft of this section framed
> "the project's declared functualize is ignored" as a defect and floated auto-bridging or
> delegation. That was wrong and the options are withdrawn — see *Why delegation is the wrong
> fix* below.

## What actually happens

A job is imported by whichever interpreter is running `func`, against that interpreter's
`site-packages`. Discovery inserts the **job module's own directory** into `sys.path`
(`_discovery/registry.py:234-235`, `providers.py:546-550`, `lazy_wrapper.py:70-71`) and
nothing else; there is no venv awareness anywhere in `src/` —
`grep -rn "site-packages\|site_packages\|VIRTUAL_ENV" src/functualize/` returns nothing
outside tests.

Demonstrated with a scratch project pinning `functualize==0.0.1-does-not-exist`:

```
functualize.__file__ = …/standalone-distribution/src/functualize/__init__.py   ← the runner's
sys.prefix           = …/standalone-distribution/.venv                          ← the runner's
project dep          = ImportError: No module named 'nonexistent_project_dep'
```

## Why this is correct, not broken

**`PATH` is the selection mechanism, and every normal project workflow already points it at
the project's functualize:**

| How the project is entered | What `func` resolves to |
|---|---|
| `uv run func …` | the project venv's functualize, with project deps |
| `mise` — this repo's own `mise.toml` sets `_.path = ["./.venv/bin"]` | the project venv's |
| an activated venv, or direnv | the project venv's |
| a deliberately-invoked binary (absolute path, or no project on `PATH`) | the binary's |

So a user working in a project gets the project's functualize *by default*, and only gets the
binary's by choosing it. The pinned version in `pyproject.toml` governs what `uv sync`
installs — it was never a dispatch instruction.

### Why delegation is the wrong fix

Re-execing into a detected project venv was considered and **rejected**:

- It would **override a deliberate choice.** Someone who typed the binary's path meant it.
- It breaks the feature's core principle. `func builtin self update` delegated into a project
  would run `uv lock --upgrade-package … && uv sync`, updating the *project* rather than the
  binary that was invoked.
- It cannot be unconditional. Today's shipped `BUILTIN_COMMANDS` is
  `['cache','state','config','domains','skills','scaffold','workflow','parallel','history','env','shell-init','why','version','info']`
  — **no `self`, no `plugin`.** A binary carrying this feature, delegating into a project
  pinned at 0.1.2, would answer `func builtin self doctor` with "no such command", for a
  command that exists in the thing the user invoked.

## The actual gap

A standalone binary is chosen precisely when there is no project environment — the no-Python
audience. Its bundled environment holds functualize plus the eleven first-party plugins (O2)
and **nothing else**. A job importing `requests` fails, and the user has no supported way to
fix that, because the binary's interpreter and its `uv` are internal implementation details
with no exposed handle.

`plugin install` (§4) already installs *into* that environment via bundled uv — but it is
scoped to plugins, records them in the manifest as plugins, and `plugin install requests`
would be a lie about what `requests` is.

### Direction (maintainer, 2026-09-03): expose the environment

Give the binary's environment a supported handle, rather than teaching functualize about
other environments. Two shapes, not mutually exclusive:

| Shape | Sketch | Notes |
|---|---|---|
| **Expose the tools** | `func builtin self python` / `func builtin self uv` print absolute paths | Composable and honest — `$(func builtin self uv) pip install requests`. Smallest surface. Nothing to keep in sync |
| **Passthrough** | `func builtin self exec -- <cmd …>` runs a command against the bundled environment | More discoverable, one command to document. Wraps rather than hands over |

Both keep the ownership principle intact: the binary owns its environment and is the only
thing that manages it. Neither reaches into a project.

**Open**: which shape (or both), whether anything installed this way is recorded in the
manifest, and whether `self update` — which rebuilds the managed environment and would
discard such packages — reconciles them the way it reconciles manifest-recorded plugins
(`PER.3`).

**Doctor's role shrinks** to an INFO line naming the running install mode, so a user who hits
an `ImportError` can see which environment they are in. It is no longer a warning about a
defect, because there is no defect — only a boundary.

---

# 1.9 — Cross-installation awareness: measured cost (2026-09-03)

**Question**: every `func` should be aware of other `func` installations — global and
per-project. What does that cost, can it be checked only when needed, and can an installation
record its signature only when it checks?

**Answer**: the cost is negligible *if the module stays off the warm path*. The file I/O is
free; **the expensive part is importing the module, and that is dominated by dataclass
codegen, not by disk**.

## Measurements

This machine, `.venv/bin/python` (CPython 3.13), medians:

| Operation | Cost | Relative to `func --version` |
|---|---|---|
| `func --version` end-to-end (the pre-boot path) | **474 ms** | baseline |
| `stat()` an existing file | **3.3 µs** | 0.0007 % |
| `stat()` a missing file | **4.8 µs** | 0.001 % |
| Read + `json.loads` a 10-installation manifest (3.7 KB) | **38.6 µs** | 0.008 % |
| Create **one** frozen dataclass | **921 µs** | 0.19 % |
| Import a small stdlib-only module defining a dataclass | **~1.0 ms** | 0.22 % |

## What this says

1. **Reading the whole registry is free.** 39 µs against 474 ms. The instinct to avoid the
   read is misdirected — that was never the cost.
2. **Importing `_cli/manifest.py` is the only measurable cost**, and roughly one millisecond
   of it is `@dataclass` codegen for the record types in `schema.md`. Three frozen dataclasses
   is ~2.8 ms before a single byte is read.
3. So the lever is **module import, not file access** — which is exactly what `AC9` already
   pins ("`functualize._cli.manifest` absent from `sys.modules` after a warm second
   invocation"). The measurement validates a constraint that was written on structural
   grounds, and gives it a number.

## The signature design this implies

A per-installation **marker file** whose *existence* is the signature:

| Path | Cost | Work |
|---|---|---|
| Warm — marker present | **one `stat()`, ~3 µs** | nothing imported, nothing parsed |
| Cold — marker absent | ~1–3 ms once | import the module, read the registry, append this installation, write the marker |

An installation therefore registers itself **once**, on its first run, and every subsequent
run pays a single `stat()`. No periodic re-scan, no write on a normal invocation.

## Global and per-project need one registry, not two

The manifest already lives at `resolve_user_config_dir() / "install.json"` — **user-global**,
honouring `XDG_CONFIG_HOME`. Every `func` that runs writes there regardless of where it came
from, and each record carries its own `binary_path`.

A project-local `.venv/bin/func` therefore registers itself with a `binary_path` inside the
project. **Per-project installations are already covered by the one shared file**; a second
per-project manifest would add a merge problem and answer no new question. A project-scoped
*view* is a filter over `binary_path`, not a second store.

## What this adds beyond the current spec

`B2` frames the manifest as "installations I have run from". The cross-awareness requirement
reframes it as **the registry of every `func` that has run on this machine**, which the same
file already is. Two things follow that the spec does not yet say:

- **Enumeration is a first-class use**, not a doctor implementation detail: any installation
  can list the others, with the current one marked.
- **Concurrent registration must be safe.** Two `func` processes starting together both append
  to one file. Writes must be atomic — write a temporary file and `rename()` — or a record is
  lost. `AC6` says append-only but does not say concurrency-safe, and append-only is exactly
  the property a lost update violates.

## Bounds of the claim

An installation is knowable from the registry only **after it has run at least once**. That
is not the whole story — some installations are *actively* discoverable without ever having
run, and cheaply. See §1.10, which measures it and corrects the blanket claim this paragraph
originally made about `PATH`.

Measurements are single-machine and indicative. `AC23`-style discipline applies: if a budget
is ever asserted on these, CI must measure it rather than quote this table.

---

# 1.10 — Registry only: no discovery (decided 2026-09-03)

**Decision**: `func` discovers nothing. The registry is a **pre-defined file, voluntarily
updated by any `func` that runs.** Reading it answers "what else is on this machine"; nothing
scans `PATH`, lists tool directories, walks the filesystem, or executes another binary.

The measurements below were taken while evaluating active discovery. They are kept because
they are the *reason* discovery is rejected, not merely the record of a road not taken.

## What discovery would have cost

| Operation | Cost |
|---|---|
| `sys.argv[0]` / `sys.executable` / `sys.prefix` | ~0 µs — in memory |
| `importlib.metadata.version("functualize")` | 1 420 µs |
| `shutil.which("func")` | 19.5 µs |
| Scan all `PATH` dirs (10 here) | 57.2 µs |
| List the uv tools dir (10 entries) | 44.3 µs |
| Read one foreign install's version from `dist-info` | ~650 µs |
| **Execute `func --version`** | **415 ms** |
| Walk `~/code` depth ≤ 3 / ≤ 4 | 29.1 ms / 53.5 ms |

Two of those are disqualifying on their own. Executing five installations to ask their
versions costs **2.1 s serial** — 440 % of the ~474 ms baseline, and it means running foreign
binaries to interrogate them, a posture nobody asked for. A filesystem walk has no honest
root: `~/code` at depth 4 is 53 ms and finds seven `pyproject.toml` files, while a real search
would have to consider `$HOME`.

The cheap tiers are genuinely cheap — a full `PATH` scan is 57 µs — but they buy the *wrong
thing*. They find installations that exist on disk. The registry answers a better question:
which installations have actually **run**.

## Why "has run" is the better predicate

A `func` that has never executed is not yet a fact about the system. It has produced no state,
no config, no jobs, no plugins. Recording it would inflate the registry with things that have
never mattered, and the case for finding it — "the user downloaded a binary and forgot" — is
answered the moment they run it, which is also the moment it starts mattering.

So the blind spot is not a gap to be closed. It is the definition working correctly.

## The mechanism

Every `func`, on running, ensures its own record is present. That is the entire protocol.

| Path | Cost | Work |
|---|---|---|
| Already registered | one `stat()`, ~3 µs | nothing imported, nothing parsed |
| Not yet registered | ~1–3 ms, once | import, read, append or refresh, write marker |
| Someone asks what exists | ~39 µs | read the registry |

## Consequences that must be specified, not assumed

Thinking the protocol through surfaces four things the current spec does not say.

### 1. The marker must be keyed by identity, not by path — a real defect

`schema.md` keyed the registration marker on `binary_path` alone. **An upgrade in place then
goes unnoticed**: `/usr/local/bin/func` at 0.1.2 registers and writes its marker; upgraded to
0.2.0 the marker still exists, the fast path short-circuits, and the registry keeps reporting
0.1.2 forever.

The key must cover everything the record asserts that can change — at minimum
`binary_path` **and** `functualize_version`. A version change then misses the marker, costs
one cold registration, and **refreshes** the existing record rather than appending a second.
The cost stays one `stat()` on the warm path.

### 2. Refresh, not only append

`AC6` says installations are never *removed*, which is right. But re-registration after an
upgrade must **replace that installation's record**, or one binary accumulates a record per
version it has ever been. `schema.md`'s `Manifest` already exposes `replace_record` alongside
`append`; the protocol has to say which one an upgrade takes.

### 3. Registration is voluntary, so failing to register is never an error

A read-only config directory, a container with no writable `XDG_CONFIG_HOME`, a sandbox — in
each, registration fails. It must degrade **silently**: no warning, no non-zero exit, no
retry loop. A registry that breaks `func` is worse than no registry. The invocation the user
typed is what matters; bookkeeping is not allowed to interfere with it.

### 4. A synced config directory imports foreign records

`~/.config` is commonly synced across machines by dotfiles repositories. Records written on
machine A then appear on machine B with `binary_path` values that do not resolve there.

This degrades correctly — doctor already reports an entry whose `binary_path` is missing as
stale (`AC7`) — but the *reason* shown would be misleading, since nothing is broken. Worth
either recording a machine identifier per record, or wording the stale message so it does not
assert a fault.

## What it does not need

- No `PATH` scan, no tool-directory listing, no filesystem walk, no subprocess.
- No background refresh, no daemon, no periodic re-scan.
- No per-project registry — one user-global file, with project installs recorded by their own
  `binary_path` (§1.9).

---

# 2 — Testing and isolation strategy

**Question**: how is a feature that installs software, writes to the user's home directory,
and ships a binary tested without damaging the developer's machine or being untestable?

**Answer**: four tiers, three of which already exist in this repository. Only the binary
tier is new.

## 2.1 What already exists

| Mechanism | Where | Isolation it provides |
|---|---|---|
| `cli_run` | `tests/conftest.py` | In-process `main()`, captured stdout/stderr, real routing. <100ms |
| `xdg_dirs` | `tests/conftest.py` | Temporary `config`/`data`/`cache`/`home`; `cli_run` depends on it |
| `_isolate_home` | `tests/conftest.py:170-187` | **Autouse.** Patches `Path.home()` and strips every `FUNCTUALIZE_*` and `XDG_*` variable |
| `project_tree` | `tests/conftest.py` | Factory for project dirs — jobs, plugins, pyproject, `.functualize.toml` |
| TUI Pilot | `tests/tui_audit/`, `tests/_cli/` | Drives the real Textual app |
| doc-verify scenarios | `examples/docs/scenarios/*.toml` | Per-step `engine = "shell" \| "docker" \| "pty"`, container images, read-only volume mounts |
| observe-tui Tier 3 | `.agents/skills/observe-tui/` | Ephemeral podman/docker recipes for install flows and destructive operations |
| evals | `evals/` | promptfoo + a container that is "a blast radius limiter for a *confused* agent" |

**Both `podman` and `docker` are on this host**, and doc-verify's runner is engine-selectable.

## 2.2 The isolation problem this feature creates

Three things ordinary tests must never do:

1. **Mutate the developer's real installation** — `plugin install` shells out to
   `uv tool install`, which would rewrite a real receipt.
2. **Write a real manifest** — `install.json` lands in the user config directory.
3. **Depend on how the test runner itself was installed** — `sys.prefix` cannot be set by
   environment, so a detection test that reads the live interpreter can only ever assert the
   one mode the suite happens to run under.

Problem 3 is why `spec.md` **AC4** requires detection to be decidable from supplied inputs.
That is a *testability* requirement driving a design constraint, and it is the single most
important line in this document.

Problems 1 and 2 are already solved: `_isolate_home` is autouse, and `xdg_dirs` redirects the
config directory. **Manifest tests need no new machinery** — but because `_isolate_home`
strips `FUNCTUALIZE_*`, every test pinning a mode must pass `FUNCTUALIZE_RUNTIME`
explicitly through `cli_run(env=…)`.

## 2.3 The four tiers

### Tier 1 — unit, no I/O

Detection and the receipt merge. Pure inputs, pure outputs, no filesystem, no subprocess.

Covers **AC1–AC4**, **AC26–AC27**. Every mode reachable because detection takes its inputs as
arguments.

### Tier 2 — CLI integration, in-process

`cli_run` + `xdg_dirs` + `project_tree`. The manifest, refusals, `info` fields, first-run
hint, warm-path structure.

Covers **AC5–AC18**, **AC20–AC21**, **AC30–AC33**.

**Mutating commands must not actually mutate.** They are exercised in refusal modes (which
execute nothing by definition — AC16) and in a print-only mode where the command is rendered
but not run. The confirmation prompt is the seam that makes this safe: AC18 requires the
command be printed *before* any side effect, so asserting on that string needs no
subprocess.

**AC9** — "the manifest machinery is not loaded on a warm path" — is asserted
**structurally** (`functualize._cli.manifest` absent from `sys.modules`), not by timing.
There is no pre-boot wall-clock budget: the perf budgets cover `FunctualizeApp.__init__`
only, and are skipped under coverage and xdist by `tests/conftest.py:129-148`.

### Tier 3 — TUI Pilot

Covers **AC19** (plugin command hands over the terminal) and **AC28** (`skills install` does
the same).

**AC28 is worth writing before P2 is fixed** — it fails, demonstrating the defect, then
passes. That is the sabotage discipline `.spec/CONSTITUTION.md` asks for, obtained for free.

### Tier 4 — container, out of pytest

Real installations in disposable containers, following `b-install-flows.toml`, which already
tests documented install commands with `engine = "docker"` and read-only source mounts.

Covers **AC17** (uv receipt preservation), **AC22** (offline launch), and the real
`plugin install` path — none of which can run in-process.

**These are doc-verify scenarios, not pytest tests.** doc-verify's rule is explicit: scenario
files live in `examples/docs/` and are never imported by the suite. They run on demand, like
`evals/`.

Proposed additions:

| Scenario | Steps |
|---|---|
| extend `b-install-flows.toml` | a `uv tool install` step asserting the detected mode is `tool_uv`, and a `pipx install` step for `tool_pipx` — **which also settles the one signal the shape intent still marks UNVERIFIED**, since no pipx was available on the audit host |
| new `k-plugin-lifecycle.toml` | in one container: install plugin A, install plugin B, assert **A is still present** (AC17) |
| new `l-standalone-binary.toml` | run the built binary with **networking disabled** (`--network none`), execute a job, assert success (AC22); and assert its measured size (AC23) |

`--network none` is what turns AC22 from a claim into a gate. It is the only way to test the
property recipe B was chosen for.

## 2.4 What is deliberately not tested automatically

| Not tested | Why | Instead |
|---|---|---|
| Real `self update` against a live install | It would upgrade the developer's functualize | Container scenario, or refusal-mode assertions only |
| Homebrew formula | Needs macOS and a tap | Manual, at release |
| `npx skills add` interactive prompts | Third-party, network, interactive | AC29 asserts the terminal path is *unchanged*, which needs no prompt simulation |
| Binary size as a fixed number | Drifts every release | AC23 asserts CI **measures and reports**; a threshold is a release decision |

## 2.5 Where each acceptance criterion lands

| Tier | Criteria |
|---|---|
| 1 — unit | AC1, AC2, AC3, AC4, AC26, AC27 |
| 2 — CLI integration | AC5–AC16, AC18, AC20, AC21, AC30, AC31, AC32, AC33 |
| 3 — TUI Pilot | AC19, AC28 |
| 4 — container scenario | AC17, AC22, AC29 |
| CI configuration | AC23, AC24, AC25 |
| Review-only | AC12 (a check that can only succeed is a design property, not a runtime assertion) |

**AC12 has no automated form.** "No check can only ever report success" is verified by
reading doctor's check list against what each check can observe. Recorded here so the Plan
phase does not invent a fake assertion for it.
