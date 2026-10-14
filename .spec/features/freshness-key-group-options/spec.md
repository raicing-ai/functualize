# freshness-key-group-options

## The defect

A job that declares `cache=Fingerprint(...)` and receives a `GroupOptions`
parameter is judged "up to date" across a change of that option.
`func demo --target a scan` followed by `func demo --target b scan` skips the
second run and keeps the record written under `a`. A `FromJob` consumer then
gets a value from a different option: `func demo --target b report` (with
`report` reading `FromJob("demo.scan")`) prints
`REPORT target=b scanned=a`. Exit code is 0 and nothing reports the mismatch.

Verified against `master` at `c03dfb72`:

- `_engine/executor.py:465-480`: `_args_hash_for` hashes
  `config_payload(rc.job_config)` plus `call_kwargs - context.injected`.
- `_engine/executor.py:2463-2464`: `_resolve_group_options` puts the resolved
  instance into `call_kwargs` and adds its name to `context.injected`, so the
  writer drops it together with the DI capabilities.
- `_engine/executor.py:450`: the design comment says resolved GroupOptions
  are covered "via config resolution". The code does not support this.
  `rc.job_config` is the job's own config model, resolved against the job's
  section. A `GroupOptions` class is resolved separately, against the
  *group's* section (`_make_config_view(group_path, scope="group")`), and
  never reaches `job_config`.
- `_engine/executor.py:517`: the reader `fingerprint_key_for` hashes
  `config_payload(config)` with `{}`. It cannot see the option either, so
  readers and the writer agree on a key that is wrong for both.
- `_primitives/fingerprint.py:122`: the hashed payload is
  `{"config": ..., "args": ...}`. It has no field for anything else.

Reproduced at authoring time by
`tests/group_options/test_group_options_freshness.py` on unmodified `master`:
9 failed, 2 passed. The two that passed were the same-option hit and the
`why` agreement, which hold before the fix because both sides ignore the
option. The cross-process test printed `REPORT target=b scanned=a`.

## Decision (acceptance criterion 4)

**A resolved GroupOptions value belongs in the key. The comment at
`executor.py:450` is wrong and is corrected.** Config resolution does not
cover the option, so the report's consequence is reachable (shown above), not
hypothetical.

This follows `contributor/reference/pitfalls.md` §21. A key holds what a later
reader in another process can reconstruct. A capability instance fails that
test. A resolved `GroupOptions` value passes it: the reader resolves it with
the same `_config_resolver`, the same group section and the same option
layer the writer used. The executor's "injected" set is a correct way to
exclude capabilities, but it does not mean "unreconstructable". The option is
injected and reconstructable at once, so it is counted on its own.

## The behavior after

- Two runs of a cached job with the same explicit arguments and different
  resolved GroupOptions values write and read **different** freshness records.
  "Resolved" means after precedence: default < config file < vault < env <
  group CLI. A value changed through any layer changes the key.
- Two runs with the same resolved value share a record, as before.
- A job that declares **no** GroupOptions parameter has exactly the key it had
  before the change. The hashed payload gains a field only when the job has
  something to put in it. Records written before the change still match.
- Every reader builds the key from the same option layer as the writer:
  - the `FromJob` value read (`_from_job_value`);
  - the "is the recorded value reusable" check in the dependency pass;
  - `func builtin why`.

  The `FromJob` read and the dependency check use the consumer's
  group-option layer. After #106, that is the same layer its dependencies
  ran under.
- A reader that cannot resolve an option, for example a required field with
  no value, treats that option as unknown. It addresses a key no writer
  produces, so the read misses. It does not fall back to the option-blind
  key, because that key could return a record from before the change.

### Deliberate behavior changes

- A cached job that declares a GroupOptions parameter misses **once** after
  upgrading. Its records were written under the option-blind key, and the new
  key never matches them. Jobs without group options are not affected.
- `Exec(run="once"|...)` deduplication uses the same args hash, so two calls
  that differ only in a resolved group option are no longer treated as
  duplicates. This is the same defect seen through a second consumer.

## Order relative to the delivery fix

The body asks for the delivery fix to land first, or for a statement of why
the order does not matter. It has landed: `fix(engine): propagate group
options to dependencies (#106)` is on `master` at `206e42de`, below this
branch's base. The order would not matter anyway. #106 decides *which* option
value a dependency resolves. This change decides *whether a record answers
for* the value that was resolved. Each fix is correct without the other.
With both in place, the dependency scheduled for `report --target b` resolves
`b` (#106), its pre-flight keys on `b` (this change), and the consumer's
reader keys on `b` (this change).

## Out of scope

- How the option reaches a dependency (the delivery fix above). Its files are
  not touched.
- Fingerprint content other than GroupOptions (sources, arguments).
- `func builtin why` with typed group flags. `why` accepts no group-CLI
  layer, so it explains the run a plain `func <job>` would make (file, env and
  default layers). This matches its current behavior for job config.

## Acceptance criteria

Each criterion is a gate and was run at authoring time against the code after
the change.

- **AC-1: a changed option misses.** Same job, same explicit arguments,
  `target=a` then `target=b`: both bodies run. A value changed through the
  environment does the same. a → b → a reruns nothing on the third call.
  Gate: `uv run pytest tests/group_options/test_group_options_freshness.py -q`
  (`TestTheKeyFollowsTheOption`).
- **AC-2: an unchanged option hits.** `target=a` twice: the second run is
  `SKIPPED`. A job without group options keeps a byte-identical key
  (`TestTheKeyFormula::test_a_job_without_group_options_keeps_its_key`). The
  warm path adds one cached tuple lookup per run for a job without group
  options, and one `model_dump` per declared option otherwise.
  Gate: same command.
- **AC-3: `FromJob` never crosses option values.** `scan --target a`, then
  `report --target b` receives `b`, both in process and across separate
  `func` processes (the report's own shape). A `run=False` reader under `b`
  receives its default, not `a`'s record.
  Gate: same command (`TestFromJobNeverCrossesOptionValues`,
  `TestTheReportAcrossProcesses`).
- **AC-4: the comment and the code agree.** The design table at the key
  derivation lists resolved GroupOptions as **in** the key, with the reason.
  Gate: reading `_engine/executor.py` at the key derivation, plus the
  decision recorded above.
- **AC-5: both directions and the injected case are pinned.** The tests
  cover the hit, the miss, and the writer counting the injected option while
  still excluding an injected `Log` capability. The reader's key is checked
  to equal the writer's.
  Gate: same command (`TestTheKeyFormula`).
- **AC-6: existing key agreement holds.** The cross-process key-agreement
  suite and the group-options suites pass unmodified.
  Gate: `uv run pytest tests/pipeline/test_fingerprint_key_agreement.py tests/group_options/ tests/test_fingerprint.py tests/test_from_job.py -q -n auto`.
