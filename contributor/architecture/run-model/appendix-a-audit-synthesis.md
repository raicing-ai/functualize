# Appendix A · Reconciling the two audits

Two audits ran in parallel against `c0c921f`, from opposite directions — one enumerating
surfaces, one reasoning from causes — and converged. That convergence is the strongest thing
about the evidence base. But they were reconciled once, into a synthesis document, and the
reconciliation introduced two inconsistencies that a reader of all three will hit. This
appendix records them so the merge is a decision rather than a silent choice.

---

## A. "Cause 4" names two different things

| Source | Cause 4 is… |
|---|---|
| `audit-engine-encapsulation.md` §1 (depth) | `func`'s pre-boot layer is a permanent second CLI, and the "one rule" fixes are per-rule hand extractions, not a mechanism |
| `.spec/shape-intents/entrypoint-encapsulation/shape-intent.md` (synthesis) | **The deposit protocol is the divergence generator** |
| `contributor/adr/020-…` | follows the depth audit |

Both claims are true and neither implies the other. The problem is that the divergence ids
hang off different ones: **D-1, D-2, D-3, D-5 and D-13** are consequences of the *deposit
protocol*, while the depth audit's **step 5** (`flag_grammar`) is a consequence of the
*pre-boot second CLI*. A reader following "Cause 4" from one document into the other lands in
a different argument.

The synthesis compressed to four causes, as the depth audit had; each dropped a different
fifth. So this set uses **five**, renumbered once, and never reuses the old numbers
(decision **M3**):

| id | Cause | Lands in |
|---|---|---|
| **C-I** | The entry contract is unresolved — 13 parameters, two of them the result of a resolution the caller performed | [04](04-request-and-entry.md) → F1 |
| **C-II** | The engine is unsealed — completed by its owners after construction, read back through message chains | [05](05-engine-seal.md) → F3 |
| **C-III** | Delivery is a per-surface act — the tables are shared, the failure-set rule is not | [06](06-outcome-authority.md) → F2 |
| **C-IV** | The deposit protocol — delivery state parked on the app and read back by the kernel | [04 §B](04-request-and-entry.md) → F1 |
| **C-V** | The pre-boot vocabulary has no home — one rule extracted by hand, seven consumers, no test | [06 §E](06-outcome-authority.md) → F2 |

C-I and C-IV are separate causes with one fix, which is why F1 is the largest feature.
C-III and C-V are separate causes with one *shape* of fix — one authority, parity-tested —
which is why they share F2.

## B. 17 surfaces versus 9, and why the count is the wrong question

The coverage audit counted **17** distinct ways a job execution starts; the documentation
(`contributor/architecture/surface-boundary.md`) claims **9**. The depth audit deliberately
did not re-enumerate. The synthesis resolved it this way, and this set agrees:

> The surface *count* will keep growing — that is what surfaces do. The fix must make the
> count **irrelevant**, not shrink it.

The evidence for that resolution arrived on its own: 0.3.0 added a tenth
(`app/_workflow_control.py:176`) without either audit's participation, and it was the
*right* thing to add — a single funnel for the three workflow surfaces. A design whose
success metric is "fewer doors" would have scored that release as a regression.

The metric this set uses instead: **what does a tenth door cost?** Today it costs a
resolution decision, a scope decision, a group-option decision, a force decision and an
outcome decision — five chances to differ. After F4 it costs a `RunRequest` and a family
choice.

## C. Where the coverage audit's own matrix is wrong

Its §B feature matrix places D-13's `✗` in the **`Invoke` / `rc.invoke`** column. D-13 is
about `interactivity.job.submit`, which is surface #15 and has no column of its own. This is
not merely a misplaced cell: `rc.invoke` **does** propagate scope
(`_engine/capabilities/invoke.py:398,406` pass `parent_scope=self._workflow_scope`), so the
cell as printed asserts something false about a surface that is fine.

Related, and correct as printed elsewhere: `invoke.py:603` passes `parent_scope=None` for
`parallel` items **deliberately**, commented *"Independent — no shared scope"*. A parallel
batch is not a nested walk, and this set does not change that.

Corrected in [07](07-surface-parity.md).

## D. What each audit uniquely contributed

Worth recording, because a merged document tends to erase which half found what — and both
halves earned their place.

**The coverage audit contributed the things you can only get by running the binary.** The 17
surfaces, each with its boot path. The live reproduction of `--output` being absent from an
app's own entry point (`Error: No such option '--output'`). The observation that
`FUNCTUALIZE_CLI_OUTPUT` appears only in help text and is read by nothing. The STATUS ledger
re-verified item by item, including four that turned out **closed**. And D-11, reproduced
twice, where the misleading error was the part worth recording.

**The depth audit contributed the things you can only get by reasoning about change
pressure.** The 8-site resolution table from serena reference enumeration. The observation
that the engine already resolves by name *on the inside* — which is what makes `run(request)`
a Move Method rather than a new service. The smell mapping with its rejections, and the
rejections are the valuable half: Mediator, Command, Strategy and a new registry each
declined with a reason, in a codebase where "add a registry" is a plausible reflex.

**The synthesis contributed the Open/Closed accounting** — noticing the engine is inverted on
*both* axes, closed where extension was needed and open where modification must be impossible
— and the discipline of naming what it would not do (D5, D6) rather than quietly omitting it.

## E. What this set changes about the evidence base

| Change | Where |
|---|---|
| Every claim re-run at `e57f0c9`; 15/17 hold, 2 drifted, 0 false | [02](02-audit-corrections.md) |
| `execute()` has **13** parameters, not 12 | [04 §A](04-request-and-entry.md) |
| The deposit protocol is **7** attributes, not 3; all 10 writes are in `_cli/main.py`; 6 are read through a silent `getattr` default | [04 §B](04-request-and-entry.md) |
| **3** `Path.cwd()` sites in the kernel, not 1 | [05 §C](05-engine-seal.md) |
| Translation sites **9**, not 7 | [02 §B.1](02-audit-corrections.md) |
| `_app/runcontext.py` does not exist — it is `_engine/capabilities/runcontext.py` | [02 §D](02-audit-corrections.md) |
| The `entry_points()` memoization recommendation is **withdrawn** — it shipped in PR #4 | [12 §D](12-performance.md) |
| `RunStatus` has no `.ok`; it has `.resumable` and `.ran` | [10 §D](10-graph-semantics.md) |
| The D-13 matrix cell is corrected | §C above |
