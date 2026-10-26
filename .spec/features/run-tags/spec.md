# run-tags — Specification

A run record answers *what* ran, *where* and *when*. It cannot answer *who asked
for it*. Run tags are the caller's own label — `harness:claude`,
`session-id:7f3a`, `ticket:MCH-202` — read from the caller's command line, the
caller's environment and the caller's user config file, fixed when the run
opens, copied to every child run, and queryable with
`func builtin run list --tag KEY:VALUE`.

Shape: *Shape Intent — Run Tags (how a caller labels the runs it starts, where
the label lives, how it is found)*, Confluence `SD/18972686` **v3** (updated
2026-10-26 11:57:10 UTC), `Status = Approved`, `Authority = Approved`. The
maintainer approved revision 2 on 2026-10-26 with "Ok follow your
recommendations. Approved" (comment `01a15396`), and the v3 header flip to
`Approved` followed at 11:57:24Z (comment `01a17812-8ebb-7108-b56e-eccf463b98e2`)
after OQ-6 was resolved as `(b′)` — a global-config layer, no project-file
layer. This spec builds v3 and no earlier revision. See `plan.md` →
`## Alignment`.

## 1. Problem

Measured on `11ed0e82` (2026-10-26, `func` 0.4.0, isolated `HOME=/tmp/rt-scratch/home`,
scratch project with `.functualize/jobs/release.py`):

```console
$ func release
released
$ echo $?
0
$ func builtin run list
run-01M5W89G7YFA8W3CG1F6SDDENT  release  success  func.job  52ms
$ func --run-tag harness:claude release
Error: Unknown command 'run-tag'.
Run 'func' to see all available commands.
$ echo $?
1
$ func builtin run list --tag session-id:7f3a
Error: No such option '--tag'. Did you mean '--state'?
$ echo $?
2
$ func builtin runs
Error: No such command 'runs'. Did you mean 'run'?
$ echo $?
2
$ func builtin run tag run-01M5 k:v
Error: No such command 'tag'.
$ echo $?
2
$ func --force builtin run list
Error: No such option '--force'.
$ echo $?
2
$ FUNCTUALIZE_RUN_TAGS="session-id:abc" func release
released
$ echo $?
0
$ func builtin run list --format json
{ "runs": [ { … "force": false, "group_option_values": {}, "invoke_depth": 0,
              "job": "release", …  "surface": "func.job" } ] }
```

The flag is rejected as an unknown command rather than as an unknown option,
which is what the shape's §5.2 predicts: `--run-tag` is not in the global
grammar's value-taking set, so `detect_mode` reads the *value* as the command
name (`_cli/dispatch.py:145-195`). The environment variable is accepted and
silently ignored — no reader exists. The JSON projection has no `run_tags` key
(`app/_run_view.py:141-156`).

**Why it hurts.** An agent that ran forty `func` commands in one session cannot
later ask "which runs were mine?". The run log knows the job, the door
(`surface`), the time, the scope and the parent. It does not know who or what
asked. The only way to tell is to guess from timestamps, and that breaks when
two sessions work in one project at the same time. The same gap exists for a CI
job id, an experiment name, or a ticket key.

### 1.1 What exists today (verified)

| Fact | Evidence |
|---|---|
| No run tag anywhere in the tree: no field, no flag, no environment variable, no record key | `rg -n 'run_tags\|RUN_TAGS\|run-tag' -g '*.py' -g '*.sql' src plugins` → no output, rc 1 |
| The global-flag grammar is an explicit list, and each entry needs the parser's help to consume its value | `_types/flag_grammar.py:46-63` (`GLOBAL_OPTIONS_ALWAYS_VALUE`, 16 entries ending `--emit-format`); `GLOBAL_OPTIONS_WITH_VALUE` aliases it at `:95-98`; `GLOBAL_BOOL_FLAGS` at `:100-113` |
| `detect_mode` skips a value-taking flag *and its value* before deciding the command; a flag absent from that set leaves its value to be read as the command | `_cli/dispatch.py:97`, skip loop `:145-195` (value-taking branch `:159-166`) |
| The accumulator is `__slots__`-only, and a repeated flag appends by name | `_cli/dispatch.py:433-453` (`__slots__`), `:455-474` (`__init__`), `:477` (`_assign_option`, append idiom `:490-493`) |
| Today's resolved global options are a fixed record; `--force` is the precedent for a run-scoped boolean | `_cli/dispatch.py:236-262` (`ParsedGlobalOptions`), `:264` (`_extract_global_options`), `--force` rationale `:296-307` |
| Four delivery inputs reach `RunRequest` from the CLI: `output_format`, `prompt_gates`, `force` (three today) | `app/adapters/_request_builder.py:91-102` (params), `:124-128` (ambient gate), `:129-151` (`RunRequest(...)`) |
| Every door builds its request through those two adapters, both keyword-only | `app/adapters/click_params.py:1006` (`build_job_engine_callback`, kw-only `:1012-1019`), `:1376` (`create_job_click_command`, kw-only `:1381-1389`) |
| The CLI threads each delivery input through four handlers and four forwarding sites | `_cli/main.py:959-967` (`_dispatch_group`, kw-only `:963-966`), `:1305-1310`, `:1359-1364`, `:1672-1677` (the three handlers' kw-only blocks); forwarding `:2240-2246`, `:2254-2264`, `:2272-2283`, `:2315-2325`; `ctx.obj` `:410-414` |
| `RunRequest` carries a frozen field set; `force` is the model for a run-scoped scalar | `_types/run_request.py:178-179` (`@dataclass(frozen=True, slots=True)` + `class RunRequest:`), `kwargs` `:193`, delivery block `:195-198` (`force: bool = False` at `:198`), `replace` `:259` |
| `nested_request` rebuilds a child from a reset dict, and `kwargs` is emptied there | `_types/run_request.py:340-376`, reset dict `:364-374`, `"kwargs": _EMPTY` `:365` |
| The executor writes the record's fields from the request | `_engine/executor.py:959-1003` (`store.open_run({...})`, `"force": request.force` at `:1000`, `runner` `:1001`) |
| The document store's run entry is a plain dict under `.functualize/runs.json` — a new key needs no schema | `_primitives/run_store.py:218` (`open_run`), `:249` (`close_run`) |
| Ordinary runs go to the **document** store by default; SQLite only when `runtime_store.url` says so | `_app/store_selection.py:44-45` (`CONFIG_KEY = "runtime_store.url"`, `DEFAULT_URL = "documents:"`), resolution `:77-102` |
| The SQLite package already ships revisions **1–4** | `_migrations.py:112-117` (`_load(1..4)`); schema files `0001`–`0004` |
| The SQLite store's `start_attempt` writes `runs` and `run_attempts` in one transaction and never sees a tag map | `_run_sql.py:87-117` (the two `INSERT`s at `:94-110` and `:111-115`); `StartAttempt` `_types/persistence.py:499-518` — its fields are `job, surface, now, scope_id, parent_run_id, invoke_depth, args_hash` (`:511-518`), so no caller can pass a tag map |
| Every `StartAttempt` in the tree is built without a tag map | `_engine/recording/run_recorder.py:18-22` — the module docstring says "Nothing constructs these values anywhere in the tree yet" (`:20-22`); the nine construction sites are `_engine/recording/run_recorder.py:56`, `testing/conformance/capabilities.py:141`, `testing/conformance/baseline.py:91`, `:95`, `:272`, `:332`, `plugins/substrates/functualize-substrate-sqlite/tests/test_run_sql.py:59`, `tests/test_legacy_import.py:101`, `tests/test_readers.py:191` |
| `list_runs` filters in Python over every record and applies `limit` last; the projection is one flat dict | `app/_run_view.py:181-232` (filters `:218-228`, append `:229`, break `:230`, return `:232`), `_describe` `:128-156` |
| The document reader over-reads `limit * 8` before filtering, to survive non-matching records | `_primitives/document_store.py:214-241` (`limit` default `:221`, over-read `:225`, per-field `continue` `:227-237`, append `:238`) |
| The user config reader drops an unrecognized section silently, and an unrecognized key inside a recognized section with a warning | `_cli/config.py:26` (`_RECOGNIZED_SECTIONS`), `:29`, `:34` (`_RECOGNIZED_KEYS`), filter loop `:123-158` |
| Environment overrides are a generic `<SECTION>_<KEY>` mapper reached only from `resolve_cli_config` | `_cli/config.py:161` (`resolve_env_overrides`), `:207` (`remainder.split("_", 1)`), `:213-215`; `resolve_cli_config` `:447`, called at `:486` |
| `func builtin …` never declares the delivery inputs, so it refuses them at parse time | `_cli/main.py:2331-2370` (`BUILTIN` mode near-path, ending at `register_builtin_commands(cli_app)`; rejected flags `:2340-2342`), `:64-73` (`format_options` docstring) |
| Job tags are a separate, source-declared thing | `func builtin info jobs release --json` → `"tags": ["infra", "release"]` (measured); `@job(tags=[...])` |

### 1.2 Census (shape experiment E1, extended to H1)

The shape's H1 asks whether every run a command starts passes through
`nested_request`. Census, measured at `11ed0e82`:

- `rg -n 'RunRequest\(' src plugins -g '*.py'` → **12 matches in 10 files**:
  `plugins/adapters/functualize-mcp/src/functualize_mcp/_server.py:311`,
  `…/_tools.py:327` and `:516`, `_app/impl.py:972`, `_cli/inline_tui.py:243`,
  `_cli/tui/job_execution.py:246`, `_types/run_request.py:330` and `:363`
  (inside `nested_request` itself), `app/_workflow_control.py:213`,
  `app/adapters/_request_builder.py:129`, `app/core.py:870`, plus
  `plugins/substrates/functualize-substrate-sqlite/tests/test_cutover_marker.py:73`
  (incidental). The shape's count of 11 predates one of these; the conclusion is
  unchanged.
- `nested_request` call sites: `_engine/workflow_orchestrator.py:95`,
  `_engine/capabilities/invoke.py:473` and `:875`,
  `_engine/dependency_runner.py:150`.

**H1 holds**: every child run is built by `nested_request`, so one copy rule in
that method covers steps, `Invoke`, `invoke_parallel`, dependencies and nested
workflows. The direct constructions are top-level doors (they need the field
*set*, not copied) or the method itself.

## 2. Users and stories

- **A developer reproducing a bug** wants every run of one attempt under one
  label, so "what did that attempt touch" is one query instead of a timestamp
  guess: `func --run-tag repro:bug-412 --run-tag attempt:3 release`, then
  `func builtin run list --tag repro:bug-412 --tag attempt:3`.
- **A coding-agent harness** exports one variable per session, and every `func`
  process it starts — and every process those start — is labelled, including
  runs of a job that shells out to `func` again.
- **A CI job** labels runs with its pipeline id and commit, then asks the run
  log which runs failed under that label.
- **An operator reading the run log** sees the labels on the row and in `run
  show`, and can narrow a scope's runs to the ones a given harness started.
- **A job author** is not a user of this feature: a tag never reaches the job,
  its arguments, its cache or its exit code.

## 3. Behaviour

### 3.1 Giving tags — three layers, one map

> "The tags come from **three places**, lowest to highest: `[run] tags` in the
> machine's `~/.config/functualize/config.toml`, an environment variable a
> harness exports once per session, and a repeatable **global flag** before the
> job name. The higher layer wins a repeated key (§5.1)." — shape §1, verbatim.

- `--run-tag KEY:VALUE`, repeatable, **before** the job name. After the job
  name it is a job option and the job's parser refuses it.
- `FUNCTUALIZE_RUN_TAGS`, a comma-separated list; whitespace around an item is
  trimmed and **empty items are skipped**, so `${CLAUDECODE:+harness:claude},
  model:opus` works with `CLAUDECODE` unset.
- `[run] tags` in the **global user** config file only. `.functualize.toml` is
  deliberately not read (OQ-6): a repository must not be able to label the runs
  of whoever executes it.
- One tag is `key:value`, split at the **first** `:` so `url:https://x` works.
  Keys are lower-case ASCII letters, digits, `.`, `_`, `-`, starting with a
  letter or digit. Values are 1–256 characters with no whitespace and no `,`.
- The three layers merge **per key**, higher wins. A key repeated inside one
  layer is an error. This is deliberately not the `import_libs`
  concatenation rule (`_cli/config.py:391-445`).
- A run carries at most **32** tags (shape §10 R4, adopted as a declared limit
  so the refusal is testable rather than discovered).

### 3.2 Early parse — validation before boot

> "They are **read before the run record is opened**, and are fixed for the
> life of the run." — shape §1.

`--run-tag` joins the value-taking global grammar
(`_types/flag_grammar.py:46-63`) so `detect_mode` consumes its value instead of
reading it as the command name (`_cli/dispatch.py:159-166`), is accumulated like
`--import-libs` (`_cli/dispatch.py:477`, append idiom `:490-493`), and lands on `ParsedGlobalOptions` beside
`force` (`_cli/dispatch.py:236-262`). All three sources are validated and merged
inside `_cli` before boot; the global config file's `[run] tags` is validated as
part of the same merge, which is why it is read at boot rather than after job
discovery. Every refusal exits **2**, runs nothing and records nothing.

`func builtin …` never declares the delivery inputs, so it refuses the flag
exactly as it refuses `--force` today (`_cli/main.py:2331-2370`, measured
transcript in §1).

### 3.3 The run record

> "A record written before this feature has no `run_tags` key. Readers treat a
> missing key as `{}`." — shape §5.3.

- **Document store.** One new key on the run entry:
  `"run_tags": {"harness": "claude", "host": "laptop", …}`. Written by
  `RunStore.open_run` (`_primitives/run_store.py:218`) from the same dict the
  executor already builds (`_engine/executor.py:959-1003`).
- **Relational store.** A new revision `0005_run_tags.sql` — the shape's
  `0003_run_tags.sql` is marked *provisional* and the package already ships
  revisions 1–4 (`_migrations.py:112-117`), so the number is **5**. Table
  `run_tags (namespace_id, run_id, key, value)` keyed by
  `(namespace_id, run_id, key)`, `ON DELETE CASCADE` from `runs`, and index
  `run_tags_lookup (namespace_id, key, value)`. Rows go in the same transaction
  as the `runs` row; retention drops them through the cascade.
- **Third-party stores** receive the map on `StartAttempt.run_tags`
  (`_types/persistence.py:499-518`), defaulting to an empty map because nine
  existing construction sites omit it.
- Tags are never rewritten. A store-level attempt to change them is a
  programming error, not a user error.

### 3.4 Inheritance — an exact copy

> "Every child run (steps, `Invoke`, `invoke_parallel`, dependencies, nested
> workflows) carries an exact copy of its top-level run's tags" — shape §7,
> binding.

`RunRequest.run_tags` is a `Mapping[str, str]` copied verbatim by
`nested_request` (`_types/run_request.py:340-376`). A child cannot add, change
or remove a tag. A **separate `func` process** is not a child: it inherits the
environment variable the job's own environment carries
(`_engine/capabilities/shell.py:1023`, `merged = dict(os.environ)`), and reads
its own flag and config file — never the parent's flag. That is why continuing a
workflow is asked by `--scope`, where the tree already ties the runs together.

### 3.5 Query

> "`--tag KEY:VALUE` is repeatable, and a run must match **all** of them.
> Matching is exact and case-sensitive." — shape §5.5.

- `--tag` combines with `--job`, `--surface`, `--state` and `--scope`;
  `--limit` is still applied after every filter.
- Every projection row gains `run_tags` (`{}` when none). The MCP run tools call
  the same `list_runs`, so they inherit it and need no new input.
- The table prints tags last, sorted by key, `key:value` separated by spaces. A
  run with no tags renders exactly as today.
- No match is `No matching runs.` with exit 0 — the existing empty-list
  behaviour, not an error.

### 3.6 Job tags stay separate

> "Run tags and job tags are separate things, in separate fields and separate
> commands; they never merge" — shape §7, binding.

`@job(tags=[...])` describes the job and is written in source; `func builtin
info` reports it unchanged. Run tags describe one execution. `--tag` filters run
records only, so `--tag infra:yes` matches nothing even when a job declares
`infra`.

### 3.7 Must not change

> "Tags never enter `args_hash` or freshness, and a job cannot read them in v1."
> — shape §7, binding.

- A tagged run and an untagged run with the same arguments compute the same
  `args_hash` and reuse each other's cached results.
- No new decorator argument, no `RunContext` attribute (OQ-4), no `Invoke`
  argument.
- No change to exit codes, to the table layout of an untagged run, or to job
  discovery and configuration resolution.
- A scope, a gate and an event never carry tags; a run of a scope does.
- No HTTP, Lambda or MCP **input** for tags in v1; the TUI starts runs with no
  tags.

## 4. Acceptance criteria

Each maps to a shape experiment (E1–E5) or a binding row of the shape's §7.

| # | Given | When | Then |
|---|---|---|---|
| AC1 (E1) | a project with a job | `func --run-tag harness:claude release` | the run record's `run_tags` is `{"harness": "claude"}`; exit 0 |
| AC2 (E1) | `[run] tags = ["host:laptop", "tier:1"]` and `FUNCTUALIZE_RUN_TAGS="tier:2,model:opus"` and `--run-tag model:sonnet` | the job runs | `{host: laptop, tier: 2, model: sonnet}` — per-key merge, higher layer wins |
| AC3 (E1) | a tag whose value holds colons | `--run-tag url:https://x` | key `url`, value `https://x` (split at the first `:`) |
| AC4 (E1) | `FUNCTUALIZE_RUN_TAGS="${CLAUDECODE:+harness:claude}, model:opus"`, `CLAUDECODE` unset | the job runs | `{model: opus}` — empty items skipped, whitespace trimmed |
| AC5 (E1) | a key outside the grammar | `--run-tag Model:opus` | `Error: --run-tag 'Model:opus': a run tag key uses a-z, 0-9, '.', '_' and '-'.`, exit 2 |
| AC6 (E1) | a value of 257 characters, and one of 256 | each given as `--run-tag k:<v>` | 257 refused with the length message, exit 2; 256 accepted |
| AC7 (E1) | 33 distinct keys across the three layers | the job runs | refused before boot with the tag-count message, exit 2; 32 accepted |
| AC8 (E2) | the caller's input | every row of the shape's §5.6 table is typed | that row's message, exit **2**, no job body runs and no run record is written |
| AC9 (E2) | the same key twice | within one layer (`--run-tag s:1 --run-tag s:2`, `s:1,s:2` in the env, `["s:1","s:2"]` in the config file) | refused, naming the layer and the two items; across layers it merges instead |
| AC10 (E2) | builtin mode | `func --run-tag a:b builtin run list` | `Error: No such option '--run-tag'.`, exit 2 — today's shape for `--force` |
| AC11 (E2) | `[run] tags = ["a:b", ":x"]` in `~/.config/functualize/config.toml` | any job command | `Error: [run] tags item 2 ':x': a run tag needs a key before ':'.`, exit 2, before any job body runs |
| AC12 (E1) | `[run] tags = ["repo:x"]` in `.functualize.toml` | any job command | the run carries no `repo` tag and no warning is produced for the project file; the key contributes nothing |
| AC13 (E3) | the document store | a tagged run completes | the run entry carries `run_tags` with exactly the merged map |
| AC14 (E3) | a run entry written before this feature (no `run_tags` key) | `run list --format json`, `run show`, MCP `list_runs` | the row's `run_tags` is `{}`; no error |
| AC15 (E3) | a SQLite-backed project at revision 4 | a tagged run completes and the database is migrated | `run_tags` holds one row per tag keyed by `(namespace_id, run_id, key)`; `run_tags_lookup` exists; deleting the run removes its rows |
| AC16 (E3) | the same tagged run recorded on both stores | `run list --tag k:v` against each | identical run ids and identical `run_tags` maps |
| AC17 (E4) | a tagged top-level run whose job uses a step, `Invoke`, `rc.invoke_parallel`, a dependency and a nested workflow | the run completes | every child record carries an exact copy of the top-level map |
| AC18 (E4) | a child built through `nested_request` | the child's request is inspected | its map equals the parent's, and the child has no way to add, change or remove an entry |
| AC19 (E4) | `FUNCTUALIZE_RUN_TAGS="harness:claude" func test`, where `test` shells out to `func coverage report` | both runs complete | both records carry `harness:claude`; the second has no `parent_run_id` |
| AC20 (E5) | runs tagged `repro:bug-412` and/or `attempt:3` | `run list --tag repro:bug-412 --tag attempt:3` | only runs carrying **both**; matching is exact and case-sensitive |
| AC21 (E5) | a scope with tagged and untagged runs | `run list --scope <id> --tag harness:claude --limit 2` | at most two rows, all in that scope and all matching; `--limit` applied after every filter |
| AC22 (E5) | any run | `run list --format json` | every row has `run_tags`, `{}` when none; the key is present for pre-feature records too |
| AC23 (E5) | a run with tags `attempt:3` and `repro:bug-412` | the table view | the row ends `attempt:3 repro:bug-412` — last, sorted by key, space-separated; an untagged row is byte-identical to today |
| AC24 (E5) | no run carries the tag | `run list --tag session-id:nope` | `No matching runs.`, exit 0 |
| AC25 (E5) | the MCP run tools | `list_runs` is called | each returned run carries `run_tags`; the tool takes no tag input in v1 |
| AC26 (E5) | a tagged run | `run show <id>` and `run show <id> --format json` | the text form has a `run_tags:` line and the JSON payload carries the map |
| AC27 (E3) | the same job invoked twice with the same arguments, once tagged `x:1` and once untagged | both records are read | identical `args_hash`; the second reuses the first's cached result |
| AC28 (E3) | a tagged run | the job body inspects its environment | no tag reaches `RunContext`, the job's kwargs, its return value or its exit code |
| AC29 (E3) | a job declaring `@job(tags=["infra", "release"])` | `func builtin info jobs <job> --json` and `run list --tag infra:yes` | `.tags` is `["infra", "release"]`; the tag filter matches nothing — the two vocabularies never merge |
| AC30 (E3) | a record already written when a store is opened | any read path | readers treat a missing `run_tags` as `{}` and never rewrite the record to add it |
| AC31 (E5) | a run started with no tag source at all | the CLI table, the exit code and `--format json` | table row and exit code byte-identical to today; JSON differs only by the added `run_tags: {}` key |
| AC32 (C) | the tree after the change | `rg -n 'run_tags' src plugins` is reviewed | readers are only `_cli`, the stores, `_run_view` and their tests — no decision is taken on a tag value |
| AC33 (C) | a run that already exists | `func builtin run tag <id> k:v`, or any store write attempting to change a tag | `Error: No such command 'tag'.`, exit 2; a store-level rewrite is refused as a programming error |
| AC34 (C) | a workflow scope with tagged runs | the scope's projection is read | the scope record carries no `run_tags`; its runs do |

## 5. Out of scope

From the shape's *Boundaries and non-goals*, verbatim in substance:

- Tags on workflow **scopes**, gates or events. A scope's runs carry tags; the
  scope does not.
- Changing tags after a run opens, or deleting them on their own.
- Searching by key alone (`--tag session-id`), by prefix, or by pattern.
- Secrets. Tags are stored in plain text, and the docs must say so.
- Any change to job tags, `@job(tags=...)` or `func builtin info`.
- Joining 0.5.0. This ticket blocks nothing in that release.

Also not carried, from the shape's §5.8: tags as an **input** on HTTP, Lambda or
MCP; tags for runs started from the TUI; a project-file layer; any authoring-API
surface (decorator argument, `RunContext` attribute, `Invoke` argument).
