# Plan — run-outcome-authority

---

## 1. The approach in one line

**Give the failure-set rule and the report line a home beside the tables that already have
one, then delete every local copy — and do the same for the flag vocabulary.**

## 2. Two halves, one shape

The outcome module and the flag grammar are separate subsystems that share a shape: *one
authority, N consumers, a parity test that pins N.* They are one feature because the second is
the first's rehearsal — `negative_flag_for` already proved the move works, and its history
(five sites planned, six found) is the argument for why the count needs a test.

Order: outcome first (it carries the D3 decision, which is the feature's only user-visible
change), grammar second.

## 3. Files to change

### New

```
src/functualize/_types/outcome.py
src/functualize/_types/flag_grammar.py
tests/types/test_outcome_families.py
tests/tui_audit/test_panel_agrees_with_table.py
tests/types/test_flag_grammar_roundtrip.py
tests/types/test_flag_grammar_consumer_count.py
```

### Modified

```
src/functualize/_types/exit_codes.py            re-export from outcome.py
src/functualize/_types/http_status.py           contents move; module removed or re-exports
src/functualize/_types/naming.py                negative_flag_for moves to flag_grammar
src/functualize/types/__init__.py               public re-exports
src/functualize/app/utils.py                    the _cli corridor
src/functualize/app/adapters/click_params.py    declares PROCESS; loses the failure set and report line
src/functualize/_cli/tui/job_execution.py       declares PANEL for render, PROCESS for exit
src/functualize/_cli/builtins.py                parallel + _resume_exit read the module
src/functualize/_cli/dispatch.py                keeps syntax; vocabulary leaves
src/functualize/_cli/tui/bar.py                 reads the grammar
src/functualize/_cli/tui/sync.py                reads the grammar
plugins/functualize-mcp/.../_tools.py           wire_status reads the module
plugins/functualize-http/.../__init__.py        declares WIRE
plugins/functualize-lambda/.../__init__.py      declares WIRE
```

## 4. Risks

- **R-a · The TUI exit change is user-visible and breaks scripts.** Anyone wrapping the inline
  TUI and testing `$? == 0` sees a paused workflow as failure now. *Mitigation:* it is the
  same break 0.3.0 already took for `workflow resume`, with the same reason; CHANGELOG entry
  quoting that precedent. This is a decision (**J3**), not an accident.

- **R-b · Splitting panel from process invites getting them backwards.** A future edit could
  make the panel exit 5 and the process print `✓`. *Mitigation:* the parity test asserts
  both families for the same status in one test body, so a swap fails loudly.

- **R-c · Moving `negative_flag_for` breaks an out-of-tree import.** It is public API.
  *Mitigation:* it keeps its name and its `functualize.types` / `functualize.app.utils` import
  paths — only the defining module changes.

- **R-d · The grammar move is pure and therefore untested by construction.** A pure move that
  compiles looks correct. *Mitigation:* the round-trip test (`emit(resolve(text)) == text`)
  runs across every consumer, and the sabotage is to diverge one alias in the click builder
  only.

- **R-e · The consumer-count test becomes a nuisance and gets deleted.** A test that fails
  whenever someone legitimately adds a consumer is a test people remove. *Mitigation:* it
  asserts the count **and prints the list**, so updating it is one obvious line and the diff
  shows a reviewer that a consumer was added.

## 5. Ordering

```
W0  outcome.py exists, tables re-exported through it   (no consumer changes)
W1  is_failure / report_line / string mapping added    (still no consumer changes)
W2  five consumers re-pointed                          (file-disjoint)
W3  the TUI's two families, and the D3 exit change     (alone — the only behaviour change)
W4  flag_grammar.py exists, vocabulary moved
W5  four grammar consumers re-pointed                  (file-disjoint)
W6  the two count/round-trip tests
W7  checkpoint
```

W0 and W1 are deliberately inert: the module exists and nothing uses it, so the suite proves
the move is behaviour-free before any consumer depends on it.

## 6. What this plan does not do

It does not change a single exit code or HTTP status **value**, and it does not touch any
door's inputs. If this feature has changed what a job does, something has gone wrong.
