# run-tags — External contracts

## C1. Giving a tag — three sources, one vocabulary

```
func [GLOBAL OPTIONS] --run-tag KEY:VALUE [--run-tag KEY:VALUE ...] <group> <job> [job options]
FUNCTUALIZE_RUN_TAGS="KEY:VALUE, KEY:VALUE, ..." func <group> <job> [job options]
# ~/.config/functualize/config.toml
[run]
tags = ["KEY:VALUE", "KEY:VALUE", ...]
```

- `--run-tag` is a **global** flag: it is read before the command is decided, so
  it must precede the job name. After the job name it belongs to the job's own
  parser, which refuses it.
- Grammar of one tag:

  ```
  tag     := key ":" value
  key     := [a-z0-9][a-z0-9._-]*
  value   := 1..256 characters, none of which is whitespace or ","
  split   := at the first ":" only, so `url:https://x` is key `url`,
             value `https://x`
  ```

- `FUNCTUALIZE_RUN_TAGS`: items separated by `,`; whitespace around each item is
  trimmed; **empty items are skipped**. `${CLAUDECODE:+harness:claude},
  model:opus` yields `{harness: claude, model: opus}` when `CLAUDECODE` is
  unset.
- `[run] tags` is a list of strings in the **global user** config file
  (`~/.config/functualize/config.toml`). `.functualize.toml` and
  `pyproject.toml` do not contribute a `[run]` section (OQ-6).
- Merge, lowest to highest: `[run] tags` → `FUNCTUALIZE_RUN_TAGS` →
  `--run-tag`. **Per key**, higher layer wins. A key given twice *inside one
  layer* is an error (C7); across layers it merges.
- At most **32** tags on one run (shape §10 R4, declared).
- Everything is validated before boot. A refusal exits **2**, runs no job body
  and writes no run record (`_types/exit_codes.py:36-41`, `USAGE = 2`).

**Two implementation constraints this contract places on the code.**

1. `FUNCTUALIZE_RUN_TAGS` is **read directly by the new run-tag module**, not
   through `resolve_env_overrides` (`_cli/config.py:161`). The generic mapper
   splits at the first `_` after the section prefix (`:206`) and lowercases the
   remainder (`:213-215`), so it would turn this variable into section `run`,
   key `tags`, value the whole comma string — and it is reached only from
   `resolve_cli_config` (`:486`), which runs *after* dispatch has had to refuse
   a malformed tag. Shape §5.1 cites that function as the spelling's home; this
   contract supersedes it for the environment layer, and the shipped prose in
   `docs/cli/run.md` follows this contract, not that sentence.
2. `[run] tags` **does** go through `read_global_config` (`:80`), so `"run"`
   joins `_RECOGNIZED_SECTIONS` (`_cli/config.py:26`) **and** `run:
   frozenset({"tags"})` joins `_RECOGNIZED_KEYS` (`:34`). Without both, the
   filter loop (`:122-160`) drops the key with
   `Warning: <path>: unrecognized key 'tags' in [run], ignoring` — the layer
   silently disappears behind a warning nobody reads.

## C2. `func builtin run list --tag` — text output

```
$ func builtin run list --tag session-id:7f3a --tag model:opus --limit 5
run-01M53YF40T1BZCZH0Q8DWK5S34 migrate success invoke 9ms harness:claude host:laptop model:opus session-id:7f3a
run-01M53YF40E830NJHY4P00094K7 deploy success func.job 31ms harness:claude host:laptop model:opus session-id:7f3a
```

- Row shape unchanged: `<run_id>  <job>  <state>  <surface>  <duration>ms`
  followed, **only when the run has tags**, by a space and the tags.
- Tags print **last**, sorted by key, `key:value`, separated by single spaces.
- A run with no tags prints exactly today's row
  (`_cli/builtins.py:1966-1971`).
- `--tag` is repeatable; a run must match **all** of them. Exact, case-sensitive
  string equality on both key and value.
- `--tag` combines with `--job`, `--surface`, `--state`, `--scope`; `--limit`
  applies after every filter (`app/_run_view.py:181-232` already documents that
  order at `:209-210`).
- No match: `No matching runs.`, exit **0** (existing behaviour, `_cli/builtins.py:1961`).
- A malformed filter value: `Error: --tag 'session-id': expected key:value.`,
  exit **2**.
- `func builtin run show <id>` gains one line, after `parent_run_id`:

  ```
  run_tags: harness:claude host:laptop model:opus session-id:7f3a
  ```

  and prints no such line when the run has no tags.

## C3. `func builtin run list --format json` — payload

```json
{
  "runs": [
    {
      "run_id": "run-01M53YF40T1BZCZH0Q8DWK5S34",
      "job": "migrate",
      "surface": "invoke",
      "state": "success",
      "status": "success",
      "started_at": "2026-10-17T03:28:40.474460+00:00",
      "ended_at": "2026-10-17T03:28:40.482242+00:00",
      "duration_ms": 9,
      "scope_id": "deploy-e13b91a6",
      "parent_run_id": "run-01M53YF40E830NJHY4P00094K7",
      "invoke_depth": 1,
      "runner": "vmi3464921/pid-4046722",
      "args_hash": "b313cea27e05…",
      "force": false,
      "group_option_values": {},
      "run_tags": {"harness": "claude", "host": "laptop", "model": "opus", "session-id": "7f3a"},
      "children": [],
      "event_count": 0
    }
  ]
}
```

- `run_tags` is **always present** in every row: an object, `{}` when the run
  carries no tags — including a record written before this feature (C6).
- Object keys are the tag keys, string values the tag values. Order is not
  meaningful in JSON; the shape's transcript sorts them.
- No other key is added, removed or renamed (`app/_run_view.py:141-156`).
- `run show --format json` carries the same `run_tags` key, because it uses the
  same projection.
- The MCP run tools call this same `list_runs` (`_workflow_tools.py:495-517`), so
  they return `run_tags` with no new tool parameter. **No `run_tags` input** on
  any MCP, HTTP or Lambda surface in v1.

## C4. `RunRequest.run_tags` — the request field

```python
# _types/run_request.py, in the delivery block beside `force` (:195-198)
run_tags: Mapping[str, str] = _EMPTY   # frozen mapping; {} when untagged
```

- Delivered by the caller, never by the job. `nested_request` (`:340-376`)
  copies the **same** mapping verbatim into every child kind: steps, `Invoke`,
  `invoke_parallel`, dependencies, nested workflows. The child cannot add,
  change or remove an entry.
- **Not** an input to `__hash__` (`:232-256`) and not to `replace`'s identity:
  a tagged and an untagged request with identical arguments hash the same, and
  so does the run's `args_hash` (`_engine/executor.py:965`, from
  `compute_args_hash(call_args=…)`, which never sees `run_tags`). Freshness and
  caching are therefore tag-blind.
- Not exposed to the job: no `RunContext` attribute (OQ-4), no decorator
  argument, no `Invoke` argument, nothing in the job's environment.
- Immutable once the run opens. No command adds, changes or deletes a tag.

## C5. Global-flag grammar — the four entries a value-taking flag needs

```python
# _types/flag_grammar.py
GLOBAL_OPTIONS_ALWAYS_VALUE = frozenset({..., "--run-tag"})   # :46-65

# _cli/dispatch.py
ParsedGlobalOptions.run_tags: tuple[str, ...] = ()            # beside force, :238-262
_OptionAccumulator.__slots__ += ("run_tags",)                 # :433-453
# _assign_option: repeatable → append, like "--import-libs"    # :477
```

- `--run-tag` is **value-required**, so it goes in
  `GLOBAL_OPTIONS_ALWAYS_VALUE` only — `GLOBAL_OPTIONS_WITH_VALUE` aliases that
  set (`:96-98`). It must **not** join `GLOBAL_BOOL_FLAGS` (`:107-116`).
- Without the grammar entry, `detect_mode` does not consume the flag's value
  (`_cli/dispatch.py:159-166`), and the measured failure is
  `func --run-tag harness:claude release` → `Error: Unknown command
  'run-tag'.`, exit 1.
- `func builtin …` never declares the delivery inputs, so it refuses the flag
  the way it refuses `--force`: `Error: No such option '--run-tag'.`, exit 2
  (`_cli/main.py:2331-2358`, rejected flags `:2340-2342`).

## C6. Query, projection and storage surface

```python
# _types/persistence.py
class RunView:                                   # :653-670
    ... run_tags: Mapping[str, str] = field(default_factory=dict)

class RunQuery:                                  # :775-783
    ... tags: tuple[tuple[str, str], ...] = ()   # all must match

class StartAttempt:                              # :499-518
    ... run_tags: Mapping[str, str] = field(default_factory=dict)
```

- `StartAttempt.run_tags` **defaults** because nine construction sites omit it —
  `_engine/recording/run_recorder.py:56`,
  `src/functualize/testing/conformance/capabilities.py:141`,
  `src/functualize/testing/conformance/baseline.py:91`, `:95`, `:272`, `:332`,
  `plugins/substrates/functualize-substrate-sqlite/tests/test_run_sql.py:59`,
  `tests/test_legacy_import.py:101`, `tests/test_readers.py:191`. A new
  conformance case exercises it in
  `src/functualize/testing/conformance/capabilities.py`.
- `app/_run_view.py`: `_describe` (`:128-156`) gains
  `"run_tags": dict(record.get("run_tags") or {})`; `list_runs` (`:181-232`)
  gains a `tags` filter that rejects a record when any `(key, value)` is absent
  or differs, applied **before** the `limit`.
- **Document store.** One new key on the run entry (`.functualize/runs.json`):

  ```json
  "run_tags": {"harness": "claude", "host": "laptop", "model": "opus",
               "session-id": "7f3a", "ticket": "MCH-202"}
  ```

  Written by `RunStore.open_run` (`_primitives/run_store.py:218`) from
  `request.run_tags`. A record with **no** `run_tags` key is read as `{}` and is
  never rewritten just to add it. `_primitives/document_store.py:214-240`'s
  `limit * 8` over-read (`:225`) must not starve a narrow tag filter — the tag
  test belongs inside the existing per-field `continue` block (`:226-235`), and
  the over-read factor is raised there so a sparse match still fills `limit`.

- **Relational store.** New revision **`0005_run_tags.sql`** — the shape's
  `0003_run_tags.sql` is marked *provisional*, and this package already ships
  revisions 1–4 (`functualize_substrate_sqlite/_migrations.py:112-117`), so the
  next number is 5, appended as `_load(5, "run_tags")`.

  ```sql
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

  Rows are inserted in the same transaction as the `runs` row
  (`_run_sql.py:87-117`), so a run that lands always lands with its tags.
  Retention drops them through the cascade.
- **Read side, relational.** The tag map is not a column on `runs`
  (`_readers.py:45-48`, `_COLUMNS` in `SqlRunReader` at `:42`), so `SqlRunReader` loads it separately — one grouped
  `SELECT run_id, key, value FROM run_tags WHERE namespace_id = ? AND run_id IN
  (…)` per page, not one query per row. Each `--tag` becomes one
  `EXISTS (SELECT 1 FROM run_tags WHERE namespace_id = ? AND run_id = runs.id
  AND key = ? AND value = ?)` clause in `recent`, which `run_tags_lookup`
  serves directly.
- **Parity.** The same tagged run recorded on both stores answers the same rows
  for the same `--tag` query (SD/16908324, operator-surface parity).

## C7. Refusals

Every row exits **2**, before boot: no job body runs and no run record is
written. Wording is *provisional* (shape §7); the situation and exit code are
binding.

| Situation | Typed | Message |
| --- | --- | --- |
| no `:` | `--run-tag harness` | `Error: --run-tag 'harness': a run tag is key:value (missing ':').` |
| empty key | `--run-tag :claude` | `Error: --run-tag ':claude': a run tag needs a key before ':'.` |
| empty value | `--run-tag harness:` | `Error: --run-tag 'harness:': a run tag needs a value after ':'.` |
| whitespace | `--run-tag "model: opus"` | `Error: --run-tag 'model: opus': a run tag cannot contain whitespace.` |
| key outside the grammar | `--run-tag Model:opus` | `Error: --run-tag 'Model:opus': a run tag key uses a-z, 0-9, '.', '_' and '-'.` |
| value too long | `--run-tag k:<257 chars>` | `Error: --run-tag 'k:…': a run tag value is at most 256 characters.` |
| more than 32 tags | three layers totalling 33 keys | `Error: a run carries at most 32 run tags (got 33).` |
| key twice in one source | `--run-tag s:1 --run-tag s:2` | `Error: run tag key 's' is given twice (--run-tag s:1, --run-tag s:2).` |
| the same, in the environment | `FUNCTUALIZE_RUN_TAGS="s:1,s:2"` | `Error: FUNCTUALIZE_RUN_TAGS gives run tag key 's' twice (items 1 and 2).` |
| malformed environment item | `FUNCTUALIZE_RUN_TAGS="a:b, :x"` | `Error: FUNCTUALIZE_RUN_TAGS item 2 ':x': a run tag needs a key before ':'.` |
| malformed global-config item | `[run] tags = ["a:b", ":x"]` | `Error: [run] tags item 2 ':x': a run tag needs a key before ':'.` |
| key twice in the global config | `[run] tags = ["s:1", "s:2"]` | `Error: [run] tags gives run tag key 's' twice (items 1 and 2).` |
| the flag on a builtin | `func --run-tag a:b builtin run list` | `Error: No such option '--run-tag'.` |
| malformed query filter | `run list --tag session-id` | `Error: --tag 'session-id': expected key:value.` |
| tagging an existing run | `func builtin run tag run-01M5… k:v` | `Error: No such command 'tag'.` |
| store-level rewrite of a run's tags | any non-opening write | a programming error, not a user error: `ValueError: run tags are fixed when <run-id> opens` (spelling illustrative) |

- The three malformed-source rows (environment item, config item, config
  duplicate) are raised while resolving the layers, before job discovery; the
  run does not start.
- A malformed **project** `[run]` section is *not* a refusal: the project file
  does not contribute this key at all, so it contributes nothing (C1, OQ-6) —
  SD/17137669 must not report it as accepted-and-read.

## C8. What does not change

- Job tags: `@job(tags=[...])`, `func builtin info jobs <job> --json` `.tags`,
  and the meaning of `--tag` as a run filter are three separate things. No run
  tag is ever written into a job's tags, and `--tag infra:yes` does not match a
  job that declares `infra`.
- No new authoring-API surface; no `RunContext` attribute; no `Invoke`
  argument.
- No input surface on HTTP, Lambda or MCP for `run_tags`; no TUI tagging.
- No change to `args_hash`, freshness, caching, exit codes for a run, run
  discovery or configuration resolution.
- The TUI's run records are unchanged — untagged — and its rows render exactly
  as today.

Not exported from any public folder; no public API change.
