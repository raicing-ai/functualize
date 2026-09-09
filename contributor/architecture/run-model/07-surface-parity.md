# 07 · Surface parity — from a matrix you maintain to a property you inherit

`TGT.7`, and feature **F4**. The coverage audit's §B matrix is 16 feature rows × 8 surface
columns, hand-maintained, and it was already wrong in one cell when it was written
([Appendix A §C](appendix-a-audit-synthesis.md)). This document is about deleting the matrix,
not extending it.

---

## A. The matrix is a symptom

A parity matrix exists because parity is not structural. Each cell is a decision somebody
made, in a different file, at a different time — so the matrix must be *maintained*, and
maintaining a table of 128 cells across 19 executing doors is not a thing anyone does.

The evidence that it is not maintained is in the matrix itself: the audit placed D-13's
failure in the `rc.invoke` column, and `rc.invoke` is one of the doors that gets it right
(`_engine/capabilities/invoke.py:398,406`). A table nobody can check drifts in both
directions — it under-reports real gaps and invents fake ones.

## B. What the gaps actually are, after F1

F1 gives every door a `RunRequest`, which closes the *deposit-shaped* gaps: `--prompt-gates`,
`--output` and `--force` become fields, so every door can carry them. What F1 does **not** do
is give a door the *syntax* to fill a field. That is this feature.

Three gaps survive F1, and one of them is the opposite of a gap:

| id | Gap | After F4 |
|---|---|---|
| **D-4** | `rc.invoke` cannot pass group options (STATUS #17) | `Invoke` takes a request; group options are a field |
| **D-5** | MCP is split three ways — `_server.py:278` passes `group_option_values`, `_tools.py:287` and `:450` do not | all three build requests; the split has nowhere to live |
| **D-6** | HTTP and Lambda have no group-option or resume channel | both build requests, with the channel in the schema |
| **B.2** | HTTP, Lambda, MCP `run_job` and the async worker have an **accidental** resume channel — a body key named `scope_id` binds to the control parameter ([01 §B.2](01-current-state.md)) | closed by construction: control inputs are request fields, job arguments are `kwargs`, no dictionary crosses between them |

That last row is why F4 is not merely additive. Three doors are documented as having no resume
channel and in fact have an unvalidated one. **Giving them a real channel and closing the
accidental one is the same change**, and doing only the first would leave the second.

## C. STATUS #17 is a boundary this set moves

`docs/guides/group-options.md` records `Invoke` having no group-option channel as
**deliberate**: an in-process nested call inherits its parent's configuration and should not
re-negotiate it.

That reasoning was sound when the alternative was adding a twelfth parameter. Under
`RunRequest` it inverts: the request already carries `group_option_values`, so *withholding*
it from `Invoke` now costs a deliberate erasure — code that builds a request and then blanks a
field. The boundary stops being free, and a boundary that costs code needs a reason stronger
than "it was free".

**Decision: `Invoke` carries group options; inheritance stays the default.** `rc.invoke(job)`
inherits the parent's values, as today; `rc.invoke(job, group_option_values=…)` overrides.
The guide is updated, and the update says the boundary moved and why.

`parallel` is untouched: items still run with `parent_scope=None`
(`_engine/capabilities/invoke.py:603`, *"Independent — no shared scope"*), because a parallel
batch is not a nested walk.

## D. The guarantee, and how it is enforced

> A feature a job author declares works on every door **by construction**, because a door
> passes an opaque request and receives a `JobResult`. There is nothing per-door to forget.

That sentence is only worth writing if something fails when it stops being true. Three things
do:

**1. The dual-surface harness, over every feature row.** `cli_run` (`tests/conftest.py:454`)
is already parameterised over `func` | `app`, and it already earned its keep — it caught the
epilog and capability-leak defects (ADR-010 §5). F4 extends it to every row of the audit's §B
table, so the matrix becomes a test rather than a document. **A row that cannot be expressed
as a test is a row that was never true.**

**2. The seal.** Audit step 9: delete the last `app/adapters/* → _engine` imports
(`click_params.py:1068-1090`, `lazy_command.py:80`, `surface_gate.py:37`). After it, an adapter
*cannot* reach the engine to re-derive anything — the import fails `lint-imports`, which runs
in CI as its own job.

**3. Provenance.** Every request names its door (`RunRequest.surface`, a closed set). A new
door that does not declare itself does not construct.

## E. What stays per-door, deliberately

Parity is not uniformity. Three things remain per-door and should:

| | Why |
|---|---|
| **Syntax** | `--output json` on a CLI, a JSON field over HTTP, a tool parameter over MCP. The vocabulary is shared ([06 §E](06-outcome-authority.md)); the spelling is not |
| **Family choice** | a panel is not a process is not a wire. One greppable word ([06 §D](06-outcome-authority.md)) |
| **Pre-boot-only flags** | aliases, `--exclude`, and `--perf-report`'s optional-value lookahead are *about reaching the program*, not about the run. They stay `func`-only, and `flag_grammar` says so |

The test for whether something belongs in the request: **does a job author's declaration
depend on it?** `--prompt-gates` changes how a declared `Gate` behaves — request. `--exclude`
changes which modules are scanned before any declaration is read — pre-boot.

## F. The measure of success

Not "the matrix is all ✓". The matrix should not exist.

The measure is the cost of the twentieth executing door. Today it is five independent
decisions — resolution, scope, group options, force, outcome — each of which has been got
wrong at least once by an existing door. After F4 it is a `RunRequest` and a family choice,
and the parity harness tells you immediately which rows you did not wire.
