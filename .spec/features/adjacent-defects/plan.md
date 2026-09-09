# Plan — adjacent-defects

---

## 1. The approach in one line

**Ten independent repairs, ordered cheapest-first, with the one architectural item last and
withdrawable.**

## 2. Why this is one feature and not ten

Each item is one to three files and none depends on another, so a wave graph over them is
almost flat. They are bundled because the *review* is the expensive part: a reviewer reading
"delete a field nobody sets" needs the same context ten times, and that context — the audit,
the STATUS ledger, this document set — is what makes each repair obviously correct rather than
obviously arbitrary.

## 3. Files to change

### Modified

```
src/functualize/_discovery/cached_provider.py     conflict is rendered, not raised
src/functualize/_app/boot.py                      catches it at the boot seam (ADR-018 surface)
src/functualize/app/utils.py                      read_group_options_from_cache takes a fingerprint
src/functualize/_engine/capabilities/job_context.py   deadline removed
src/functualize/_events/_catalog_entries.py       three entries emitted or removed
plugins/functualize-mcp/src/functualize_mcp/_workflow_tools.py   _deposit removed
tests/perf/test_startup_budget.py                 the false comment
src/functualize/app/_workflow_control.py          the false docstring
src/functualize/_cli/skills.py                    cached entry_points
src/functualize/_cli/tui/display_provider_discovery.py   cached entry_points
plugins/functualize-ai/src/functualize_ai/_provider_discovery.py  cached entry_points
src/functualize/app/adapters/click_params.py      enum round-trip (#38)
src/functualize/_discovery/…                      SyntaxError survives a warm cache (#27)
src/functualize/app/adapters/cli.py               unknown-command explanation (#37)
src/functualize/_cli/main.py                      single-file second boot (last, withdrawable)
contributor/architecture/layer-contract-blind-spot.md   NEW — the 47-violation measurement
```

## 4. Risks

- **R-a · #27 is a cache-invalidation change and cache bugs are the repo's recorded speciality.**
  ADR-011, F2, F3 and the X1–X4 matrix are all this shape. *Mitigation:* reproduce the
  asymmetry first as a failing test (a `SyntaxError` module and a `ModuleNotFoundError` module
  in one tree, run twice), and fix only the reporting path — do not touch `discovery_hash`.

- **R-b · #38's enum conversion has two surfaces that already disagree.** The CLI produces
  `str`, the programmatic path produces the member. Converting at the click layer makes them
  agree; converting in the engine would change the programmatic path too. *Mitigation:*
  convert where the `click.Choice` was rendered — `_click_type_for`'s inverse — so the
  programmatic path is untouched, and assert both in one test.

- **R-c · The single-file second boot may be load-bearing.** It exists to register peers, and
  0.3.0 already patched a double-registration bug in it. *Mitigation:* it is the last task, in
  its own wave, and spec §3.2 pre-authorises withdrawal with a recorded reason. **A withdrawal
  is a success here, not a failure** — the alternative is a forced change to routing.

- **R-d · Deleting `JobContext.deadline` looks like removing a feature.** *Mitigation:* the
  release note says what replaces it and when (F5's lease), so it reads as a correction rather
  than a regression.

- **R-e · The `TYPE_CHECKING` item produces no code change and can therefore be skipped.**
  *Mitigation:* its deliverable is a committed document with numbers, and AC-3 gates on the
  document existing. A measurement that is not written down was not made.

## 5. Ordering

Cheapest and most independent first, so the feature delivers value even if it is interrupted:

```
W0  false comments, dead names          (pure deletion, no behaviour)
W1  entry_points callers + the count test
W2  the TYPE_CHECKING measurement       (document only)
W3  rendered conflict · cache fingerprint    (two independent repairs)
W4  #38 enum · #37 explanation · #27 parse failure
W5  single-file second boot             (alone, withdrawable)
W6  checkpoint
```

## 6. What this plan does not do

It does not touch `app/utils.py` beyond one signature, does not flip the import-linter flag,
and does not open STATUS #4 or #22. Those boundaries are in
`contributor/architecture/run-model/11-boundaries.md` and `13-roadmap.md` §E.
