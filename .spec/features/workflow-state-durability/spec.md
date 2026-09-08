# Spec: workflow-state-durability

**Feature:** workflow scopes get their own versioned file, so no ordinary action can
silently erase an in-flight run.

**Shape intent:** `.spec/shape-intents/pi-workflows-parity/` — decisions **B1, B1a, B1b,
B2**. Behaviour only below; approach is `plan.md`.

---

## 1. Problem

Workflow scopes — the only record of an in-flight run, including a human's recorded gate
answers — share a state envelope whose discard rule was written for derived data. Two
ordinary actions destroy them silently.

### 1.1 A format-version bump erases every run

`load_state` degrades any unreadable content to `empty_state()`
(`_primitives/state_format.py:162-175`), `normalize_state` does the same on a
`format_version` mismatch (`:142-159`), and every writer is `update_state` = load →
mutate → save (`:296-310`). So the next ordinary write persists the empty envelope.

The header comment justifies this (`:40-47`):

> *A version mismatch discards the file (runtime state is derived, never a source of
> truth — the worst case is one extra run).*

The next line of that same comment lists what lives in the file:
`scopes (per-scope step records, recorded branch choices, gate payloads, blocked position,
epilogue record)`. **A blocked run holding an approval is not derived state.** The
rationale predates `scopes` being added to the envelope.

Proven by experiment — transcript in
`.spec/shape-intents/pi-workflows-parity/evidence/scrutiny-report-2026-09-08.md`:

```
BEFORE  scopes: ['a3f9c2e1b7d4']          # blocked run, gate payload recorded
# bump format_version, then one unrelated fingerprint write
AFTER   scopes: []
RESULT: gate payload survived? False
```

No error, no warning, no backup. Triggered by a write that had nothing to do with
workflows.

### 1.2 `state clear` erases every run, under help text that does not say so

`StateStore.clear()` writes `empty_state()` (`_primitives/state_store.py:361-365`). The
group help reads *"Manage the runtime state store (fingerprints, history)"* and the
command help *"Reset runtime state. Does not touch the discovery cache."*
(`_cli/builtins.py:778-806`). Neither mentions scopes. A user clearing stale fingerprints
destroys every blocked run.

### 1.3 The walk rewrites the whole envelope, repeatedly

`StateStore.batch()` exists to hold the lock across many mutations and write once, and
the module docstring says *"A run that makes many mutations should use
`StateStore.batch`"* (`state_store.py:9-11`). **It has zero call sites** in `src/`,
`plugins/` or `tests/`.

So `record_step`, `set_position` and `set_scope_status` each perform an independent locked
read-modify-write of a file that also holds every fingerprint and a 200-entry history
ring — roughly three full rewrites per node.

## 2. Behaviour

### 2.1 Scopes live in their own file

Workflow scopes are stored separately from derived runtime state.

- **AC-1** Workflow scope records are persisted in a file distinct from the one holding
  fingerprints, history and session state.
- **AC-2** The scope store carries its own format version, independent of the derived
  store's.
- **AC-3** Changing the derived store's format version leaves every existing scope
  readable and unchanged.
- **AC-4** Changing the scope store's format version never silently discards scopes: the
  run refuses to proceed, the existing file is preserved under a recoverable name, and
  the message states how many scopes were affected and the command to discard them
  deliberately.
- **AC-5** A missing scope file is not an error — it reads as "no scopes", exactly as a
  missing state file reads as "no fingerprints" today.
- **AC-6** A corrupt or unreadable scope file follows AC-4, not AC-5: it is preserved and
  refused, never treated as empty.

### 2.2 `state clear` stops destroying runs

- **AC-7** `func builtin state clear` clears fingerprints, history and session state, and
  leaves scopes intact.
- **AC-8** When scopes are present, `state clear` reports how many it kept and names the
  option that would clear them.
- **AC-9** `func builtin state clear --scopes` clears scopes as well, and says so.
- **AC-10** Help text for the `state` group and for `clear` names every section each one
  affects, including scopes.
- **AC-11** `func builtin state show` continues to report the scope count, and reports the
  scope store's own location and version.

### 2.3 Existing behaviour that must not change

- **AC-12** A blocked workflow resumes across the split exactly as before: completed
  steps replay, recorded branch choices hold, deposited gate payloads are found.
- **AC-13** Exit codes are unchanged — in particular 5 for a gate block, with the scope id
  and gate name on stderr.
- **AC-14** `func history`, fingerprint freshness (`--force`), and the session
  precondition cache are unaffected in behaviour.
- **AC-15** Reading or writing scopes requires no new optional package. The scope store is
  core, unconditional (shape intent 11 §2).
- **AC-16** Concurrent writers remain serialized. Two processes mutating scopes do not
  clobber each other's records.

### 2.4 The walk stops rewriting the whole envelope

- **AC-17** A walk's per-node scope writes are coalesced: walking a graph of N nodes
  performs fewer whole-file writes of the scope store than the current three-per-node,
  and the recorded outcome is identical to the uncoalesced path.
- **AC-18** If coalescing is not adopted, the unused batching entry point is removed
  rather than left with a docstring instructing callers to use it. Either way, no code
  path advertises a mechanism nothing calls.

## 3. User stories

**As an operator**, I upgrade functualize and my three blocked release pipelines are still
waiting where I left them, with the approvals I already gave them.

**As an operator**, I clear stale fingerprints to force a rebuild and my in-flight runs
survive, because the command told me it was keeping them.

**As an operator**, if a scope file genuinely cannot be read, I get a refusal naming what
was at stake and where the file went — not a silently empty list and a workflow that
starts over.

**As a maintainer**, I can bump the derived state format without auditing whether anyone
has runs in flight.

## 4. Out of scope

- Moving scopes to SQLite. The shape-compatible `{str: record}` layout is preserved so
  the `StateBackend` seam stays open (shape intent 11 §2), but no backend is added here.
- The verb surface — `answer`, `resume`, `--wf-*`, `--scope-id` removal. Separate feature.
- Notes, provenance, timestamps, or any new field inside a scope record.
- Leases, event log, or fencing a stale walker.

## 5. Definition of done

Every AC above is covered by a test. Additionally:

- The experiment in §1.1 is reproduced as a regression test: set up a blocked scope with a
  recorded gate payload, bump the derived store's version, perform an unrelated write,
  and assert the scope and its payload survive.
- `uv run ruff check src/ tests/`, `ruff format --check`, `mypy src/`, `pytest`, and
  `lint-imports` all pass with zero violations.
- No comment or docstring in the touched modules asserts that runtime state is safe to
  discard without distinguishing derived state from scopes.
