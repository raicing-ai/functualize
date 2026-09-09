# T11 — Completions read the grammar — Report

Date: 2026-09-09 · Worktree: `.worktrees/pi-parity` · No git commands used.

## Defect

`src/functualize/_cli/completions/data.py::_flag_opts` looped only over
`getattr(param, "opts", ())`. `build_click_params_from_fields` renders a `bool`
field as the click pair `--x/--no-x`; click stores the positive spelling in
`param.opts` and the NEGATIVE spelling in `param.secondary_opts`. So shell
completion never offered any `--no-` flag, while the CLI accepted it and the
TUI SmartBar offered it.

Reproduced first (real output):

```
opts= ['--cache'] secondary_opts= ['--no-cache']
completions offers: ['--cache']
```

## Change

`src/functualize/_cli/completions/data.py` only (net +10 lines; 212 → 222):

- `_flag_opts` (lines 58–84) now iterates
  `(*getattr(param, "opts", ()), *getattr(param, "secondary_opts", ()))` —
  positive spellings before the negative half of any pair, keeping the existing
  `opt.startswith("-")` filter. No import of `negative_flag_for` added; the
  builder already applied it.
- Docstring extended to say *why* both halves are read: the builder renders a
  bool as `--x/--no-x`, click stores the negative in `secondary_opts`,
  `negative_flag_for` (applied inside the builder) decides whether the negative
  half exists (a sibling literally named `no_x` owns the spelling and the pair
  collapses to `--x` alone), and reading only `opts` silently dropped every
  `--no-` flag.

`tests/_cli/test_completion_flag_pairs.py` (new, 68 lines): 4 tests —
bool yields both pair halves; bool with sibling `no_cache` yields no invented
negative (exact-list pin: `--no-cache` appears once, owned by `no_cache`;
`--no-no-cache` is `no_cache`'s real negation, as click parses it); non-bool
unchanged; completion list equals the union of every param's
`opts` + `secondary_opts` from the same fields.

## Gates

Gate 1 — `rg -c 'secondary_opts' src/functualize/_cli/completions/data.py`
- before: `0` · after: `2`

Gate 2 — `uv run python -c "from functualize._cli.completions.data import _flag_opts; from functualize._types.descriptors import FieldDescriptor; print(_flag_opts([FieldDescriptor(name='cache', type_annotation='bool', default=True, description='', required=False)]))"`
- before: `['--cache']` · after: `['--cache', '--no-cache']`

## Verify commands (real output, tails)

1. `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/`
   — exit 0 both; log tail:
   ```
   All checks passed!
   1098 files already formatted
   ```
2. `uv run mypy src/functualize/_cli/completions/data.py` — exit 0; output:
   ```
   Success: no issues found in 1 source file
   ```
3. `uv run lint-imports` — exit 0; output tail:
   ```
   Analyzed 333 files, 882 dependencies.
   Contracts: 6 kept, 0 broken.
   ```
4. `uv run python -c "import functualize._cli.completions.data"` — exit 0, no output.
5. `uv run pytest tests/_cli tests/cli -q -p no:randomly` — exit 1,
   `5 failed, 2693 passed, 550 skipped`. The 5 failures are NOT caused by this
   change:
   - `tests/_cli/test_snapshot_baseline.py` (4: empty_state, ready_bar,
     panel_ring_open, modal_open): textual snapshot mismatches. `_flag_opts` is
     consumed only by the shell-completion path (`builtins.py` → `func builtin`
     completion generation); no TUI render path imports it, and the snapshot
     report contains no flag/`--no-`/completions content. Control experiment:
     with the fix fully reverted in `data.py`, the same 4 snapshot tests still
     fail (`4 failed, 1 warning in 2.71s`) — pre-existing on this worktree,
     from concurrent sibling edits to shared TUI/bar code, not this change.
   - `tests/_cli/test_self_doctor.py::test_a_recognised_installation_reports_ok`:
     environmental. Failure text: stale installs found in a *sibling worktree* —
     `/home/viltohmyst/code/raicing-ai/functualize/.worktrees/mcp-server-fixes/.venv/bin/func=warning (0.2.3 unknown [stale])` — plus
     `'not a terminal (piped or redirected)'`. Unrelated to these two files.
   - The new file passes on its own: `4 passed in 0.13s` (and again `4 passed
     in 0.15s` after the sabotage restore).

## `_field_choices` — checked, NOT a bug, not changed

`_field_choices` keys `flag_choices` by the first `--long` opt of `param.opts`
for fields that carry `choices`. Choice-bearing fields are enum-valued value
options (`is_flag=False`) — the builder never gives them a secondary negative
half, so nothing is dropped by reading only `opts`. Booleans have no `choices`
and are skipped by the `if not values: continue` guard before any param lookup,
and a negative `--no-x` spelling never takes a choice value anyway. Same-bug
shape absent; left unchanged.

## Sabotage proof

Broke: removed the `secondary_opts` half again (loop back to
`getattr(param, "opts", ())`) by editing the file — no git.

Failing tests (3 of 4; the non-bool test has no negatives, correctly unaffected):

```
FAILED tests/_cli/test_completion_flag_pairs.py::test_boolean_field_yields_both_pair_halves
E       AssertionError: assert ['--cache'] == ['--cache', '--no-cache']
E         Right contains one more item: '--no-cache'
...
FAILED tests/_cli/test_completion_flag_pairs.py::test_bool_with_sibling_named_no_cache_gets_no_invented_negative
E       AssertionError: assert ['--cache', '--no-cache'] == ['--cache', '...-no-no-cache']
E         Right contains one more item: '--no-no-cache'
...
FAILED tests/_cli/test_completion_flag_pairs.py::test_completion_list_agrees_with_what_click_accepts
E       AssertionError: assert ['--cache', '..., '--retries'] == ['--cache', '..., '--retries']
E         At index 2 diff: '--env' != '--no-no-cache'
E         Right contains one more item: '--retries'
...
3 failed, 1 passed in 0.16s
```

Restored by editing the file back (no git checkout). Re-run green:
`4 passed in 0.15s`; ruff check + format --check exit 0; gate 1 back to `2`.

## Not done / questions

- The 4 snapshot-baseline failures and the self-doctor failure pre-date this
  change (control run with the fix reverted fails identically). They belong to
  concurrent sibling work in this shared worktree; the orchestrator should
  decide snapshot regeneration or leave to the owning agent. I did not touch
  `__snapshots__/` or the self-doctor test (whitelist + no-weakening rules).

---

## Orchestrator verification (re-run independently, not taken from the above)

Every claim in this report was re-run rather than read.

| Claim | Re-run result |
|---|---|
| Gate 1 `secondary_opts` count | `2` ✓ |
| Gate 2 `_flag_opts` on a bool | `['--cache', '--no-cache']` ✓ |
| ruff check / format | clean, 1098 files formatted ✓ |
| mypy on `data.py` | Success ✓ |
| lint-imports | 6 kept, 0 broken ✓ |
| Sabotage | 3 of 4 tests fail, restored, green ✓ |
| `_field_choices` is not the same bug | Confirmed by measurement: a `choices`-bearing field renders `is_flag=False`, `opts=['--env']`, `secondary_opts=[]` — there is no second half to drop ✓ |
| Completion equals what click accepts | Confirmed independently: union of `opts` + `secondary_opts` over `{cache, no_cache}` equals `_flag_opts` output ✓ |

**On the 4 escalated snapshot failures — the agent was right to escalate, and
they are now gone.** `tests/_cli/test_snapshot_baseline.py` → `4 passed, 4
snapshots passed`, and the full `tests/_cli tests/cli` run is `1 failed, 2697
passed` with the only red being the environmental `self_doctor` check that reads
a sibling worktree's stale venv off `PATH`.

They were **transient, caused by a concurrent sibling agent** editing
`app/adapters/click_params.py` for F2 T9 while this agent's suite ran — that
file renders the flags the SmartBar snapshot draws. The agent's control
experiment (revert the fix, same 4 still fail) correctly proved the failures were
not its own, but could not see that the cause was a half-written file in a
shared worktree rather than committed sibling work.

**Regenerating those snapshots would have baked a mid-edit render into the
baseline.** Refusing to touch `__snapshots__/` was the correct call, and the
whitelist that forbade it did its job.

The lesson is the orchestrator's, not the agent's: running several agents in one
worktree means a suite can go red for reasons that are neither the agent's change
nor a real defect, and only the orchestrator can tell which. Escalate-don't-fix
is the right contract for an agent under those conditions.
