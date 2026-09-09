# Plan — surface-request-parity

---

## 1. The approach in one line

**Give three doors the syntax to fill the fields F1 gave them, close the accidental channel
that stood in for it, and turn the hand-maintained parity matrix into a suite.**

## 2. The shape of the work

Three unrelated-looking pieces that are one:

| Piece | Why it belongs here |
|---|---|
| Real channels for `Invoke`, HTTP, Lambda, MCP | the gap F1 leaves |
| Closing the `**kwargs` splat | the *same* change — the accidental channel is what stood in for the real one |
| The seal, and the contract that forbids the edge | what makes the parity claim structural rather than conventional |

## 3. Files to change

### New

```
tests/integration/test_surface_feature_matrix.py    every §B row, both surfaces
tests/adapters/test_adapters_do_not_import_engine.py
plugins/functualize-http/tests/test_request_envelope.py
plugins/functualize-lambda/tests/test_request_envelope.py
plugins/functualize-mcp/tests/test_three_doors_agree.py
```

### Modified

```
src/functualize/_engine/capabilities/invoke.py     group_option_values keyword
src/functualize/app/adapters/click_params.py       3 _engine imports removed
src/functualize/app/adapters/lazy_command.py       1 removed; the TTY route shared
src/functualize/app/adapters/surface_gate.py       1 removed
src/functualize/types/__init__.py                  MissingValueError, terminal_available made public
pyproject.toml                                     the new forbidden edge
plugins/functualize-http/.../__init__.py           the envelope
plugins/functualize-lambda/.../__init__.py         the envelope, both handlers
plugins/functualize-mcp/.../_tools.py              group_option_values + scope_id on 2 doors
plugins/functualize-mcp/.../_translator.py         group fields become declared properties
docs/guides/group-options.md                       #17's boundary moved, and why
```

## 4. Risks

- **R-a · The HTTP/Lambda envelope change is breaking for live callers.** A body that was
  splatted as job arguments now needs `arguments`. *Mitigation:* it is the fix, not a side
  effect — the flat shape is what let `scope_id` bind to a control parameter. Both plugin
  READMEs get a before/after; pre-release stance covers the break; the plugins are versioned
  separately and get a minor bump.

- **R-b · MCP's per-job tools regress while the generic doors gain.** They are schema-driven
  and already correct. *Mitigation:* `test_three_doors_agree.py` asserts all three produce the
  same result for the same inputs — the property, not three separate tests.

- **R-c · The parity suite is huge and slow.** 16 rows × 2 surfaces, some needing a workflow
  and a gate. *Mitigation:* it uses the in-process `cli_run` fixture (< 100 ms per case, the
  CLI-integration tier), and rows needing a real PTY are marked `slow` and excluded from
  `test-fast`.

- **R-d · A §B row turns out to be untestable and gets dropped silently.** *Mitigation:*
  AC-10 requires a row to be a passing case **or a recorded finding**. Dropping without a
  record is the failure mode this whole feature exists to prevent.

- **R-e · Making `terminal_available` public enlarges the public surface.** *Mitigation:* it
  is already imported by two adapters, so it is public in practice and private only in
  spelling. Naming it makes the existing coupling visible and testable.

- **R-f · `Invoke`'s new keyword changes nested behaviour by accident.** *Mitigation:*
  `None` means inherit, which is today's behaviour; a test asserts a bare `rc.invoke(job)` is
  byte-identical before and after, and it is written before the keyword is added.

## 5. Ordering

```
W0  Invoke gains the keyword (default None = inherit)
W1  MCP's three doors agree
W2  HTTP and Lambda envelopes
W3  the five _engine imports leave the adapters
W4  the import contract forbids the edge          ← after W3, so it lands green
W5  the parity suite over every §B row
W6  docs: #17's boundary, both plugin READMEs
W7  checkpoint
```

W4 after W3 is the one ordering that matters: a contract added before the imports are gone
lands red, and a red contract in CI teaches people to ignore it.

## 6. What this plan does not do

It adds no `RunRequest` field, changes no flag spelling, and does not reduce the door count.
A tenth door should be cheap — that is the measure of success (`07-surface-parity.md` §F), not
a smaller table.
