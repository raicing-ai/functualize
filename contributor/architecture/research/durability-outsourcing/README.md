# Outsourcing durability — Restate, DBOS, Cloudflare, S3

**Status: research. Nothing here is decided, scheduled, or implemented.** No source file,
Jira issue or Confluence page was changed to produce it.

## The question

> Research Restate, DBOS, Cloudflare D1, Cloudflare "D2", and AWS S3 transactions — with
> emphasis on using them as the backend store, or (for Restate and DBOS) letting them
> provide durability. How should we design this? What are the abstractions and at what
> level? Should durability guarantee and persistence be at different abstraction levels?
> Would outsourcing durability be cheap? Does it conflict with our execution engine?

## The argument, in six sentences

1. "Durability" names three different things — bytes surviving a power cut, a transition
   committing as one fenced unit, and a computation surviving the death of its process —
   and they belong at three different levels.
2. Restate and DBOS operate at the third level, and **Functualize already implements the
   third level**: replay, memoised steps, pinned branches, durable gates and a
   code-version fence, all shipped, in `src/functualize/_engine/`.
3. Our four actual defects are all at the **second** level, in fencing and cross-document
   atomicity — which neither Restate nor DBOS would fix, because neither is a document
   store and both leave `fresh`, `scopes`, `runs` and `shell-history` exactly where they
   are.
4. There is no "Cloudflare D2"; the plausible intents are Durable Objects (unreachable
   without shipping a JavaScript Worker) and R2 (blocked on an undocumented atomicity
   guarantee).
5. **Cloudflare D1 is the best technical fit of anything evaluated** — real transactions
   via `batch`, reachable from plain Python, and it needs no change to our port — while S3
   is viable but cannot fix the cross-document defect, because AWS states plainly that
   there is no way to make atomic updates across keys.
6. So: durability guarantees and persistence *should* sit at different levels, the
   guarantee should be **a declared, tested field** rather than a docstring, and the
   correct move is to repair level 2 on the substrates we already have — after which a D1
   plugin is ~400 lines, and adopting a level-3 engine is still a 3,716-line replacement.

## Reading order

| # | File | Read it for |
|---|---|---|
| 1 | [`01-the-question.md`](01-the-question.md) | The three levels of "durability", and the constraints any answer must survive. **Start here.** |
| 2 | [`02-what-we-already-have.md`](02-what-we-already-have.md) | The durable-execution engine that already exists here, with line numbers. Without this, `03`/`04` look like free wins. |
| 3 | [`03-restate.md`](03-restate.md) | Restate: what it is, what it would give us, and the five reasons it cannot be adopted |
| 4 | [`04-dbos.md`](04-dbos.md) | DBOS: the serious candidate, and the one idea worth stealing from it |
| 5 | [`05-cloudflare.md`](05-cloudflare.md) | D1, Durable Objects, R2, Workflows — and what "D2" is |
| 6 | [`06-s3.md`](06-s3.md) | S3 conditional writes as a real CAS primitive, and the port bug they expose |
| 7 | [`07-the-design.md`](07-the-design.md) | **The answer to the design question.** Three levels, the profile, the buffering transaction |
| 8 | [`08-is-it-cheap.md`](08-is-it-cheap.md) | **The answer to the cost question.** 352 lines versus 3,716, measured |
| 9 | [`09-verdict.md`](09-verdict.md) | What to do, what would change it, what is still unknown |

New to the codebase? Read
[`../runtime-persistence-engine-owned/01-orientation.md`](../runtime-persistence-engine-owned/01-orientation.md)
first — it assumes no prior context at all.

## Relationship to the other research in this directory

| Folder | What it covers |
|---|---|
| [`../runtime-persistence/`](../runtime-persistence/) | The canonical repo proposal — "Design 1", the provider family |
| [`../runtime-persistence-engine-owned/`](../runtime-persistence-engine-owned/) | The engine-owned design — "Design 3", plus the four defects and the change inventory |
| **this folder** | Whether any of it should be outsourced, and to whom |

This folder **depends on** the defect catalogue in
[`../runtime-persistence-engine-owned/03-the-four-defects.md`](../runtime-persistence-engine-owned/03-the-four-defects.md)
and the `StoreProfile` / `RuntimeStore` ports in
[`../runtime-persistence-engine-owned/05-the-design.md`](../runtime-persistence-engine-owned/05-the-design.md).
It extends them; it does not contradict them. Where the research changed a decision — the
transaction port must buffer rather than stream, because D1 has no `BEGIN` — it is called
out explicitly in `07-the-design.md` §4.

## How the external facts were gathered

Four parallel research agents, one per system, each instructed to cite a URL for every
claim and to write "NOT FOUND" rather than guess. The unresolved items are carried forward
verbatim into each document's closing section and collected in `09-verdict.md` §4 — most
importantly the R2 atomicity question, which is the single fact that would unblock or
block a whole candidate.

Repository claims are cited by `path:line` and were read from the working tree at the time
of writing. Counts came from running the command that would falsify them; the commands are
shown inline so you can re-run them.
