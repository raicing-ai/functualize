# Plan — run-request-entry

---

## 1. The approach in one line

**Freeze a run's inputs into one value object, move resolution inside the engine, and let the
facade be the only door — so the fixes for D-1, D-2, D-3 and D-13 are consequences rather than
patches.**

## 2. Order within the feature

The audit recommends landing the three divergences first and separately. Under one-PR they are
ordered first *within* this feature instead (spec §7). Concretely that means waves 0–2 make the
divergences *expressible* and waves 3–6 make them *true*:

```
W0  RunRequest exists                         (nothing depends on it yet)
W1  engine.run(request) beside execute()      (transitional, labelled)
W2  the facade takes a request
W3  every door builds one                     (the big wave, file-disjoint)
W4  execute() deleted; resolution moves in    (the risky commit)
W5  deposits become fields; the new flags     (D-1, D-2, D-3 become true)
W6  history, dead argument, perf phase, checkpoint
```

## 3. Two things that must move verbatim, and one that must not move at all

**Must move verbatim** (`RAD.4` — the riskiest change in the set):

- the config-model / job-kwargs split, `app/adapters/click_params.py:1099-1104`
- stdin-marker resolution, `click_params.py:1108-1124`

Both currently live in the eager click callback and are re-stated by the lazy wrapper. They
move into `engine.run` **unchanged in behaviour**, in the same commit as the deletion of
`execute()`, with `TestWarmBootParity` and `tests/group_options/` as the gate. Splitting the
move from the deletion would leave a half-state where two implementations exist.

**Must not move**: `_execute_lifecycle`. `run()` resolves, then calls the lifecycle it already
calls. `tests/engine/test_lifecycle_order.py` is green at every commit — that is how we know
the moves were pure.

## 4. Files to change

### New

```
src/functualize/_types/run_request.py
tests/types/test_run_request.py
tests/engine/test_engine_run_entry.py
tests/app/test_event_submit_scope.py          # D-13
tests/cli/test_app_surface_prompt_gates.py    # D-1
tests/cli/test_app_surface_output_format.py   # D-2
tests/integration/test_force_on_every_door.py # D-3
tests/app/test_control_inputs_are_not_kwargs.py  # the accidental channel
```

### Modified

```
src/functualize/_engine/executor.py            run() added, execute() deleted, resolution moves in
src/functualize/_types/__init__.py             re-export RunRequest, Surface
src/functualize/app/core.py                    execute(request); drop the registry lookup at :620-621
src/functualize/app/utils.py                   re-export RunRequest, Surface for _cli
src/functualize/app/adapters/click_params.py   callback builds a request; kwargs-split leaves
src/functualize/app/adapters/lazy_command.py   same, for the lazy path
src/functualize/app/adapters/cli.py            root callback registers --prompt-gates/--output
src/functualize/app/commands.py                registration unaffected; execution path updated
src/functualize/_app/impl.py                   :861 goes through the facade (D-13)
src/functualize/_cli/main.py                   4 deposit sites become request fields
plugins/functualize-http/src/functualize_http/__init__.py     builds a request
plugins/functualize-lambda/src/functualize_lambda/__init__.py builds a request
plugins/functualize-mcp/src/functualize_mcp/_tools.py         builds requests (2 doors)
plugins/functualize-mcp/src/functualize_mcp/_server.py        builds a request
tests/perf/test_startup_budget.py              warm-cache func <job> phase (T8)
docs/guides/…                                  --prompt-gates / --output now on both surfaces
```

## 5. Risks

- **R-a · The kwargs-split move changes behaviour invisibly.** The split decides which
  arguments reach a config model and which reach the job. A silent change shows up as a
  missing config value, not an error. *Mitigation:* move it in one commit with
  `tests/group_options/` (`--run-slow`, both surfaces) and `TestWarmBootParity` as gates, and
  sabotage-check by breaking the split and confirming the group-options matrix goes red.

- **R-b · Eager and lazy click drift during the move.** Two constructors, one contract —
  `pitfalls.md` §23. The eager path binds a function at build time and the lazy path
  materializes from a descriptor. *Mitigation:* both build a request through **one** helper;
  a test asserts the two paths produce equal requests for the same argv.

- **R-c · Deleting `execute()` breaks out-of-tree plugins silently.** Not enumerable from this
  repo (`RAD.2`). *Mitigation:* a plugin-guide release note, and `AdapterPlugin` already only
  promises `__call__(app)`.

- **R-d · `surface` becomes a lie.** A door that copies another door's construction inherits
  its surface value, and provenance silently misreports. *Mitigation:* the closed `Literal`,
  plus a test that every door in the contracts §5 table produces its own value end to end.

- **R-e · `func why`'s second verdict engine is orphaned.** `app/core.py:725-823` walks
  `engine.materialize_job` and `_declared_dep_names` (`RAD.6`, C-9). *Mitigation:* it is on
  the modified list; `func builtin why` has its own tests and they run in this feature's gate.

- **R-f · The accidental channel closes and someone was using it.** Three doors currently
  accept `scope_id` in a payload ([01 §B.2](../../../contributor/architecture/run-model/01-current-state.md)).
  Closing it is correct and is a behaviour change for anyone who found it. *Mitigation:* the
  real channel lands in the same feature, so there is a supported replacement on day one;
  release note.

- **R-g · The perf phase is added but never fails.** A budget that cannot go red is decoration
  (`12 §C`). *Mitigation:* author it by running it, record the measured number, and set the
  budget from measurement — then sabotage by inserting a sleep and confirming it fires.

- **R-h · Wave 3 is large.** Fifteen files build requests. *Mitigation:* the waves are
  file-disjoint by construction, and W3 is split into four sub-waves by owning package
  (`_cli`, `app/adapters`, plugins, `_app`), each independently green.

## 6. The one thing this plan does not do

It does not give `Invoke`, HTTP or Lambda the *syntax* to fill a group-option field — that is
F4. This feature gives every door a request with the field on it; three doors will build
requests that leave it `None`, exactly as they do today. That is a smaller gap than the one
they have now, and it is closed by name in the next feature rather than left implicit.
