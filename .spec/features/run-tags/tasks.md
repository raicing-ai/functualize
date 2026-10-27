# run tags — Tasks

Base: `origin/master` `11ed0e82`. Branch: `sdd/run-tags`.
Spec: `spec.md` (AC1–AC34). Contracts: `contracts.md` (C1–C8). Plan: `plan.md`.

Authoring-time gate runs (2026-10-26, at `11ed0e82`):

- `rg -n 'run_tags|RUN_TAGS|run-tag' -g '*.py' -g '*.sql' src plugins` →
  **no output, rc=1** (the feature does not exist yet).
- `rg -n 'RunRequest\(' src plugins -g '*.py'` → **12 matches in 10 files**.
- `rg -n 'def run_list' src/functualize/_cli/builtins.py` → **1 hit**,
  line 1930.
- `rg -n '_load\(' plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/_migrations.py`
  → revisions 1–4, so the new file is `0005_run_tags.sql`.
- `uv run lint-imports` → 7 kept, 0 broken.
- `func --run-tag harness:claude release` → `Error: Unknown command
  'run-tag'.`, exit 1 (the flag becomes the command name today).
- `func builtin run list --tag session-id:7f3a` → `Error: No such option
  '--tag'. Did you mean '--state'?`, exit 2.

## Wave 0

- [x] **1.1 — One tag grammar, one merge, one refusal type** (C1, C7;
      AC3–AC7, AC9 first half)
  - **[F]** `src/functualize/_cli/run_tags.py` (new),
    `tests/cli/test_run_tags.py` (new)
  - **Inputs:** `plan.md` §4.1; the shape's grammar of one tag (§5.1:169) and its
    §5.6 table (`:295-309`); `contracts.md` C1/C7.
  - **Do:** stdlib only — no `functualize._types`, no `_primitives`, no
    `_engine`, and **not** `_types.flag_grammar` (it must stay outside
    `EXPECTED_CONSUMERS` in `tests/types/test_flag_grammar_consumer_count.py`).
    `RunTagError(message)`; `parse_tag(text, *, where)` splitting on
    `text.partition(":")` — so `url:https://x` keeps its second colon — and
    refusing each §5.6 row with its own sentence; `parse_env(raw)` splitting on
    `,`, trimming each item, **skipping empty items**, refusing a duplicate key
    inside the layer naming both; `parse_config_list(items)` over the TOML list,
    refusing a non-list, a non-string item and a duplicate; `parse_flag_list`,
    the same rules over the repeated flag; `merge_layers(*layers)` dict-merging
    lowest→highest into a `MappingProxyType`, then applying `MAX_TAGS = 32`.
    Constants `TAG_KEY_RE = re.compile(r"[a-z0-9][a-z0-9._-]*")`,
    `MAX_VALUE_LEN = 256`.
  - **Tests (unit):** AC3 `url:https://x` → `("url", "https://x")`;
    AC4 `"${unset}, model:opus"` → one tag and `",,"` → none; AC5
    `--run-tag 'Model:opus'` → `Error: --run-tag 'Model:opus': a run tag key
    uses a-z, 0-9, '.', '_' and '-'.`; AC6 a 256-char value accepted and 257
    refused; AC7 32 keys accepted and 33 refused; the eleven parse-level §5.6
    rows each assert message **and** `isinstance(exc, RunTagError)` (no bare
    `str`); AC9 in-layer duplicate names the layer and both items; cross-layer
    duplicate merges (higher wins) and is **not** an error; every message names
    its source (`--run-tag`, `FUNCTUALIZE_RUN_TAGS`, or the config path).
  - **Invariants:** no module-level mutable state; every public function is
    pure; the merged result is a `MappingProxyType` (a caller cannot mutate a
    request's tags); no exception escapes other than `RunTagError`.
  - **Acceptance:** `uv run pytest tests/cli/test_run_tags.py -q` green;
    `uv run python -c "import functualize._cli.run_tags"` clean;
    `rg -n 'flag_grammar' src/functualize/_cli/run_tags.py` → 0 hits.
  - **Reachability:** modules only, no production caller yet —
    **TRANSITIONAL(run-tags/1.1, 3.1)**. Brought live by 3.1, which calls
    `merge_layers` before boot.

- [x] **1.2 — `--run-tag` is a value-taking global flag** (C2; AC10 first half)
  - **[F]** `src/functualize/_types/flag_grammar.py`,
    `src/functualize/_cli/dispatch.py`,
    `tests/types/test_flag_grammar_roundtrip.py`,
    `tests/_cli/test_pre_boot_arity_parity.py`,
    `tests/_cli/test_dispatch_preservation.py`,
    `tests/cli/test_global_options.py`
  - **Inputs:** `plan.md` §4.2, §4.3; `flag_grammar.py:46-65`, `:98`,
    `:104-113`; `dispatch.py:238-261`, `:375-396`, `:430-474`, `:477-538`,
    `:142-191`.
  - **Do:** add `"--run-tag"` to `GLOBAL_OPTIONS_ALWAYS_VALUE` only — never to
    `GLOBAL_BOOL_FLAGS`. Add `"run_tags"` to `_OptionAccumulator.__slots__` and
    `self.run_tags: list[str] | None = None` to `__init__`. Add the append
    branch to `_assign_option` using the `--import-libs` idiom (`:490-493`):
    allocate the list on first sight, append the raw spelling. Add
    `run_tags: list[str] | None = field(default=None)` to `ParsedGlobalOptions`
    beside `force` and pass `run_tags=state.run_tags` in the constructor call.
    No parsing here — dispatch collects spellings, 1.1 judges them.
    `detect_mode` gets no edit; its skip loop already consults the set.
  - **Tests (unit):** flag roundtrip enumerates the new member; the arity
    parity test gets `--run-tag x:y <job>` → `first_positional_index == 2`
    (the `--perf-report text job_name` case at
    `tests/_cli/test_dispatch_preservation.py:387-404` is the template);
    `--run-tag=x:y` (the `=` form) lands in the same list; a missing value
    (`--run-tag --force`) is the existing missing-value refusal; two repeats
    accumulate in order; `func --run-tag harness:claude release` no longer
    reaches `Unknown command` (assert `detect_mode` returns JOB).
  - **Invariants:** `GLOBAL_OPTIONS_WITH_VALUE` is an alias (`:98`) — one edit
    covers both names; `GLOBAL_BOOL_FLAGS` membership is unchanged;
    `--run-tag` consumes a value in `detect_mode`, `--option=value` detection
    and the "move it before the group" advice alike.
  - **Acceptance:** `uv run pytest tests/types
    tests/_cli/test_pre_boot_arity_parity.py tests/cli/test_global_options.py -q`
    green; `uv run python -c "from functualize.types import
    GLOBAL_OPTIONS_ALWAYS_VALUE as g; assert '--run-tag' in g"` silent.
  - **Reachability:** `_run_cli` → `_extract_global_options` →
    `_assign_option`; measured live after 3.1 (`func --run-tag a:b release`).

- [x] **1.3 — `[run] tags` is a recognized global-config section** (C3;
      AC11, AC12)
  - **[F]** `src/functualize/_cli/config.py`, `tests/cli/test_cli_config.py`
  - **Inputs:** `plan.md` §4.4; `_cli/config.py:26` (`_RECOGNIZED_SECTIONS`),
    `:34` (`_RECOGNIZED_KEYS`), `:67` (the neighbouring `vault` entry), and
    `:80-158` (`read_global_config`; the silent section skip at `:131-133`, the
    key warning at `:148-152`).
  - **Do:** add `"run"` to `_RECOGNIZED_SECTIONS` and
    `"run": frozenset({"tags"})` to `_RECOGNIZED_KEYS`, with the one-line
    comment the neighbouring `vault` entry carries (read here, judged by
    `_cli/run_tags.py`, never imported by `_app`). Do **not** route
    `FUNCTUALIZE_RUN_TAGS` through `resolve_env_overrides` (plan D1).
  - **Tests (unit):** `read_global_config` round-trips `[run] tags = ["a:b"]`;
    an unknown key inside `[run]` still warns with the existing sentence; a
    `[run]` table in `.functualize.toml` is not read and produces no `[run]`
    entry (AC12 — the project file is not a tag source); `[run] tags` as a
    string instead of a list is returned verbatim, unjudged, so 1.1 refuses it.
  - **Invariants:** `read_global_config`'s signature and its return shape are
    unchanged; no other section's filtering changes; `config path` /
    `info --json` (which read through this function) stay truthful.
  - **Acceptance:** `uv run pytest tests/cli/test_cli_config.py -q` green;
    `uv run python -c "from functualize._cli.config import _RECOGNIZED_KEYS;
    assert _RECOGNIZED_KEYS['run'] == frozenset({'tags'})"` silent.
  - **Reachability:** `resolve_cli_config` (`_cli/config.py:447`) →
    `read_global_config` (`:484`); the value is consumed by 3.1.

## Wave 1

- [x] **2.1 — `RunRequest.run_tags`, copied verbatim to every child** (C4;
      AC17, AC18, AC27, AC28)
  - **[F]** `src/functualize/_types/run_request.py`,
    `tests/engine/test_nested_delivery_inputs.py`
  - **Inputs:** `plan.md` §4.7; `_types/run_request.py:175`, `:195-198`,
    `:232-249`, `:340-376`; `contracts.md` C4.
  - **Do:** add `run_tags: Mapping[str, str] = field(default_factory=lambda:
    _EMPTY)` to the delivery-input block, docstring line stating that a child
    receives an exact copy and cannot add, change or remove an entry. Add
    **nothing** to `nested_request` — `run_tags` is absent from the reset dict
    (`_types/run_request.py:364-374`), so `parent.replace(**fields)` (`:376`)
    already copies it. Do **not** add it to `__hash__` (`:232-249`) or to
    `from_payload` (`:330-337`).
  - **Tests (unit):** a request with `{"harness":"claude"}` nests into a child
    whose map is equal and is not the same object mutation-wise (the child's
    map is frozen — assigning raises `TypeError`); a caller-stated
    `run_tags=` override replaces the whole map; every child kind is covered —
    workflow step, `Invoke`, `rc.invoke_parallel`, dependency, nested workflow
    (AC17); `nested_request` adds, changes and removes nothing (AC18); a
    payload-built request carries `{}` (the wire doors take no tag input);
    `hash()` of two requests differing only in tags is defined and equal
    (AC27's precondition — tags are not in the fingerprint).
  - **Invariants:** the reset dict is unchanged; `parent is None` still yields
    `RunRequest(**changes)`; no `run_tags` in `__hash__`; the field defaults, so
    all 12 construction sites compile untouched.
  - **Acceptance:** `uv run pytest tests/engine/test_nested_delivery_inputs.py
    -q` green; `uv run pytest tests/test_public_api_surface.py -q` green;
    `rg -n 'run_tags' src/functualize/_types/run_request.py` → 2 hits (field,
    docstring).
  - **Reachability:** `_run_cli` → handler → `build_request` → `RunRequest`;
    live proof lands in 3.1.

- [ ] **2.2 — The fourth delivery input through both builders** (C5; AC1)
  - **[F]** `src/functualize/app/adapters/_request_builder.py`,
    `src/functualize/app/adapters/click_params.py`,
    `tests/adapters/test_request_builder.py`
  - **Inputs:** `plan.md` §4.6; `_request_builder.py:91-102`, `:110-115`,
    `:124-146`; `click_params.py:1014-1019`, `:1116-1126`, `:1376-1388`.
  - **Do:** `build_request(..., run_tags: Mapping[str, str] | None = None)`;
    the ambient gate (`:124-128`) gains the fourth disjunct; the `RunRequest(`
    call passes `run_tags` (ambient value frozen into a `MappingProxyType`).
    Reword "The three **delivery inputs**" (`:110-115`) to four, same sentence
    shape. `build_job_engine_callback` and `create_job_click_command` each gain
    the keyword-only parameter and forward it. Add **no** Click option: the flag
    is pre-command.
  - **Tests (unit):** a stated map reaches the request unchanged; `None` takes
    the ambient dict's map; a mapping passed as a plain dict is not aliased
    (mutating the caller's dict afterwards changes nothing); neither builder
    declares a `--run-tag` option (`option_names` assertion, AC10's structural
    half).
  - **Invariants:** `app/adapters/**` still imports no `_engine` module
    (`pyproject.toml:448-463`); the three existing delivery inputs behave
    identically when `run_tags` is omitted.
  - **Acceptance:** `uv run pytest tests/app tests/cli -q` green on the touched
    files; `uv run lint-imports` → 7 kept, 0 broken.
  - **Reachability:** `_handle_job` → `build_job_engine_callback` →
    `build_request`; exercised end-to-end by 3.1.

## Wave 2

- [ ] **3.1 — `_cli/main.py`: merge before boot, refuse with exit 2, forward
      to every door** (C2, C3; AC1, AC2, AC8, AC9 second half, AC10)
  - **[F]** `src/functualize/_cli/main.py`, `tests/cli/test_run_tags_pre_boot.py`
    (new), `tests/cli/test_run_tags_layers.py` (new)
  - **Inputs:** `plan.md` §4.5; `main.py:229-247`, `:252-288`, `:410-414`,
    `:575-582`, `:959`, `:1110`, `:1298-1310`, `:1353-1364`, `:1670-1677`,
    `:2124-2140`, `:2234-2235`, `:2240-2283`, `:2289-2295`, `:2297-2329`,
    `:2331-2358`.
  - **Do:** after `_extract_global_options` (`:2124`) and before discovery,
    compute `run_tags = merge_layers(parse_config_list(...),
    parse_env(os.environ.get("FUNCTUALIZE_RUN_TAGS", "")),
    parse_flag_list(global_opts.run_tags))` in a `try` whose `RunTagError`
    handler prints `Error: {exc}` to stderr and raises
    `SystemExit(ExitCode.USAGE)` — **2**, not the `:252-288` block's 1. Forward
    `run_tags=run_tags` at the SINGLE_FILE (`:2240-2246`), JOB
    (`:2254-2264`), `_handle_group` (`:2272-2283`) and UNKNOWN `_handle_job`
    (`:2315-2325`) calls, and add the keyword to the four handler signatures
    (`_handle_bare` `:575-582` gains its first one, defaulting to `None`).
    BUILTIN mode gets no edit.
  - **Tests (CliRunner + subprocess, isolated HOME/XDG):** AC1 one flag, exit
    0, one tagged run in `run list --format json`; AC2 config `{host:laptop}` +
    env `{tier:2, model:opus}` + flag `{model:sonnet}` → `{host:laptop,
    tier:2, model:sonnet}`; AC8 each refused spelling → its message, exit 2,
    the job body never runs (a job that writes a sentinel file does not write
    it) and `run list --format json` is unchanged; AC9 cross-layer duplicate
    merges while an in-layer duplicate is refused naming the layer; AC10
    `func --run-tag a:b builtin run list` → `Error: No such option
    '--run-tag'.`, exit 2; a malformed `FUNCTUALIZE_RUN_TAGS` blocks every
    mode, including `func builtin info`, with exit 2 (R3, intended).
  - **Invariants:** no tag is parsed after boot — the merge is complete before
    the app object exists; the `:252-288` refusals keep exit 1; BUILTIN's
    refusal stays Click's, not ours.
  - **Acceptance:** `uv run pytest tests/cli/test_run_tags_pre_boot.py
    tests/cli/test_run_tags_layers.py -q` green;
    `rg -n 'merge_layers' src/functualize/_cli/main.py` → 1 hit;
    `rg -n 'run_tags' src/functualize/_cli/main.py` → ≥ 10 hits (four
    signatures, five forwards, the merge).
  - **Reachability:** live: `func --run-tag harness:claude release` then
    `func builtin run list --format json` shows the map. Commit, delete the
    merge call, watch AC1 fail, restore.

- [ ] **3.2 — The record carries the map, in both stores' write path** (C6;
      AC13, AC19, AC27)
  - **[F]** `src/functualize/_engine/executor.py`,
    `tests/engine/test_run_record_run_tags.py` (new)
  - **Inputs:** `plan.md` §4.8, §4.9; `executor.py:938-1006` (`:959`, `:1000`,
    `:1004-1006`); `_primitives/run_store.py:218-247` (`:233`, `:240-241`);
    `contracts.md` C6.
  - **Do:** one key in the dict `_open_run_record` already builds —
    `"run_tags": dict(request.run_tags)` beside `"force": request.force`
    (`_engine/executor.py:1000`). Nothing else: `RunStore.open_run` stores the
    dict as-is, and the record is never rewritten (`require_transition` at
    `run_store.py:237`).
  - **Tests (unit + integration):** AC13 a run started with three tags has
    exactly those three in `store.get_run(run_id)["run_tags"]`; AC27 the same
    job with and without tags yields an identical `args_hash` and the second
    invocation reports a cache hit / fresh-skip as it would untagged; AC19 a
    real `func coverage report` subprocess run inside a job is tagged with the
    parent's map **and** has no `parent_run_id`; the `except Exception` swallow
    still keeps a failing store from failing the run (fake store raising in
    `open_run` → run still succeeds).
  - **Invariants:** no tag reaches `RunContext`, job kwargs, return value or
    exit code (AC28 — asserted on the job's own observed arguments); the
    record's other keys are untouched; `args_hash` is still computed from job
    kwargs only.
  - **Acceptance:** `uv run pytest tests/engine/test_run_record_run_tags.py -q`
    green; `rg -n '"run_tags"' src/functualize/_engine/executor.py` → 1 hit.
  - **Reachability:** live: start a tagged run, then
    `func builtin run show <id> --format json` → the map is present (read side
    lands in 5.2/6.1, so this step pairs with them).

## Wave 3

- [ ] **4.1 — Peer types and one conformance case for both stores** (C6;
      AC16, AC30, AC34 first half)
  - **[F]** `src/functualize/_types/persistence.py`,
    `src/functualize/testing/conformance/baseline.py`
  - **Inputs:** `plan.md` §4.11; `persistence.py:499-518`, `:653-670`,
    `:775-783`; `src/functualize/testing/conformance/baseline.py:91`, `:95`,
    `:272`, `:332`, `:604-632`, `:635-648`;
    `_engine/recording/run_recorder.py:20-22`, `:56-64`.
  - **Do:** `StartAttempt.run_tags: Mapping[str, str] =
    field(default_factory=dict)` (**defaulted** — nine sites omit it, the two
    conformance ones above plus `_engine/recording/run_recorder.py:56`,
    `testing/conformance/capabilities.py:141`, `test_run_sql.py:59`,
    `tests/test_legacy_import.py:101`, `tests/test_readers.py:191`);
    `RunView.run_tags: Mapping[str, str] = field(default_factory=dict)`;
    `RunQuery.tags: tuple[tuple[str, str], ...] = ()` with the docstring gaining
    "every tag must match". One new named check appended to `BASELINE` before
    the closing `)` (`testing/conformance/baseline.py:632`): start a run with
    two tags, read it back through `store.runs.run(run_id)`, assert the map;
    start a second with no argument and assert `{}`.
  - **Tests (unit):** the new conformance case runs under both substrates
    (document + SQLite); construction with three positional arguments still
    works (`testing/conformance/capabilities.py:140-142`); a
    `RunQuery(tags=(("k","v"),))` is hashable and frozen.
  - **Invariants:** `tests/test_public_api_surface.py:209`/`:224` pins the
    *names* — fields only, no new exported type; every existing construction
    site is untouched and reads `{}`.
  - **Acceptance:** `uv run pytest
    plugins/substrates/functualize-substrate-sqlite -q -k conformance` green;
    `uv run pytest tests/test_public_api_surface.py -q` green.
  - **Reachability:** `run_baseline` is invoked by the plugin suite and by
    `tests/` conformance runs; live proof is 5.1's SQLite path.

- [ ] **4.2 — The document store's projection and tag filter** (C6; AC14,
      AC30, AC34)
  - **[F]** `src/functualize/_primitives/document_store.py`,
    `tests/integration/test_run_view.py`
  - **Inputs:** `plan.md` §4.9; `document_store.py:210-241` (`:221`, `:223-225`,
    `:227-237`, `:238-241`), `:269-281`; `contracts.md` C6 `:188-191`.
  - **Do:** `_run_view` (`:269-281`) gains `run_tags=dict(record.get("run_tags")
    or {})`; `_DocumentRunReader.recent` gains one predicate inside the existing
    per-field `continue` chain —
    `if query.tags: stored = record.get("run_tags") or {}; if any(stored.get(k)
    != v for k, v in query.tags): continue` — and the over-read factor (`:225`)
    rises from `limit * 8` to `max(limit * 32, limit)` with the comment saying
    why (plan D4: a too-small factor yields a short answer, not an error).
  - **Tests (unit/integration):** a record written **before** this feature (no
    key) reads as `{}` and is never rewritten — `get_run` after the read is
    byte-equal to before it (AC14, AC30); AND semantics over two tags; a sparse
    index (200 untagged runs, 3 tagged, `limit=2`) still returns 2 (the
    over-read headroom); a scope record carries **no** `run_tags` while its runs
    do (AC34).
  - **Invariants:** `RunQuery`'s existing filters are unchanged; the `limit` is
    still applied after every filter; no per-row store call is added.
  - **Acceptance:** `uv run pytest tests/integration/test_run_view.py -q` green.
  - **Reachability:** `func builtin run list` on the default document store —
    live in 6.1.

## Wave 4

- [ ] **5.1 — Revision 5: the `run_tags` table, its writer and its reader**
      (C6; AC15, AC16, AC33)
  - **[F]** `plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/_schema/0005_run_tags.sql`
    (new),
    `plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/_migrations.py`,
    `.../_run_sql.py`, `.../_readers.py`,
    `plugins/substrates/functualize-substrate-sqlite/tests/test_migrations.py`,
    `.../test_run_sql.py`, `.../test_readers.py`
  - **Inputs:** `plan.md` §4.10; `_migrations.py:95-111`, `:112-117`,
    `:123-129`; `_run_sql.py:87-117` (`:94-110`); `_readers.py:45-48`,
    `:54-67`, `:76-93`; `0004_gate_interactions.sql` (header convention).
  - **Do:** create the SQL file with the `-- Revision 0005 — run tags` header,
    `CREATE TABLE run_tags (namespace_id, run_id, key, value, PRIMARY KEY
    (namespace_id, run_id, key), FOREIGN KEY (namespace_id, run_id) REFERENCES
    runs (namespace_id, id) ON DELETE CASCADE)` and
    `CREATE INDEX run_tags_lookup ON run_tags (namespace_id, key, value)`.
    Append `_load(5, "run_tags")` to `SHIPPED_MIGRATIONS` and one docstring
    line. `start_attempt` stages one `INSERT INTO run_tags …` per key in the
    **same** transaction as the `runs` INSERT. `_readers._COLUMNS` and the
    positional `_view` change together; `recent` gains one `EXISTS (SELECT 1
    FROM run_tags WHERE namespace_id = ? AND run_id = runs.id AND key = ? AND
    value = ?)` per tag in the existing clause loop, before the `LIMIT ?`; the
    page's maps load with one grouped `SELECT run_id, key, value … WHERE run_id
    IN (…)`, never per row.
  - **Tests (unit):** AC15 a database at revision 4 with existing runs
    migrates to 5, gains the table and the index, and one row per key; AC16 the
    store and the document store return identical run ids **and** identical
    maps for the same writes; a tag filter narrows to the same set as the
    document store; `limit` applied after the filter; deleting a run drops its
    rows through the cascade (retention test); AC33 an update attempted through
    the store's own write path is refused as a programming error, not applied
    and not a user message.
  - **Invariants:** the migration is additive — no existing table or column
    changes, and revision 4 remains a valid rollback target (`_CREATED`);
    `_COLUMNS` and `_view` stay positional-consistent; the plugin imports no
    new core module.
  - **Acceptance:** `uv run pytest
    plugins/substrates/functualize-substrate-sqlite -q` green;
    `rg -n 'run_tags' plugins/substrates/functualize-substrate-sqlite/src` → the
    SQL file, `_migrations.py`, `_run_sql.py`, `_readers.py` only.
  - **Reachability:** point `runtime_store.url` at SQLite and run 6.1's live
    transcript; the conformance case from 4.1 covers both stores.

- [ ] **5.2 — `app/_run_view.py`: the projection and the query** (C6; AC21,
      AC22)
  - **[F]** `src/functualize/app/_run_view.py`,
    `tests/integration/test_run_view.py`
  - **Inputs:** `plan.md` §4.12; `_run_view.py:1-40`, `:128-156` (`:152`),
    `:181-232` (`:188`, `:209-210`, `:218-228`, `:229-230`).
  - **Do:** `_describe` gains `"run_tags": dict(record.get("run_tags") or {})`
    after `force`; `list_runs` gains `tags: Sequence[tuple[str, str]] = ()` and
    one predicate before `_describe` — `if tags and any((record.get("run_tags")
    or {}).get(k) != v for k, v in tags): continue` — so the limit stays last.
    Modules docstring's "One projection, thin callers" still holds: no second
    shape is introduced.
  - **Tests (integration):** AC22 every row carries `run_tags` and a
    pre-feature record's row carries `{}`; AC21 `--scope` + two `--tag` +
    `limit=2` returns two matching rows, proving the limit is applied after all
    filters; an untagged row's dict differs from today's only by the new key.
  - **Invariants:** the existing job/surface/scope/state predicates and the
    `max(0, limit)` clamp are unchanged; `_describe`'s key order is stable for
    renderers; `list_runs` still reads no store other than through the passed
    `store`.
  - **Acceptance:** `uv run pytest tests/integration/test_run_view.py -q`
    green; `uv run lint-imports` → 7 kept, 0 broken.
  - **Reachability:** `func builtin run list --tag k:v` — live in 6.1.

## Wave 5

- [ ] **6.1 — `run list --tag` and `run show`'s tag line** (C8; AC20, AC21,
      AC22, AC23, AC24, AC25 first half, AC26, AC29, AC31)
  - **[F]** `src/functualize/_cli/builtins.py`,
    `tests/_cli/test_builtin_command_pilot.py`,
    `tests/cli/test_builtin_commands_read_the_installed_substrate.py`
  - **Inputs:** `plan.md` §4.12; `builtins.py:1902-1928`, `:1930-1971`
    (`:1955-1959`, `:1960-1962`, `:1963-1971`), `:1973-1987`, `:1989-2018`
    (`:2004-2006`, `:2007-2018`); `docs/cli/run.md:33-52`.
  - **Do:** `run_list` gains `@click.option("--tag", "tag", multiple=True,
    metavar="KEY:VALUE", …)`, parses each through
    `_cli.run_tags.parse_tag` (a malformed filter → `Error: …`, exit 2) and
    passes `tags=…` to `list_runs`. In the table branch render tags **last**:
    `" ".join(f"{k}:{it['run_tags'][k]}" for k in sorted(it["run_tags"]))`,
    appended as `"  " + tags_text` only when non-empty. `run_show` prints a
    `run_tags:` line in the fixed-key area, `-` when the map is empty; the JSON
    branch gains nothing (the projection already carries the key).
  - **Tests (unit + CliRunner):** AC20 two `--tag` values are AND,
    exact/case-sensitive (`host:Laptop` matches nothing); AC21 limit after
    filters; AC22 every JSON row has `run_tags`, including pre-feature records;
    AC23 a tagged row ends `attempt:3 repro:bug-412` (sorted by key, space
    separated, tags last) and an untagged row is **byte-identical** to today's
    (assert the full line string); AC24 no match → `No matching runs.`, exit 0;
    AC26 `run show` text has the `run_tags:` line and `--format json` has the
    map; AC29 `info jobs <job> --json` still reports the job's own
    `["infra","release"]` and `--tag infra:yes` matches no run; AC31 with no tag
    source the table output and exit code are byte-identical while the JSON
    differs only by `"run_tags": {}`.
  - **Invariants:** the table's first five columns are untouched; `run show`'s
    line order for existing keys is unchanged; no new import of `_types` in
    `_cli`; the flag is refused on `func builtin` (still Click's error).
  - **Acceptance:** `uv run pytest tests/_cli/test_builtin_command_pilot.py
    tests/cli/test_builtin_commands_read_the_installed_substrate.py -q` green.
  - **Reachability:** live on both stores — `func --run-tag harness:claude
    release` then `func builtin run list --tag harness:claude` and
    `func builtin run show <id>`.

- [ ] **6.2 — MCP inherits the projection and takes no tag input** (C8; AC25)
  - **[F]** `tests/plugins/test_mcp_workflow_tools.py`
  - **Inputs:** `plan.md` §4.12; MCP `_workflow_tools.py:50`, `:215`,
    `:500-517`; `contracts.md` C8.
  - **Do:** no production edit — `_list_runs` calls the same `list_runs`, so the
    map arrives with the row. Add the assertion only, plus a refusal test that
    the tool schema has **no** `run_tags`/`tag` input parameter in v1.
  - **Tests (unit):** a tagged run returned by `list_runs` carries `run_tags`
    through the MCP tool result; an untagged run carries `{}`; the tool's input
    schema has no tag parameter.
  - **Invariants:** no MCP write-side surface change; the tool's other fields
    are unchanged; no `_engine` import added.
  - **Acceptance:** `uv run pytest tests/plugins/test_mcp_workflow_tools.py -q`
    green.
  - **Reachability:** the MCP tool is exercised by its own suite; live proof is
    the CLI transcript plus the shared projection.

## Wave 6

- [ ] **7.1 — Docs and changelog** (C8; shape §5.8, R2)
  - **[F]** `docs/cli/run.md`, `docs/api/types.md`, `CHANGELOG.md`
  - **Inputs:** `plan.md` §4.13; `docs/cli/run.md:33-52`, `:65`, `:85-99`;
    `docs/api/types.md:148-159` (`:156`); `CHANGELOG.md:8-11`.
  - **Do:** `run list` synopsis gains `[--tag KEY:VALUE ...]`; a new
    `### Filtering by tag` section (AND semantics, exact/case-sensitive, the
    three tag sources, **tags are stored in plain text — never put a secret in
    one**); the JSON section notes `run_tags`; the MCP section notes the
    inherited field and the absent input. `docs/api/types.md:156` gains
    `--run-tag` in the `GLOBAL_OPTIONS_ALWAYS_VALUE` row; `:157` is untouched.
    `CHANGELOG.md` gets one `### Added — <one sentence>` above the existing
    `### Added — gate answers are durable…` (`:10`), heading plus one paragraph.
  - **Tests:** doc-verify on the two rendered pages (the `--run-tag` row means
    what the flag does; the example output matches the built binary).
  - **Invariants:** `GLOBAL_BOOL_FLAGS`'s documented membership is unchanged;
    no tracker keys in the changelog; no claim about a project-file tag source.
  - **Acceptance:** `rg -n -- '--run-tag' docs/api/types.md` → 1 hit at `:156`;
    `rg -n -- '--tag' docs/cli/run.md` → ≥ 2 hits; `rg -n '^### Added' 
    CHANGELOG.md` → the new entry above the gate one.
  - **Reachability:** docs only.

- [ ] **7.2 — Checkpoint** (AC32; all gates)
  - **[F]** none (verification only)
  - **Do:** `uv run ruff check --fix src/ tests/ plugins/ examples/`,
    `uv run ruff format --check src/ tests/ plugins/ examples/`,
    `uv run mypy src/`, `uv run lint-imports`, the tiered pytest selection for
    the diff (`.agents/skills/test-tiers/scripts/tests-for-diff`, never one
    pytest call past 600 s), and
    `uv run python .github/scripts/dead_code_delta.py 11ed0e82 HEAD`
    (expect 0 NEW_DEAD / 0 TESTS_ONLY). AC32 census:
    `rg -n 'run_tags' src plugins -g '*.py' -g '*.sql'` must show readers only
    in `_cli/` (builtins, main, run_tags), the two stores, `_run_view.py`, the
    peer types, the adapter builders and the executor — nothing else.
  - **Acceptance:** all six checks green; the census matches `spec.md` AC32's
    list; every task above `[x]` with its reachability evidence.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["2.1", "2.2"] },
    { "id": 2, "tasks": ["3.1", "3.2"] },
    { "id": 3, "tasks": ["4.1", "4.2"] },
    { "id": 4, "tasks": ["5.1", "5.2"] },
    { "id": 5, "tasks": ["6.1", "6.2"] },
    { "id": 6, "tasks": ["7.1", "7.2"] }
  ]
}
```
