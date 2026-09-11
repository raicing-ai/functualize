# Runtime State Store Reference

**Audience:** contributors working on state persistence, fingerprints, or workflow resumption.
**Status:** shipped.

## 1. Purpose

Runtime persistence is **five files**, and the difference between them is the discard
rule. Two hold records and refuse when unreadable; three hold derived or convenience data
and degrade to empty.

| file | holds | on unreadable |
|---|---|---|
| `state.json` | fingerprints, session precondition cache | degrades to empty |
| `scopes.json` | scope records: steps, branches, gate payloads, position, epilogue | **refuses** |
| `scope-state/<id>.json` | one run's `rc.state` (`scope-record-lifecycle`/T3) | **refuses** |
| `runs.json` | the run log: every execution, its origin, parentage and outcome | degrades to empty |
| `shell-history.json` | commands typed in the TUI's shell mode (`durable-run-layer`/T3b) | degrades to empty |

The two-file table below is kept for the pair the discard rule was first drawn between:

| | `state.json` | `scopes.json` |
|---|---|---|
| Holds | fingerprints, session precondition cache | workflow scope records: steps, branch choices, gate payloads, position, epilogue |
| Is | **derived** — recomputable from the source tree | a **record** — recomputable from nothing |
| Unreadable or wrong version | degrades to empty; worst case is one extra run | **refuses**, leaving the file in place |
| Module | `_primitives/state_format.py` | `_primitives/scope_format.py` |
| Cleared by | `func builtin state clear` | `func builtin state clear --scopes` |

Scopes lived in `state.json` until 2026-09-09. They should not have: a `STATE_VERSION`
bump — an ordinary release action — silently erased every in-flight run, gate payloads and
all, because the envelope's discard rule was written for fingerprints. A blocked run
holding a human's approval is not derived state.

**When adding a section, pick the file first.** If losing it would upset someone, it is not
derived and does not belong in `state.json`.

Both are separate again from the discovery cache (which holds "what jobs exist and their
metadata"). None of the three invalidates another:
- `func cache clear` clears the discovery cache only
- `func builtin state clear` clears derived runtime state only, and keeps scopes
- `func builtin state clear --scopes` also discards scopes, moving the file aside

## 2. File Format

- **Location:** `.functualize/state.json` and `.functualize/scopes.json` (same XDG
  fallback rules as `cache.json`, resolved via `locator.py`)
- **Modules:** `_primitives/state_format.py`, `_primitives/scope_format.py`
- **Versions:** `STATE_VERSION` and `SCOPES_VERSION`, **independent of each other** —
  bumping one says nothing about the other, which is the point of the split
- **Concurrency:** advisory file lock on write; last-writer-wins per key (two concurrent
  runs touching *different* jobs or scopes don't clobber each other's records)
- **Atomic write:** one implementation, `state_format.atomic_write_json`, shared by both.
  A second copy is how one of them loses its `fsync`.
- **Format:** versioned JSON to start. Migrate to sqlite only if history/pruning
  pressure demands it — measured, not assumed. Both files keep every section as a flat
  `{str: record}` mapping, which is the shape `StateBackend`'s KV protocol addresses, so
  that migration needs no record-format change.

`state.json`:
```json
{
  "format_version": 1,
  "fingerprints": { ... },
  "session": {"preconditions": { ... }}
}
```

`scopes.json` — two keys, no more:
```json
{
  "format_version": 1,
  "scopes": {
    "<scope_id>": {
      "workflow": "release", "status": "blocked",
      "steps": {}, "branches": {}, "gates": {},
      "position": "approve", "epilogue": null, "tool_calls": []
    }
  }
}
```

**The scope file is always the state file's sibling**, derived via
`resolve_state_location(...).with_name(SCOPES_FILENAME)` rather than a second upward walk.
Two walks can disagree; one cannot. So the pair can never land in different directories or
different modes.

### 2.1 Reading, side by side

| Condition | `state.json` | `scopes.json` |
|---|---|---|
| absent | empty envelope | empty — "no scopes" |
| unparseable / not a dict | empty envelope | **`ScopeStoreUnreadableError`** |
| version mismatch | empty envelope | **`ScopeStoreUnreadableError`** |

A refusal **never moves the file**. It has to be a repeatable state: if the read renamed
the file aside, the next run would find nothing, read it as "no scopes", and start the
workflow over — silently, which is the failure the split exists to prevent. The file moves
only at `func builtin state clear --scopes`, and even then it is moved, not deleted.

The error reports a **count, never content**: scope records hold gate payloads and step
return values, which may be secrets.

Every delivery surface turns that error into a refusal — the CLI exits 2 (from both the
cold and warm dispatch paths), and the MCP workflow tools return
`{"error": "scope_store_unreadable", ...}` rather than claiming the workflow was not
found.

## 3. Fingerprint Model

```
fingerprint_key = <job_name>::<args_hash>::<method>
```

- `job_name`: canonical lowercase-hyphenated name
- `args_hash`: SHA-256 of the canonical JSON representation of resolved config + args
- `method`: hash algorithm (`sha256`)
- `sources`: globs from `Fingerprint.sources`; file mtimes + content hash
- `job_version`: declaration hash (function source hash — detect code changes)
- **R4 stat short-circuit:** if mtimes of all sources are unchanged, skip content hashing

A fingerprint record is keyed implicitly by the four-part identity `(scope_id, job_name,
args_hash, method)` plus the optional `job_version` discriminator.

## 4. Guard Pipeline

Precedence order (each stage is checked in sequence; first disqualification or error stops):

```
platforms → preconditions → status → fingerprint
```

Three outcome states:

| State | Meaning |
|-------|---------|
| `SKIP_NEUTRAL` | Guard says "no opinion" — job may still run if fingerprint is stale |
| `SKIP_SATISFIED` | Guard confirms freshness — job is up to date, skipped |
| `BLOCK(failure)` | Guard failed — error, job does not run |
| `BLOCKED(awaiting=Model)` | Gate waiting for input — walk paused, persisted in state store |

**Session precondition cache:** precondition results are cached within a session
(keyed by command string) to avoid re-running the same check multiple times.

**R10a:** truthy guard results AND with staleness (the `satisfied` path still checks
fingerprint freshness before skipping).

## 5. Per-Scope Records

Keyed `(scope_id, job_name, args_hash)`. One record type serves four consumers:

1. **Replay-skip on resume** — a completed step in this scope does NOT re-run
2. **Branch-choice recording** — a chosen `ConditionalEdge` key is recorded on first
   evaluation and *read* on replay (determinism: a non-deterministic condition must
   not change branches between pause and resume)
3. **Persistent `run="once"` / `"when_changed"` dedupe** — scope-/session-keyed,
   mechanically distinct from fingerprints
4. **Epilogue `FromJob[step]` injection** — step return values available to the
   workflow's epilogue body

## 6. History — two sources, one command

The ring buffer in `state.json` is **gone** (`durable-run-layer`/T3b). It held two kinds
of record under a `namespace` tag, and they went in opposite directions:

| namespace | now comes from | why |
|---|---|---|
| `job` | **derived** from `runs.json` via `app/_run_view.job_history` | the run log already recorded the same runs, plus the nested ones, plus who invoked them — the ring was a poorer copy of a subset |
| `shell` | `_primitives/shell_history.py`, its own file | a command typed in shell mode was never a run; the log has nowhere to put one |

`func builtin history` reads both and merges them newest-first on `at`. Its `--namespace`
flag is unchanged, and so is the rendering — the split is invisible to the caller.

**The launch rule moved, not changed.** "Only what the user launched" — `invoke_depth == 0`
plus the items of a top-level parallel batch — used to be applied when *writing* the ring.
It is now applied when *reading* the log, in `_run_view._is_a_launch`, which is possible
because both of its inputs (`surface`, `invoke_depth`) are in the run record.

**Argument values are still never stored** — only `args_hash`, so a record identifies a
run without persisting its inputs.

The bound moved with the data: the ring's 200 is gone, and history is now capped by
`RUNS_LIMIT` (500), the one cap that has to hold anyway.

## 7. `func builtin why` / `--explain`

Shared verdict renderer:

```
$ func builtin why build

build
  platforms  ✓ linux · aarch64→✓ · x86_64→✓ · win32→skip
  preconditions  docker: ✓ · venv: ✓
  status  test -f dist/app.whl → exit 1 (not satisfied)
  fingerprint  src/**/*.py: 3 files changed since last run (a.py, b.py, c.py)
  deps  lint ✓ fresh · test ✗ stale → will run first
```

`--explain` on any run prints the same verdict per node as it schedules.

## 8. `func builtin state clear`

- Clears **derived** runtime state: fingerprints, session preconditions. Not history —
  it no longer lives here (§6)
- **Keeps workflow scopes**, and says how many it kept. A scope is a run somebody is
  waiting on, not a cache; discarding one is a separate decision
- `--scopes` also discards scopes, **moving the file aside** rather than deleting it, and
  reports where it went. This is also the escape hatch from a scope file that cannot be
  read, so it never reads the file first
- Does NOT touch the discovery cache; `func cache clear` does NOT touch state
- `func builtin state show` reports both files, their counts, and the scope format
  version. On an unreadable scope store it prints every other statistic, renders the scope
  line as the fault, and exits 2 — it is the command people run to find out what is
  wrong, so it diagnoses rather than stonewalls
