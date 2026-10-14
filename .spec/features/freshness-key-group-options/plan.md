# plan.md — freshness-key-group-options

## Design skills consulted

- `.claude/skills/python-design-patterns`, the repo's own (KISS, separation
  of concerns, single responsibility, God-class decomposition). It applies
  directly here because the engine class is already a God class (see below).
- `design-patterns-refactoring`, a user-level skill present in this session's
  listing. It carries the Refactoring.Guru smell catalogue. Loaded for the
  catalogue names used below (ch31/ch32/ch34) and for *Move Method* /
  *Extract Method* (ch38/ch39).

Retrieval for this plan:

- `rg` for every count and negative. Callers of `fingerprint_key_for`,
  `_args_hash_for` and `compute_args_hash` across `src/`. The callers of
  `Preflight.check`.
- The prior-art prose pass over `contributor/reference/pitfalls.md` §21–§22,
  `contributor/adr/012-resolved-sources.md` and `docs/guides/group-options.md`.

The zvec-grep MCP server refused connections for this session, so the prose
pass was done with `rg` over those named documents. That is narrower than a
semantic search, and this note records the gap.

## BEFORE — the shape now

```
                           [peer layer _engine]
_engine/executor.py  JobExecutionEngine  (2813-line module; class far past ~500 LOC)
  _execute_lifecycle
    ├─ _resolve_group_options ─► ctx.call_kwargs[opts]=instance; ctx.injected+=opts
    ├─ DependencyRunner.run_for ─► _unreusable_upstreams(fn)
    │                                 └─► engine.fingerprint_key_for(up, m)   READER 1
    ├─ _inject_from_job ─► _from_job_value(ref) ─► fingerprint_key_for        READER 2
    ├─ _run_mode_skip ─► _args_hash_for(ctx)                                   WRITER
    └─ _preflight_check ─► Preflight.check(args_hash=_args_hash_for(ctx))     WRITER
                                    │
  _args_hash_for(ctx)      = compute_args_hash(config, call_kwargs - injected)
  fingerprint_key_for(job) = compute_args_hash(config, {})     ← both option-blind
                                    │ imports (legal: _engine → _primitives)
                                    ▼
_primitives/fingerprint.py  compute_args_hash(config, args) → {"config","args"}

_app/impl.py (composition root)  explain / `func builtin why`
  ├─ Preflight.check(config=…)  → default args_hash = compute_args_hash(config,{})  READER 3
  └─ _return_value_note ─► engine.fingerprint_key_for                         READER 4
```

### Smells the BEFORE already carries

- **Large Class.** `JobExecutionEngine` in `_engine/executor.py`. It is
  pre-existing and is being taken apart one subject at a time
  (`WorkflowOrchestrator`, `DependencyRunner`). The constitution forbids
  *growth*, so the AFTER must not add net lines to the class.
- **Shotgun Surgery.** The "what is in the key" rule is written at three
  places that must change together: `_args_hash_for`, `fingerprint_key_for`
  and `Preflight.check`'s default derivation (as reached from `why`). This
  defect is a direct result: adding a key component means editing all three.
- **Misleading comment** (catalogue: *Comments* used as deodorant). The
  design table at `executor.py:450` claims config resolution covers group
  options. No code makes that true.

## AFTER — the shape this feature leaves

```
_engine/freshness_key.py   FreshnessKeys(engine)     [peer layer _engine, NEW]
  for_run(ctx)                      WRITER: config + explicit + group options
      group options = {p: config_payload(ctx.call_kwargs[p])
                       for p in engine._group_options_params(ctx.function)}
  for_job(job, group_option_values) READER: config + {} + resolved group options
      resolved through engine._build_group_options — the same resolver,
      section and layer the writer's run used; never prompts; an
      unresolvable option → None (a key no writer produces)
            │ imports (legal: _engine → _primitives)
            ▼
_primitives/fingerprint.py compute_args_hash(config, args, group_options=None)
      payload gains "group_options" only when non-empty → old keys unchanged

_engine/executor.py JobExecutionEngine          (net shrink: comment + bodies moved)
  _args_hash_for(ctx)                      → FreshnessKeys.for_run
  fingerprint_args_hash_for(job, layer)    → FreshnessKeys.for_job
  fingerprint_key_for(job, m, layer)       → fingerprint_key(job, ↑, m)
  _build_group_options(cls, values)        ← extracted from _resolve_group_options
  _from_job_value(…, layer=ctx.request.group_option_values)       READER 2
DependencyRunner._unreusable_upstreams(fn, layer=ctx.request…)    READER 1
_app/impl.py explain: Preflight.check(…, args_hash=engine.fingerprint_args_hash_for(n))  READER 3
```

No new boundary crossing. `freshness_key.py` imports only `_primitives`,
which `_engine` already does, and it reaches the engine through a
back-reference typed under `TYPE_CHECKING`, the same way
`dependency_runner.py` does. `_app/impl.py` already calls the engine.
`lint-imports` decides legality: 7 contracts are expected to stay kept.

### Smell check on the AFTER (introduced-smells pass)

- **Middle Man.** `_args_hash_for` and `fingerprint_args_hash_for` on the
  engine forward to `FreshnessKeys`. This is accepted. They are the names
  existing callers and `DependencyRunner`/`_app` already reach, and
  `WorkflowOrchestrator` and `DependencyRunner` set the same precedent. The
  forwarding is one line each.
- **Inappropriate Intimacy.** `FreshnessKeys` reads engine privates
  (`_group_options_params`, `_build_group_options`, `_run_context_of`). It
  has the same intimacy as `DependencyRunner`, by the same extraction
  design. This is accepted for the same reason.
- **Shotgun Surgery** is reduced: `why` no longer derives a key of its own.
  It asks the engine. The writer/reader pair remains two methods in one
  module.

## Surviving smells

1. **Parallel derivation (Duplicate Code, in kind).** `FreshnessKeys.for_run`
   and `for_job` both build "config + args + group options". The writer reads
   live values from a context, and the reader re-resolves them from a name and
   a layer. Merging them would need a fake context or would leave the writer
   resolving twice. They now sit side by side in one module, and
   `TestTheKeyFormula::test_the_writer_counts_the_injected_option_and_nothing_else`
   asserts reader == writer. Accepted. **No maintainer review needed.**
2. **Large Class.** `JobExecutionEngine` survives, smaller than before
   (net-negative line count in the class). Its decomposition is not this
   feature's subject. **No review needed.** Pre-existing, and not grown.
3. **Middle Man / Inappropriate Intimacy** on the new collaborator, as
   above. These follow the established extraction pattern. **No review
   needed.**

## Files to change

| File | Change |
|---|---|
| `src/functualize/_primitives/fingerprint.py` | `compute_args_hash(..., group_options=None)`; docstring states the rule |
| `src/functualize/_engine/freshness_key.py` | new: `FreshnessKeys` (writer + reader derivation, the corrected design table) |
| `src/functualize/_engine/executor.py` | delegations; `fingerprint_args_hash_for`; `_build_group_options` extracted; `_from_job_value` takes the layer; the old table moves out |
| `src/functualize/_engine/dependency_runner.py` | `_unreusable_upstreams` takes the dependent's layer |
| `src/functualize/_app/impl.py` | the explain path passes the engine's args hash to `Preflight.check` (two calls) |
| `tests/group_options/test_group_options_freshness.py` | new: AC-1..AC-5 |
| `docs/guides/group-options.md` | one paragraph: a changed option re-runs a cached job |
| `contributor/reference/pitfalls.md` | §21 gains the "injected is not unreconstructable" corollary |
| `.spec/STATUS.md` | completion entry (the durable half of this package) |

**File-scope disclosure:** `_app/impl.py` belongs to an in-progress sibling
lane (run middleware decorators). The change here is two keyword arguments
inside the explain body, which is disjoint from the decorator and registry
code. Without it, `func builtin why` would read the option-blind key, which no
writer produces after this change. `why` would then claim "would run"
straight after a successful run of every cached group-option job, which is
the contradiction pitfalls §22 records. Disclosed here and in the hand-off.

## Risks

- **One-time miss after upgrade** for cached jobs with group options. This
  is deliberate (spec § Deliberate behavior changes).
- **A secret group-option field enters the hash input.** The job config
  already does this. Only the sha256 digest is stored, and the plain values
  are never written to the record by this change.
- **Reader cost.** `for_job` resolves each declared option class once per
  read, through the boot-built resolution chain. There is no file I/O per
  read (`AGENTS.md` § Config system). Each loop over the three methods now
  derives the hash once instead of three times.
- **`why` with typed flags** explains the flagless run. See spec § Out of
  scope.
