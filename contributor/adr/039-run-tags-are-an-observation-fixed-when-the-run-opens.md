# ADR-039: Run Tags Are an Observation, Fixed When the Run Opens

**Status**: accepted
**Date**: 2026-10-29
**Deciders**: maintainer

## Context

People and tools want to find and group runs by facts the job knows nothing
about: which coding harness or session launched it, which model, which bug it
reproduces, which attempt this is. There was no place to say any of that. A
job's own `@job(tags=[...])` describes the job, not one execution of it, and
`args_hash` and the job's arguments cannot carry it without changing what the
job computes and what the cache reuses.

## Decision

- **A run tag is a `key:value` label on one run.** The key matches
  `[a-z0-9][a-z0-9._-]*`, the value is split at the first `:` and may hold
  colons, neither side may contain whitespace, a value holds at most 256
  characters, and a run holds at most 32 tags. `_cli/run_tags.py` is the one
  grammar; every refusal is a `RunTagError`.
- **Three sources, merged before boot.** The user's global config
  (`[run] tags`, a list), `FUNCTUALIZE_RUN_TAGS` (comma-separated, blank items
  skipped) and the repeatable global `--run-tag` flag, lowest to highest,
  merged per key with the later source winning. A key repeated inside one
  source is refused, naming that source. The project file is not a source.
  The merge completes before discovery, so the map exists before the app
  does; a refusal is a usage error, exit 2, before any job module is
  imported. The environment is read for every mode, so a malformed variable
  also stops `builtin` commands — intended. `builtin` commands take no
  `--run-tag`, because they start no run.
- **Only the `func` CLI accepts tags in this version.** HTTP, Lambda and MCP
  take no tag input, and a request rebuilt from a wire payload carries `{}`.
  Runs started from the TUI are untagged.
- **A child carries an exact copy.** `RunRequest.run_tags` is copied unchanged
  by `nested_request` to every workflow step, dependency, `Invoke` and
  parallel child; a child cannot add, change or remove an entry. A separate
  `func` process started by a job inherits the environment variable, not the
  parent run: it is tagged, and it has no `parent_run_id`.
- **Tags are an observation, never an input.** They are not in the request's
  hash, not in `args_hash` (a tagged and an untagged invocation share a cache
  entry), and never reach the job's arguments, its `RunContext`, its return
  value or its exit code.
- **Fixed when the run opens.** The run record is written with its tags and
  never rewritten to change them. A record written before tags existed reads
  as `{}` and is not rewritten to add the key. On the SQLite store (schema
  revision 5) a run's tags are rows of `run_tags`, staged in the run's own
  transaction before its first attempt; triggers refuse an update, a delete
  while the run exists, and an insert once the run has an attempt, and the
  rows leave with their run through the foreign-key cascade.
- **One projection, filtered by every tag.** Every run row — `run list`,
  `run show`, `--format json`, the MCP run tools — carries `run_tags`. A tag
  filter (`run list --tag`, `RunQuery.tags`) matches a run only when it carries
  every requested pair exactly and case-sensitively, and runs before the limit.
- **Tags are stored and shown in plain text.** They must never carry a secret.

## Consequences

### Positive

- A run can be found by who or what launched it without touching the job.
- Tags cannot change a job's behaviour, its result or what the cache reuses.
- Both shipped stores pass the same `run_tags_round_trip` conformance check.

### Negative

- The engine records runs in the run log, not through the runtime store's
  `start_attempt`, so the relational `runs`/`run_tags` pair has no production
  writer until the run recorder is wired. Until then a SQLite project's tags
  are read from the run log, like every other run field.
- `run_tags_lookup` (on `key, value`) does not serve `recent()`'s correlated
  probe, which uses the primary key; it serves only a query that starts from
  tags.
- The document-to-SQLite importer does not copy tags.
- `--run-tag` is a fourth delivery input on the request, which widens the
  handler signatures and the request builders by one keyword each.
