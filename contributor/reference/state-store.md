# Runtime State Store Reference

**Audience:** contributors working on state persistence, fingerprints, or workflow resumption.
**Status:** shipped.

## 1. Purpose

The runtime state store holds **"what happened at runtime"** — fingerprints, guard results,
workflow step records, branch choices, execution history. It is deliberately separate from
the discovery cache (which holds "what jobs exist and their metadata").

- **State store** — runtime results, history, workflow position
- **Discovery cache** — job descriptors, params, module metadata

The two never invalidate each other:
- `func cache clear` clears discovery cache only
- `func builtin state clear` clears runtime state only

## 2. File Format

- **Location:** `.functualize/state.json` (same XDG fallback rules as `cache.json`,
  resolved via `locator.py`)
- **Module:** `_primitives/state_format.py`
- **Version:** `STATE_VERSION` constant; bump on incompatible schema changes
- **Concurrency:** advisory file lock on write; last-writer-wins per job-key (two
  concurrent runs of *different* jobs don't clobber each other's records)
- **Format:** versioned JSON to start. Migrate to sqlite only if history/pruning
  pressure demands it — measured, not assumed.

The envelope:
```json
{
  "version": 1,
  "functualize_version": "0.15.0",
  "generated_at": "2026-07-24T12:00:00Z",
  "fingerprints": { ... },
  "scope_records": { ... },
  "history": [ ... ]
}
```

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

## 6. History Ring Buffer

- `append_history(entry)` / `get_history(n)` on the state store
- Ring buffer, bound 200 entries
- Entry fields: `job_name`, `args_hash`, `status` (success/failure/cancelled),
  `duration_ms`, `timestamp`, `scope_id`
- Backs `func builtin history` command
- Written through the shell mode's `StateStore.append_history`

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

- Clears runtime state only (fingerprints, scope records, history, preconditions)
- Does NOT touch the discovery cache
- `func cache clear` does NOT touch state
- The two operations are independent and deliberate
