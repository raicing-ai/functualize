# run tags — Plan

## Alignment

- **Shape:** *Shape Intent — Run Tags: Arbitrary Tags on Job Runs, Inherited and
  Queryable* — Confluence `SD/18972686`, **version 3** (updated
  2026-10-26 11:57:10 UTC),
  `Status = Approved`, `Authority = Approved`. Read live on 2026-10-26 before
  this plan was written.
- **Approval record:** member comment `01a15396` on version 2 — "Ok follow your
  recommendations. Approved" — and the version-3 header flip at 11:57:24Z
  (comment `01a17812-8ebb-7108-b56e-eccf463b98e2`). Revision 3 is the build
  shape; it added the config layer of §5.1 and the early-parse sequence of §5.2.
- **In scope, in the shape's words:**
  - "a repeatable **global flag** before the job name" (shape §1, §5.1:
    `func [GLOBAL OPTIONS] --run-tag KEY:VALUE [...] <group> <job> [job options]`)
  - "an environment variable a harness exports once per session" —
    `FUNCTUALIZE_RUN_TAGS="KEY:VALUE, KEY:VALUE, ..."` (§5.1)
  - "`[run] tags` in `~/.config/functualize/config.toml`, a list of
    `key:value` strings … at the **bottom** of the three layers" (§5.1)
  - "`--tag KEY:VALUE` … repeatable with AND semantics, exact and
    case-sensitive" on `run list`, and "every row gains `run_tags` (`{}` when
    none)" (§5.5:274-277)
  - both record formats — the document store's `run_tags` key and the SQLite
    `run_tags` table (§5.3:203-245)
  - "A copy, not a merge or an override" for every child run (§5.4:253)
  - "the **global user** file is touched … The **project** file is deliberately
    not read" (§5.8:336)
- **Out of scope, in the shape's words:** "Tags on workflow **scopes**, gates or
  events"; "Changing tags after a run opens, or deleting them on their own";
  "Searching by key alone (`--tag session-id`), by prefix, or by pattern";
  "Secrets. Tags are stored in plain text, and the docs must say so"; "Any
  change to job tags, `@job(tags=...)` or `func builtin info`"; "Joining 0.5.0".
  Also not carried (§5.8): tags as an **input** on HTTP, Lambda or MCP; tags for
  runs started from the TUI; a project-file layer; any authoring-API surface.
- **Must not change, in the shape's words:** "Run tags and job tags are separate
  things … The two never merge" (§7:395); "Tags never enter `args_hash` or
  freshness, and a job cannot read them in v1" (§7:400); "A run's tags are fixed
  when it opens" (§7:399); "`func builtin …` refuses the flag exactly as it
  refuses `--force`" (§7:403).
- **Shape risks answered here:** R1 (a config layer declared but not
  registered, and an env spelling validated twice) → §4.1 and §4.11; R2
  (secrets) → §4.12 docs, plus the "no job can read a tag" fence in §4.7; R3 (a
  broken env value stops every command) → §4.5, intended and loud; R4 (growth) →
  the 32-tag cap in §4.1; R5 (another door wants tags first) → decision D6.
- **Related, not carried:** `SD/18153475` (the owner request behind this
  feature; the `runs` spelling it uses does not exist — measured in `spec.md`
  §1). `SD/18317314` (the four review rules R-1…R-4 that `spec.md` §8 binds
  this plan to). `SD/16908324` (store parity, cited by shape §5.3 — this plan's
  §4.8/§4.9 keep both stores answering one query). `SD/17137669` (the
  unknown-key check on the project file — a `[run]` table there must not be
  reported as accepted-and-read; §4.11).

## 1. Skills consulted

- `python-design-patterns` (in-repo, `.agents/skills/python-design-patterns`) —
  the KISS rule (`.agents/skills/python-design-patterns/SKILL.md:23`), single
  responsibility (`:27`), composition over inheritance (`:31`), and the Rule of
  Three (`:35`): how many copies of a
  parse/merge rule justify an abstraction. This plan adds **one** new module for
  four call sites of the same grammar; it adds no class.
- `design-patterns-refactoring` (user-level; Refactoring.Guru catalogue) — the
  smell names used in §2 and §3 (*Shotgun Surgery*, *Divergent Change*,
  *Primitive Obsession*, *Duplicate Code*, *Long Method*, *Data Clumps*), and
  their routing to a remedy.
- `code-intel` — the `rg`/symbol census in §2 and the blast radius in §5.
- `test-tiers` — which pytest tier covers which task in `tasks.md`; the six
  gates in `AGENTS.md:7-46`.
- `sync-docs` / `doc-verify` — §4.12: which documents claim authority over the
  flag tables, the run-log projection and the run list, and how to verify the
  rendered pages after the edit.

## 2. Architecture pass — the region today

Tools: `rg -n` over `src/`, `plugins/`, `tests/` at `11ed0e82`; direct reads of
every anchor below; `uv run lint-imports` → **7 kept, 0 broken** (401 files,
1179 dependencies). Codemaps: `contributor/architecture/codemaps/overview.md`
(layer vocabulary — delivery `_cli/`, public `app/`, peer `_types/` _and_
`_primitives/`, internal `_engine/`). Nothing in the codemap mentions run tags;
nothing contradicts the drawing.

Census (shape experiment E1, extended): `rg -n 'run_tags|RUN_TAGS|run-tag' -g
'*.py' -g '*.sql' src plugins` → **no output, rc=1**. `rg -n 'RunRequest\(' src
plugins -g '*.py'` → **12 matches in 10 files** (shape §10 says 11; the live
count is 12 — `spec.md` §1.2 lists them). `rg -n 'nested_request\(' src` → 4
call sites.

### BEFORE

```
 layer: delivery  _cli/  (may import public folders + _cli siblings only)
 ┌──────────────────────────────────────────────────────────────────────────┐
 │ _cli/dispatch.py                                                         │
 │   _extract_global_options (264-400)                                      │
 │     _OptionAccumulator (430-474)   __slots__ (433-453): output,          │
 │       │                            prompt_gates, force                   │
 │       ├── _assign_option (477-538)  --force is BOOL; no list-valued      │
 │       │                            delivery input exists                 │
 │       └── ParsedGlobalOptions (238-261): output :258, prompt_gates :259, │
 │                                        force :260                         │
 │   detect_mode (142-191)  skips a value-required flag's next token         │
 │       │                  only for GLOBAL_OPTIONS_ALWAYS_VALUE (:154)     │
 │       ▼                                                                  │
 │ _cli/main.py  _run_cli (2033-2340)                                       │
 │   prompt_gates = global_opts.prompt_gates  (:2234)                       │
 │   force        = global_opts.force         (:2235)   ← two scalars,      │
 │       │                                               copied four times  │
 │       ├── _handle_single_file (1670-)  ──┐                               │
 │       ├── _handle_job        (1353-)  ──┤  each takes prompt_gates=,     │
 │       ├── _handle_group      (1298-)  ──┤  force= as keyword-only and     │
 │       ├── _handle_bare       (575-582) ─┘  forwards them again            │
 │       └── BUILTIN mode declares none of them, so Click refuses            │
 │           (comment :2331-2358; measured: No such option '--force')        │
 │                              │                                          │
 │ _cli/builtins.py  run_list (1930-1971)  --job/--surface/--state/         │
 │                    run_show (1989-)        --scope/--limit/--format      │
 └──────────────────────────────┬───────────────────────────────────────────┘
                                │ public API only
 public  app/utils.py → app/_run_view.py  list_runs (181-232)  _describe (:128-156)
                                │
 ┌──────────────────────────────▼───────────────────────────────────────────┐
 │ peer  _types/                                                           │
 │   run_request.py  RunRequest (178-208): job_name, surface, kwargs,       │
 │                     prompt_gates :196, output_format :197, force :198,   │
 │                     group_option_values :201, … , parent_run_id         │
 │                   nested_request (340-376): delivery inputs travel down, │
 │                     seven fields reset (:364-374)                        │
 │   persistence.py  StartAttempt (499-518): job, surface, now, scope_id,   │
 │                     parent_run_id, invoke_depth, args_hash — no tags     │
 │                   RunView (654-670), RunQuery (775-783): job, status,    │
 │                     scope_id, parent_run_id, limit                       │
 └──────────────────────────────┬───────────────────────────────────────────┘
 ┌──────────────────────────────▼───────────────────────────────────────────┐
 │ internal  _engine/executor.py                                            │
 │   _open_run_record (938-1006) builds the record dict: job, surface,      │
 │     args_hash :965, scope_id :991, parent_run_id :993, invoke_depth,     │
 │     group_option_values :995, force :1000, runner :1001                  │
 │     → RunStore(self.substrate).open_run(...) :959                         │
 │     except Exception: pass (:1004-1006) — an observation never fails a run│
 └──────────────────────────────┬───────────────────────────────────────────┘
 ┌──────────────────────────────▼───────────────────────────────────────────┐
 │ primitives + plugins                                                     │
 │   _primitives/run_store.py   open_run (218-247)  writes the dict as-is   │
 │   _primitives/document_store.py _DocumentRunReader.recent (214-241)      │
 │     over-reads limit*8 (:225), filters job/status/scope/parent (:227-237)│
 │   plugins/substrates/…-sqlite  _migrations.py SHIPPED_MIGRATIONS         │
 │     (112-117) = revisions 1-4; 0001_runtime_schema.sql runs (32-49)      │
 │   _run_sql.py  SqlRunWriter.start_attempt (87-117) — one INSERT, no tags │
 │   _readers.py  SqlRunReader._COLUMNS (45-48), _view (54-67), recent (76-93)│
 └──────────────────────────────────────────────────────────────────────────┘
```

### Smells the BEFORE already carries

| Smell | Where |
|---|---|
| *Shotgun Surgery* | a delivery input costs four edits in four handlers plus the builder and both click command factories: `_handle_single_file` (`_cli/main.py:1672-1677`), `_handle_job` (`_cli/main.py:1359-1364`), `_handle_group` (`_cli/main.py:1305-1310`), `_handle_bare` (`_cli/main.py:575-582`), `_request_builder.build_request` (`app/adapters/_request_builder.py:97-99`, `:124-145`), `build_job_engine_callback` (`app/adapters/click_params.py:1012-1019`), `create_job_click_command` (`app/adapters/click_params.py:1381-1389`). A fourth input must make the same tour. |
| *Divergent Change* | four hand-maintained flag lists answer one question: `GLOBAL_OPTIONS_ALWAYS_VALUE` (`_types/flag_grammar.py:46-65`), `GLOBAL_BOOL_FLAGS` (`_types/flag_grammar.py:104-113`), `_OptionAccumulator.__slots__` (`_cli/dispatch.py:433-453`), `ParsedGlobalOptions` (`_cli/dispatch.py:238-261`). Adding one flag edits four lists, and forgetting one is a silent behaviour change — measured: a flag in none of them becomes the command name (`func --run-tag harness:claude release` → `Unknown command 'run-tag'`, exit 1). |
| *Primitive Obsession* | the run record is a bare `dict[str, Any]` built by hand in `_open_run_record` (`executor.py:938`), the `open_run({…})` call at `:959-1003`, and read back with `.get("…")` in four readers (`app/_run_view.py:138-156`, `document_store.py:269-281`, `_readers.py:54-67`), so every new key is an untyped agreement across five files. |
| *Data Clumps* | `prompt_gates`/`output_format`/`force` travel together through every signature (`app/adapters/_request_builder.py:97-99`, `_types/run_request.py:196-198`) and are documented as a set ("The three **delivery inputs**", `app/adapters/_request_builder.py:110-115`) without ever being one value. |
| *Long Method* | `register_builtin_commands` (`builtins.py`, `run_app.command("list")` at `:1902` … `:2020`) already carries both run subcommands; `run_list` itself is small (`:1930-1971`) but its row rendering is inline (`:1963-1971`). |
| *Primitive Obsession* (second site) | the document reader's over-read factor `limit * 8` (`document_store.py:225`) is a hand-tuned constant standing in for "enough headroom for a selective filter"; a new selective filter (tags) has no way to declare its own selectivity. |

## 3. Candidate AFTERs

Rejections first, each with the anchor that fails it.

- **A1 (rejected) — environment variable only.** The shape's §5.1 lists three
  sources and `spec.md` AC1/AC2 require the flag and the config layer. A single
  env var is also unsettable per-invocation by a caller who does not own the
  shell, which is exactly the harness case (§2 of the shape).
- **A2 (rejected) — flag only.** `spec.md` AC2 and AC4 are layer tests; with one
  layer there is nothing to merge, and §5.2's "read before the run record is
  opened" loses its only interesting case.
- **A3 (rejected) — a process-global (`ContextVar` or module dict) carried into
  the run.** This is the mechanism `run_request.py:212-216` records as already
  refuted for `parent_run_id`: `rc.invoke_parallel` runs items on a
  `ThreadPoolExecutor` and "a fresh thread starts with an empty context", so the
  children that most need the value are the ones that lose it. §5.4's exact-copy
  rule would be unenforceable.
- **A4 (rejected) — fold run tags into the existing job tags.** §7:395 is
  binding: "Run tags and job tags are separate things … The two never merge."
  The two also answer different questions and live on different objects (a job
  declaration vs. a run record), and `spec.md` AC29 measures that
  `info jobs --json .tags` stays `["infra","release"]`.
- **A5 (rejected) — an append-only tag log the run reads through.** §7:396
  binds one value per key per run, and §5.4:255 shows collision is impossible
  inside one tree because the map is copied, not extended. A log buys nothing
  and costs a second reader.
- **A6 (rejected) — a delta map written on the child and resolved by walking
  ancestors.** §5.4:253 says "A copy, not a merge or an override"; a delta
  makes every reader a resolver, and `_describe` (`_run_view.py:128-156`) would
  have to walk the tree to answer one row.
- **A7 (chosen) — one `_cli/run_tags.py` parser/merger, one
  `RunRequest.run_tags` field, one record key, one `run_tags` table and one
  filter.** Three layers become one frozen map before boot; the map is a request
  field, so `nested_request`'s existing `parent.replace(**fields)` copy
  (`run_request.py:376`) carries it down with **no code at all**; the record
  stores it under one key (document) or one table (SQLite); the readers expose
  it in the projection they already build, and the filter is one comparison in
  each store's existing predicate chain.

  *Introduced-smell check for A7:* (1) *Speculative Generality* — is the new
  module one call site? No: four (flag, env, config, and the merge itself, plus
  the refusal in `main.py`), and Rule of Three is satisfied. (2) *Divergent
  Change* — does it centralise or spread? It centralises: all grammar and merge
  rules live in one file with no imports from the flag grammar, so
  `tests/types/test_flag_grammar_consumer_count.py`'s `EXPECTED_CONSUMERS` is
  untouched. (3) *Data Clumps* — does it add a fourth scalar to the clump? No:
  `run_tags` is one `Mapping`, deliberately not three more booleans, and the
  clump itself stays as it is (extracting a `DeliveryInputs` value object is
  refused in D2 — it would rewrite 12 `RunRequest(` sites for no behaviour).
  (4) *Shotgun Surgery* — does it worsen it? It adds the fourth input to the
  existing tour (unavoidable: the tour is the mechanism), but it adds **no
  fifth list**: `GLOBAL_OPTIONS_WITH_VALUE` is an alias of
  `GLOBAL_OPTIONS_ALWAYS_VALUE` (`flag_grammar.py:98`), so one edit covers both.

### AFTER

```
 layer: delivery  _cli/
 ┌────────────────────────────────────────────────────────────────────────────┐
 │ process edge, before boot:  argv[--run-tag …]  ·  $FUNCTUALIZE_RUN_TAGS     │
 │                             ·  ~/.config/functualize/config.toml [run] tags │
 │                                          │                                 │
 │                              ┌───────────▼─────────────┐                   │
 │                              │ _cli/run_tags.py  [NEW] │  parse_tag /      │
 │                              │  RunTagError            │  parse_env /      │
 │                              │  32-tag cap             │  parse_config_list│
 │                              └───────────┬─────────────┘  merge_layers     │
 │                                          │                                │
 │ _cli/dispatch.py  GLOBAL_OPTIONS_ALWAYS_VALUE += --run-tag                 │
 │   _OptionAccumulator.run_tags (list, append idiom) ─┐                      │
 │   ParsedGlobalOptions.run_tags                      │                      │
 │        │                                            │                      │
 │ _cli/main.py  _run_cli: run_tags = merge_layers(config, env, flag)         │
 │        │      refusal → SystemExit(2), nothing runs, nothing recorded       │
 │        ├──► _handle_job / _handle_group / _handle_single_file               │
 │        │    / _handle_bare   (run_tags= keyword on each)                   │
 │        └──► BUILTIN mode declares none → Click refuses, exit 2              │
 │                                          │                                 │
 │ app/adapters/_request_builder.py  build_request(..., run_tags: Mapping|None)│
 │ app/adapters/click_params.py      both builders pass it through             │
 └──────────────────────────────────────────┬─────────────────────────────────┘
                                            │ public API only
 ┌──────────────────────────────────────────▼─────────────────────────────────┐
 │ peer  _types/run_request.py  RunRequest.run_tags  (frozen map, not hashed)  │
 │       nested_request  → parent.replace(**fields) copies it verbatim         │
 │       _types/persistence.py  StartAttempt.run_tags (defaults to {}),        │
 │                              RunView.run_tags, RunQuery.tags               │
 └──────────────────────────────────────────┬─────────────────────────────────┘
 ┌──────────────────────────────────────────▼─────────────────────────────────┐
 │ internal  _engine/executor.py  _open_run_record: "run_tags": dict(...)      │
 └──────────────────────────────────────────┬─────────────────────────────────┘
 ┌──────────────────────────────────────────▼─────────────────────────────────┐
 │ document store                          │ plugin SQLite                    │
 │  _primitives/run_store.py               │  0005_run_tags.sql [NEW]         │
 │   open_run stores the key               │   run_tags(namespace_id, run_id, │
 │  document_store.recent: tag predicate   │            key, value) + index   │
 │   in the existing filter chain          │  _run_sql.py start_attempt: same │
 │                                         │   transaction as the runs INSERT │
 └──────────────────────────────────────────┬─────────────────────────────────┘
                                            │
 ┌──────────────────────────────────────────▼─────────────────────────────────┐
 │ app/_run_view.py   _describe(): + "run_tags"                               │
 │                    list_runs(): + tags filter, applied before the limit    │
 │ _cli/builtins.py   run list --tag KEY:VALUE (repeatable), row gains tags   │
 │                    run show: a run_tags line                               │
 │ MCP                _list_runs already calls list_runs → inherits the map   │
 └────────────────────────────────────────────────────────────────────────────┘
```

Closing note, as the shape puts it (§6.1:363): dependencies point down only. The
engine and the stores never parse a tag; they copy and store a map.

**Boundary check.** `_cli/run_tags.py` imports `dataclasses`, `collections.abc`,
`typing` — stdlib only, no `functualize._types`, no `_primitives`, no `_engine`
(`pyproject.toml:432-446`). It does **not** import
`functualize._types.flag_grammar`, directly or indirectly, so it stays outside
`tests/types/test_flag_grammar_consumer_count.py`'s `EXPECTED_CONSUMERS`. The
delivery adapters (`app/adapters/_request_builder.py`,
`app/adapters/click_params.py`) import `run_tags` only as a `Mapping` type from
`collections.abc` and never reach `_engine`
(`pyproject.toml:448-463`). `_cli/config.py` gains two constants in tables it
already owns — no new import. The new SQL file lives in the plugin's
`_schema/` directory and is loaded by `_migrations._load` (`:95-97`); the
plugin still imports no core module it did not already import.

## 4. Technical approach

### 4.1 `_cli/run_tags.py` (new)

Pure functions, no class, no module state:

- `TAG_KEY_RE = re.compile(r"[a-z0-9][a-z0-9._-]*")` and
  `MAX_VALUE_LEN = 256`, `MAX_TAGS = 32` — the shape's grammar of one tag (§5.1:169) and
  Risk 4's cap.
- `parse_tag(text: str, *, where: str) -> tuple[str, str]` — split at the
  **first** `:` (`text.partition(":")`), then validate: no `:` at all, empty
  key, empty value, whitespace in either part, key outside the grammar, value
  longer than 256 — each raising `RunTagError` with the §5.6 row's message
  (`spec.md` AC5, AC6; `contracts.md` C7).
- `parse_env(raw: str) -> tuple[tuple[str, str], ...]` — split on `,`, strip
  each item, **skip empty items** (the `${CLAUDECODE:+…}, model:opus` case,
  AC4), reject a duplicate key inside the one layer naming both items (AC9).
- `parse_config_list(items: object) -> tuple[tuple[str, str], ...]` — the same
  rules over the TOML list; a non-list or a non-string item is the §5.6 config
  row.
- `merge_layers(*layers) -> Mapping[str, str]` — dict-merge lowest→highest,
  `MappingProxyType` result, then the 32-key cap (AC7). A key repeated **across**
  layers is a merge, not an error (AC2); a duplicate inside one layer was
  already refused by that layer's parser.
- `RunTagError(Exception)` carrying `message: str`; `__str__` returns it. Every
  raise site names the flag, the env var or the file it came from, so an operator
  reading one line knows which of three places to edit.

Read-before-write of the config layer is `read_global_config(config_dir)`
(`_cli/config.py:100-158`), which means registration (§4.11) is a prerequisite
of this module returning anything.

### 4.2 `_types/flag_grammar.py`

One entry: `"--run-tag"` into `GLOBAL_OPTIONS_ALWAYS_VALUE` (`:46-65`).
`GLOBAL_OPTIONS_WITH_VALUE` is the same object under another name (`:98`), so
`--option=value` detection and the "move it before the group" advice both follow
without a second edit. It must **not** enter `GLOBAL_BOOL_FLAGS`
(`:104-113`) — it always consumes a value.

### 4.3 `_cli/dispatch.py`

Four edits, mirroring how `--import-libs` (`:490-493`) already works:

- `_OptionAccumulator.__slots__` gains `"run_tags"` (`:433-453`) and `__init__`
  initialises `self.run_tags: list[str] | None = None` (`:455-474`).
- `_assign_option` gains one branch with the append idiom (`:477-538`):
  `elif flag == "--run-tag": state.run_tags = [...]; state.run_tags.append(value)`.
  Parsing is **not** done here — dispatch collects spellings, `_cli/run_tags.py`
  judges them, because dispatch runs before `main.py` can report a refusal in
  the shape's message shape.
- `ParsedGlobalOptions` gains `run_tags: list[str] | None = field(default=None)`
  beside `force` (`:260`), and the constructor call (`:375-396`) passes
  `run_tags=state.run_tags`.
- `detect_mode` needs **no** edit: its skip loop already consults
  `GLOBAL_OPTIONS_ALWAYS_VALUE` (`:154`) and advances
  `i += 2 if value_required_takes_next(arg, nxt) else 1` (`:159`), so adding the
  flag to that set is what stops `harness:claude` being read as the command name
  — the measured failure in `spec.md` §1.

### 4.4 `_cli/config.py` — registering the config layer

- `"run"` into `_RECOGNIZED_SECTIONS` (`:26`).
- `"run": frozenset({"tags"})` into `_RECOGNIZED_KEYS` (`:34`), beside `vault`
  (`:67`).

Both are required, not cosmetic: `read_global_config` silently skips an
unrecognized section (`:131-133`) and drops an unrecognized key with the warning
`unrecognized key '{key}' in [{section}], ignoring` (`:148-152`). Without the
registration the layer would be declared in the docs and read as nothing —
Risk 1 exactly, and the reason AC11's broken-list message has to come from a
parser that actually sees the value.

`FUNCTUALIZE_RUN_TAGS` is **not** routed through `resolve_env_overrides`
(`:161`). Two measured reasons: that mapper splits at the first `_`
(`parts = remainder.split("_", 1)`, `:206`) so `RUN_TAGS` becomes section `run`
/ key `tags` holding one bare comma string — a shape no layer can validate as
items — and it is reached only from `resolve_cli_config` (`:447`, env read
`:484`), which runs after dispatch must already have refused a malformed tag
pre-boot. `_cli/run_tags.py` reads `os.environ` itself, in the same place the
flag list is merged. The shape (§5.1:171) names `resolve_env_overrides` as "the
environment spelling of the same key"; that sentence describes the *intent*, and
this plan implements it directly. Recorded as D1.

### 4.5 `_cli/main.py` — merge, refuse, forward

- After `global_opts, cli_flags = _extract_global_options(sys.argv)`
  (`_cli/main.py:2124`) and before discovery (`:2126`), build the map:

  ```python
  run_tags = merge_layers(
      parse_config_list(global_config.get("run", {}).get("tags")),
      parse_env(os.environ.get("FUNCTUALIZE_RUN_TAGS", "")),
      parse_flag_list(global_opts.run_tags),
  )
  ```

  wrapped so a `RunTagError` prints `Error: …` to stderr and raises
  `SystemExit(ExitCode.USAGE)` — **2**, not 1.
- The `cli_app` validation block (`_cli/main.py:252-288`) is the wrong precedent
  for the code: all four of its refusals `raise SystemExit(1)` (`:259`, `:268`,
  `:277`, `:288`). Every run-tag refusal is `USAGE = 2`
  (`_types/exit_codes.py:36-41`) and `_dispatch_group` already returns 2 for
  usage errors (`_cli/main.py:1110`). The message *shape* copies the block
  (`Error: …`, `err=True`), the code does not.
- Forward `run_tags=run_tags` at every site that forwards `force`: the
  SINGLE_FILE call (`_cli/main.py:2240-2246`), the JOB call (`:2254-2264`), the
  `_handle_group` call (`:2272-2283`), the UNKNOWN branch's `_handle_job`
  (`:2315-2325`), and the four handler signatures (`_handle_bare :575-582` —
  which has **no** `prompt_gates`/`force` today and gains one keyword with a
  `{}` default; `_handle_group :1306-1310`; `_handle_job :1360-1364`;
  `_handle_single_file :1673-1677`). The UNKNOWN comment (`_cli/main.py:2303-2313`)
  states the rule that makes this mandatory: "anything added to Mode.JOB's call
  belongs in this one too", because a cold discovery cache otherwise silently
  drops the value.
- BUILTIN mode: no edit. It declares none of the delivery inputs, so Click
  refuses `--run-tag` exactly as it refuses `--force`
  (`_cli/main.py:2331-2358`; measured `Error: No such option '--force'.`, exit
  2) — AC10.
- `ctx.obj` (`_cli/main.py:410-414`) gains nothing: it carries `app`,
  `cli_config`, `anchor` only, and the merge already happened before boot.

### 4.6 `app/adapters/` — the fourth delivery input

- `_request_builder.build_request` (`app/adapters/_request_builder.py:91-102`):
  `run_tags: Mapping[str, str] | None = None` beside `force`. The ambient gate
  (`:124-128`) gains the fourth disjunct — `if prompt_gates is None or … or
  run_tags is None` — and the `RunRequest(` construction (`:129-146`) gains
  `run_tags=MappingProxyType(dict(ambient.get("run_tags") or {})) if run_tags is
  None else run_tags`. The docstring "The three **delivery inputs**" (`:110-115`)
  becomes four, worded the same way, because the sentence is load-bearing: it is
  why a caller states them or the ambient dict answers.
- `click_params.build_job_engine_callback` (`app/adapters/click_params.py:1012-1019`)
  gains `run_tags: Mapping[str, str] | None = None` and passes it at the
  `build_request(` call (`:1116-1126`, next to `force=force` at `:1124`);
  `create_job_click_command` (`:1376-1389`) gains it as a keyword-only
  parameter and forwards it to the callback factory. A click **option** is not
  added: the flag is pre-command, parsed by dispatch before the app exists, so a
  job's own parser must never see it (v3 §5.1:168 — "After the job name,
  `--run-tag` would be a job option, and the job's own parser would refuse it").

### 4.7 `_types/run_request.py` — one field, copied by existing code

- `run_tags: Mapping[str, str] = field(default_factory=lambda: _EMPTY)` in the
  delivery-input block (`:195-198`), with a docstring line stating what §5.4
  means: every child gets an exact copy, a child cannot add, change or remove an
  entry (AC18).
- `nested_request` gains **no** code: `run_tags` is not in the reset dict
  (`:364-374`), so `parent.replace(**fields)` (`:376`) keeps the parent's map —
  which is literally "a copy, not a merge" (§5.4:253). The `parent is None`
  branch (`:362-363`) and `from_payload` (`:330-337`) both stay tag-free: a
  payload from a wire door cannot introduce a tag (§5.8).
- `__hash__` (`:232-249`) must **not** include `run_tags`. The docstring already
  gives the reason for excluding mappings (`kwargs`, `group_option_values`), and
  §7:400 binds "Tags never enter `args_hash` or freshness": the fingerprint is
  computed from job kwargs in the `open_run` payload inside `_open_run_record`
  (`executor.py:965`; the method starts `:938`), not from
  the request, so AC27 holds without further code. The obligation is the
  negative one — do not add it.
- `_EMPTY` (`:175`) is reused rather than a second `MappingProxyType({})` per
  instance, so `nested_request`'s copy is one object.

### 4.8 `_engine/executor.py`

`_open_run_record` (`:938-1006`) gains one key in the dict it already builds:

```python
"run_tags": dict(request.run_tags),
```

beside `"force": request.force` (`:1000`). Nothing else: the `try/except
Exception` swallow (`:1004-1006`) keeps its rule — a store that cannot be
written must not turn a good run into a visible failure — and the SQLite path
reaches the same value through `StartAttempt` (§4.10), not through this dict.

### 4.9 Document store

- `_primitives/run_store.py` `open_run` (`:218-247`) needs **no** code: it stores
  the caller's dict as-is (`entry = {k: v for k, v in record.items() if k !=
  "run_id"}` `:233`) after popping `kwargs`/`arguments` (`:240-241`). The key
  arrives, is written, and is never rewritten (`_mutate` on an existing record
  goes through `require_transition` at `:237`).
- `_primitives/document_store.py` `_run_view` (`:269-281`) gains
  `run_tags=dict(record.get("run_tags") or {})` — the `or {}` is AC14/AC30: a
  record written before this feature has no key, and is read as `{}` and never
  rewritten to add it.
- `_DocumentRunReader.recent` (`:214-241`) gains one predicate inside the
  existing `continue` chain (`:227-237`):

  ```python
  if query.tags:
      stored = record.get("run_tags") or {}
      if any(stored.get(key) != value for key, value in query.tags):
          continue
  ```

  and the over-read factor (`:225`) rises from `limit * 8` to a value that
  survives a selective tag filter. The constant is not guesswork any more: eight
  is enough for a job or state filter, and a tag can match one run in a hundred
  — the plan raises it to `max(limit * 32, limit)` and says so in the comment,
  because the failure mode of a too-small factor is a silently short answer, not
  an error. Recorded as D4 (needs maintainer review when a real workload
  disagrees).

### 4.10 Plugin SQLite store

- New file `plugins/substrates/functualize-substrate-sqlite/src/
  functualize_substrate_sqlite/_schema/0005_run_tags.sql`. **The number is 5,
  not the shape's 3**: `_migrations.py:112-117` ships revisions 1–4
  (`runtime_schema`, `step_record_metadata`, `step_attempt`,
  `gate_interactions`), and shape §7 marks `0003_run_tags.sql` *provisional*.
  The header follows `0004_gate_interactions.sql`'s convention:

  ```sql
  -- Revision 0005 — run tags: one row per key per run
  -- Additive only: no existing table or column changes.
  CREATE TABLE run_tags (
      namespace_id TEXT NOT NULL,
      run_id       TEXT NOT NULL,
      key          TEXT NOT NULL,
      value        TEXT NOT NULL,
      PRIMARY KEY (namespace_id, run_id, key),
      FOREIGN KEY (namespace_id, run_id) REFERENCES runs (namespace_id, id)
          ON DELETE CASCADE
  );
  CREATE INDEX run_tags_lookup ON run_tags (namespace_id, key, value);
  ```

- `_migrations.py`: `_load(5, "run_tags")` appended to `SHIPPED_MIGRATIONS`
  (`:112-117`); the docstring (`:101-111`) gains one line. `_CREATED` (`:123-129`)
  already tolerates a revision that only creates objects.
- `_run_sql.py` `SqlRunWriter.start_attempt` (`:87-117`): after the `runs`
  INSERT (`:94-110`), stage one `run_tags` INSERT per key **in the same
  transaction** — shape §5.3:243 — e.g.
  `INSERT INTO run_tags (namespace_id, run_id, key, value) VALUES (?,?,?,?)`
  per sorted key. Retention removes the rows through the cascade; no delete
  statement is added.
- `_readers.py`: `_COLUMNS` (`:45-48`) and the positional `_view` (`:54-67`)
  change **together** or neither does — the projection gains `run_tags`, loaded
  with one grouped query per page
  (`SELECT run_id, key, value FROM run_tags WHERE namespace_id = ? AND run_id IN
  (…)`), never one query per row. `recent` (`:76-93`) gains one
  `EXISTS (SELECT 1 FROM run_tags WHERE namespace_id = ? AND run_id = runs.id AND
  key = ? AND value = ?)` clause per `--tag` in the existing clause loop
  (`:77-87`), before the `LIMIT ?` (`:88-93`) — `run_tags_lookup` serves it.

### 4.11 `_types/persistence.py` and the conformance kit

- `RunView` (`:654-670`) gains `run_tags: Mapping[str, str] = field(default_factory=dict)`;
  `RunQuery` (`:775-783`) gains `tags: tuple[tuple[str, str], ...] = ()`; the
  docstring (`:777`) gains "every tag must match".
- `StartAttempt` (`:499-518`) gains `run_tags: Mapping[str, str] =
  field(default_factory=dict)`. **Defaulted, because nine construction sites
  omit it**: `_engine/recording/run_recorder.py:56`,
  `src/functualize/testing/conformance/capabilities.py:141`,
  `src/functualize/testing/conformance/baseline.py:91`, `:95`, `:272`, `:332`,
  `plugins/substrates/functualize-substrate-sqlite/tests/test_run_sql.py:59`,
  `tests/test_legacy_import.py:101`, `tests/test_readers.py:191`. `run_recorder.py:20-22`
  says why nothing breaks today: "Nothing constructs these values anywhere in
  the tree yet, so the mapping is derived from the contract, not copied from a
  call site" — the `StartAttempt` half of this feature is latent until a store
  uses it.
- One new case in `src/functualize/testing/conformance/baseline.py`, appended to `BASELINE`
  (`:604-632`) before the closing paren: start a run with
  `StartAttempt(..., run_tags={"k": "v"})`, read it back through
  `store.runs.run(run_id)`, assert the map — and assert a run started **without**
  the argument reads `{}`. Both stores answer it, which is AC16's parity rule in
  the one place the repo already enforces parity across substrates.

`tests/test_public_api_surface.py:209`/`:224` pins the *names* `StartAttempt` and
`RunQuery`; new fields on an existing name are safe, a new exported name is not —
so `run_tags` is a field, never a type.

### 4.12 Read side — projection, CLI, MCP

- `app/_run_view.py` `_describe` (`:138-156`) gains
  `"run_tags": dict(record.get("run_tags") or {})` — after `force` (`:152`) and
  before `group_option_values`, so the dict's insertion order stays
  "delivery-ish first". The projection is still the only one (§1 of that module):
  the CLI renders it, MCP returns it, and neither reads a store.
- `list_runs` (`:181-232`) gains `tags: Sequence[tuple[str, str]] = ()` beside
  the existing filters, and one predicate before `_describe`:

  ```python
  if tags and any(
      (record.get("run_tags") or {}).get(k) != v for k, v in tags
  ):
      continue
  ```

  Because it sits before the `rows.append`/`break` (`:229-230`), `--limit` stays
  "applied **after** filtering" (`:209-210`) — AC21, and the same rule
  `docs/cli/run.md:51-52` already states.
- `_cli/builtins.py`: `run_list` gains
  `@click.option("--tag", "tag", multiple=True, metavar="KEY:VALUE",
  help="…")` (`:1902-1928` block) and passes `tags=parse_filter_list(tag)` —
  the same `parse_tag` from `_cli/run_tags.py`, refusing a malformed filter with
  exit 2 (§5.6:306) — plus, in the table branch (`:1963-1971`), the tags
  rendered **last, sorted by key, `key:value` space-separated** (AC23):

  ```python
  tags_text = " ".join(f"{k}:{it['run_tags'][k]}" for k in sorted(it["run_tags"]))
  ...
  f"{it['run_id']}  {it['job']}  {it['state']}  {it['surface'] or '-'}  {took}"
  + (f"  {tags_text}" if tags_text else "")
  ```

  An untagged row is byte-identical to today's (AC23, AC31). The JSON branch
  (`:1955-1959`) needs no edit — it dumps `{"runs": items}` and the projection
  already carries the key.
- `run_show` (`:1989-2018`): the text branch gains a `run_tags:` line in the
  fixed-key loop (`:2007-2008`) area, printing `-` when empty so the line is
  always present; the JSON branch (`:2004-2006`) gains nothing, because
  `describe_run`/`run_tree` already return the projection plus `run_tags`
  (AC26).
- MCP: nothing to add. `plugins/adapters/functualize-mcp/src/functualize_mcp/
  _workflow_tools.py` `_list_runs` (`:500-517`) calls the same `list_runs`
  (imported `:50`, registered `:215`), so every returned run carries `run_tags`
  (AC25) and the tool takes **no** tag input in v1 (§5.8).

### 4.13 Docs and changelog

- `docs/cli/run.md`: the `func builtin run list` synopsis (`:35-38`) gains
  `[--tag KEY:VALUE ...]`; a new `### Filtering by tag` section after
  `### Filtering by state` (`:65`) covering AND semantics, exact/case-sensitive
  matching, the three sources of a tag (flag, env, global config), and the
  plain-text/no-secrets rule R2 requires; the `## JSON` section (`:107-112`)
  notes `run_tags`; the `## MCP` table (`:122-126`) notes that the tool inherits
  the projection and takes no tag input.
- `docs/api/types.md`: the `GLOBAL_OPTIONS_ALWAYS_VALUE` row (`:156`) gains
  `--run-tag`. The `GLOBAL_BOOL_FLAGS` row (`:157`) must stay unchanged —
  `--run-tag` takes a value.
- `CHANGELOG.md`: `### Added — <one sentence>` above the existing
  `### Added — gate answers are durable…` (`:10`), in the file's style (a
  heading sentence, then one paragraph).

## 5. Blast radius (pass 3b)

| Symbol | References (rg / serena) | Effect |
|---|---|---|
| `RunRequest` | 12 construction sites in 10 files (`spec.md` §1.2) + every `nested_request` caller (4) | One new defaulted field: no site changes, `from_payload`/`replace` keep working. A site that passes it positionally would break — none does (all keyword). |
| `nested_request` | `_engine/workflow_orchestrator.py:95`, `_engine/capabilities/invoke.py:473` and `:875`, `_engine/dependency_runner.py:150` | No code change; the copy now carries `run_tags`. Covered by a test that asserts the child's map equals the parent's. |
| `build_request` | `click_params.py:1116` (both builders), `tests/adapters/test_request_builder.py` (both paths), `tests/workflow/test_workflow_surface_parity.py` | One new keyword with a `None` default; the ambient-path tests gain a case, existing calls unaffected. |
| `StartAttempt` | 9 construction sites — `run_recorder.py:56`, `conformance/capabilities.py:141`, `conformance/baseline.py:91`, `:95`, `:272`, `:332`, `test_run_sql.py:59`, `tests/test_legacy_import.py:101`, `tests/test_readers.py:191` | Field is defaulted: every existing construction compiles and reads `{}`. Pinned by name at `tests/test_public_api_surface.py:209`. |
| `RunQuery` | definition `_types/persistence.py:775-783`; consumers `_readers.py:76`, `_primitives/document_store.py:214` | New defaulted `tags` tuple; every existing construction is unchanged. |
| `RunView` | definition `_types/persistence.py:653-670`; the two constructors `_primitives/document_store.py:269-281` (`_run_view`) and `_readers.py:54-67` (`_view`), over `_COLUMNS` (`_readers.py:42-48`) | New defaulted field; the two constructors and `_COLUMNS` are updated together. |
| `list_runs` | `builtins.run_list:1947`, MCP `_list_runs:500`, `tests/integration/test_run_view.py` | New defaulted `tags` argument; the table rendering gains a conditional suffix only. |
| `GLOBAL_OPTIONS_ALWAYS_VALUE` | `_cli/dispatch.py:154`, `:159`, `:327-345`, `_cli/completions/data.py`, `_cli/tui/bar.py`, `_cli/tui/sync.py`, `app/adapters/click_params.py`, `tests/types/test_flag_grammar_roundtrip.py` | One member added; the roundtrip test enumerates membership and will need the new name in its expectation. |
| `read_global_config` | `_cli/config.py:80` (definition), called from `resolve_cli_config` (`:447`) at `:484`; `_cli/builtins.py:2311` (`config_show`, `:2301`); `tests/cli/test_cli_config.py` | `[run]` becomes a recognized section; a config file with `[run] tags` now round-trips instead of vanishing. Existing tests assert other sections — unaffected. |
| `SHIPPED_MIGRATIONS` | plugin `_migrations.py`, `tests/…/test_migrations.py`, `test_legacy_import.py` | Revision 5 appended; a database at 4 migrates forward. The "latest revision" assertions in the plugin's tests move from 4 to 5. |

## 6. Decisions

- **D1 (taken, from the shape — with one implementation correction):** three
  layers, lowest→highest, per-key merge, no project-file layer. The correction:
  `FUNCTUALIZE_RUN_TAGS` is read by `_cli/run_tags.py` directly, **not** through
  `resolve_env_overrides` (`_cli/config.py:161`). The shape (§5.1:171) names that
  mapper as the env spelling; measured, it would split `RUN_TAGS` at the first
  `_` (`:206`) into a single unvalidated string and is only reachable after
  dispatch has already had to refuse a malformed tag. Same behaviour, different
  reader; recorded here because it is a deviation from the page.
- **D2 (taken):** no `DeliveryInputs` value object. The clump of four delivery
  inputs is real (*Data Clumps*, §2), but extracting it rewrites 12 `RunRequest(`
  sites and both builders for zero behaviour change, and the repo's Rule of Three
  already tolerates the four. Revisit when a fifth input arrives.
- **D3 (taken):** the 32-tag cap is a declared limit with its own message, per
  shape Risk 4, so AC7 is testable rather than discovered.
- **D4 (needs maintainer review):** the document reader's over-read factor rises
  `8 → 32` (`document_store.py:225`). The number is a heuristic and its failure
  mode is a short answer on a sparse index, not an error. A maintainer who wants
  a different factor changes one constant; a maintainer who wants exactness
  replaces the over-read with a store-level predicate, which is a larger change
  than this feature.
- **D5 (needs maintainer review):** the refusal messages in §5.6 are
  *provisional* per shape §7 — the wording is fixed by this plan (contracts C7
  `:243-260`) so the tests can assert it, and changing a sentence later changes
  a test.
- **D6 (taken):** another door wanting tags first is out of v1 (§5.8). HTTP,
  Lambda and MCP take **no** `run_tags` input; MCP *reads* them because it shares
  the projection. A door added later writes the same request field — the
  mechanism does not change.

## Surviving smells

| Smell (catalogue) | Where | Why accepted | Maintainer review? |
|---|---|---|---|
| *Shotgun Surgery* | a delivery input still costs one edit in four `_cli/main.py` handlers, two builders and `build_request` | The four handlers exist because four doors exist; collapsing them is a `_cli/main.py` restructure, not a run-tag change. This feature pays the cost once and documents it in the §2 table so the next input's author sees the tour. | No — accepted with the tour named |
| *Primitive Obsession* | the run record stays a `dict[str, Any]` across five files | Replacing it with a typed record is the whole durable-run layer's shape, and `RunStore.open_run`'s docstring (`:219-231`) deliberately accepts a dict. The new key follows the existing convention rather than starting a second one. | No |
| *Divergent Change* | four hand-maintained flag lists | `GLOBAL_OPTIONS_WITH_VALUE` already aliases `GLOBAL_OPTIONS_ALWAYS_VALUE` (`flag_grammar.py:98`), so the real count is three. Deriving the other two from one table is a `_cli/dispatch.py` refactor with its own risk (`__slots__` is a typed declaration, not a list). | **Yes** — flag it to a maintainer as a follow-up, do not do it here |
| *Duplicate Code* | the tag predicate exists in two stores (`document_store.recent`, `_readers.recent`) in two different shapes (a Python `continue` vs an SQL `EXISTS`) | The dependency runs one way only — the plugin depends on core (`plugins/substrates/functualize-substrate-sqlite/pyproject.toml:19-21`), and core declares no plugin dependency (`pyproject.toml:22-32`) and never imports one. A shared helper would therefore have to live in core and be called from the plugin, which no contract forbids — but the two stores' *filters* genuinely differ (an in-memory scan over a document vs a `WHERE` clause), so the shared part would be a predicate wrapper over two unlike readers. Parity is enforced instead by the conformance kit (§4.11), which is the repo's answer to this smell. | No |
| *Data Clumps* | `prompt_gates`/`output_format`/`force`/`run_tags` travel together | D2: the extraction is a 12-site rewrite with no behaviour change. | **Yes** — D2 is the recorded decision |

## 7. Risks

- **R1 — the config layer is declared but read as nothing.** Mitigation:
  §4.4's two registrations, and an AC11 test that a broken `[run] tags` list
  produces the refusal rather than a silent skip. Residual: a user who writes
  `[run] tags` in `.functualize.toml` gets no warning (§5.8 — deliberately not
  read; the project file is not a tag source, so there is nothing to warn
  about). AC12 pins that.
- **R2 — a tag holds a secret.** Mitigation: docs state plain text (§4.13), the
  shape's own §5.5 does too, and no job can read a tag (§4.7/§4.8: the value is
  written to the record and never enters `RunContext`, kwargs or `args_hash` —
  AC28). Residual: the user can still type one, which the docs answer.
- **R3 — a malformed `FUNCTUALIZE_RUN_TAGS` stops every command.** Intended and
  loud (§5.2, §7:397): exit 2, nothing runs, nothing recorded. A harness that
  exports a broken value must be fixed by its owner, not silently ignored. The
  risk is a lost working session behind a typo — answered by the message naming
  the env var and the item, and by the empty-item skip (AC4) that makes the
  common `${VAR:+…}` idiom safe.
- **R4 — tag growth.** 32 keys per run, refused with its own message (AC7).
  Residual: 32 × 256 characters is the worst-case record, which is a document
  key the store already handles.
- **R5 — another door wants tags first.** Out of v1 (§5.8); the mechanism (one
  request field) is door-agnostic, so a later door adds an *input*, not a
  mechanism.
- **R6 — the over-read starves a sparse tag filter** (D4). The factor is
  documented and the failure is a short answer, not a wrong one; the test builds
  a deliberately sparse project (`spec.md` AC21) so a future reduction of the
  constant fails loudly.
- **R7 — a migrated database at revision 4 with runs already in it.** The new
  table is additive and every pre-feature run has no rows, which reads as `{}`
  (AC15 + AC30 together). Residual: a rollback to revision 4 leaves a table
  nothing reads — `_CREATED` (`:123-129`) tolerates that.
