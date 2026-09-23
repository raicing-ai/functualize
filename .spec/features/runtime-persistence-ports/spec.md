# FUN-17 — Ports, StoreProfile, recorders, and the construction move

**Status:** refined 2026-09-23 against `origin/master` @ `1f3b760`, after rebase.
Supersedes the pre-loaded scaffold. Every count and negative below was produced by
running the command that would falsify it; the commands are quoted inline.

## Goal

Define the persistence ports as data and protocols in `_types`, adapt today's document
stores behind them, and move engine construction to `_app` **after** config resolves so
the engine receives its storage instead of discovering it.

## Why

`JobExecutionEngine` does not receive its storage. It reaches for it, lazily, on first
access:

```python
# src/functualize/_engine/executor.py:1509-1528
@property
def substrate(self) -> StoreSubstrate:
    if self._substrate is not None:
        return self._substrate
    from functualize._primitives.substrate import substrate_for_project
    chosen = getattr(self.host, "substrate_override", None)
    self._substrate = chosen or substrate_for_project(self.fresh_root)
    return self._substrate
```

Two facts make this the wave everything else rests on. The engine is built at
`_app/boot.py:403` (static path) and `:622` (standard path) — both **before** config
resolves — so late discovery is not a style choice, it is the only thing that works
today. And the host attribute it reaches for is declared on a Protocol this repository
owns (`_types/protocols.py:470`), yet is read through `getattr(..., None)`: a defensive
lookup against a type we control, which is the exact shape that already cost this repo a
silent bug (`app/_workflow_control.py:420-424` records it).

Moving the construction deletes the coupling rather than arguing about it.

## Premises, verified

Each line is a claim this spec rests on, with the command that would falsify it and the
value it returned on `1f3b760` + this branch.

| Claim | Command | Returned |
|---|---|---|
| `StoreProfile` does not exist in shipped code | `rg -c 'StoreProfile' -g '*.py' src/ plugins/` | `0` |
| `Claimed \| Conflict` does not exist anywhere in `src/` | `rg -c 'Claimed \| Conflict' -g '*.py' src/` | `0` |
| The engine is constructed with no storage argument, twice | `rg -c 'build_engine\(app\)$' src/functualize/_app/boot.py` | `2` |
| The engine still reaches for its own substrate | `rg -c 'substrate_for_project' src/functualize/_engine/executor.py` | `3` |
| …and still reads the host slot defensively | `rg -c 'substrate_override' src/functualize/_engine/executor.py` | `2` |
| Seven import-linter contracts exist | `rg -c '^\[\[tool.importlinter.contracts\]\]' pyproject.toml` | `7` |
| Losing a claim is an exception today, not an outcome | `rg -c 'LeaseHeldError' src/functualize/_engine/frontier.py` | `1` |
| …and one call site swallows it whole | `rg -c 'except Exception:' src/functualize/app/_workflow_control.py` | `1` |

## What the rebase changed about the criteria

The branch was two commits behind. Re-read against the repaired code, **one of the two
things the criteria were said to inherit is there and one is not**:

- **Delivered by FUN-24 (#46).** The opaque revision token. `Revision = NewType("Revision",
  str)` (`_types/protocols.py:764`), minted as a content hash by
  `_primitives/substrate.py:60-68`. Criteria that assume a comparable, non-integer
  revision can be written against real code.
- **NOT delivered by FUN-24.** `Claimed | Conflict`. `rg -c 'Claimed \| Conflict' -g '*.py'
  src/` returns `0`. `_primitives/lease.py:226` still raises `LeaseHeldError`, and
  `app/_workflow_control.py:439` still catches it with a bare `except Exception`.
  **Criterion 6 is FUN-17's own work in full**, not a re-statement of a repair that
  already landed.

Criterion 3's ten field *values* are settled, and not by this ticket: FUN-25's
`contributor/reference/substrate-capability-matrix.md` measured all ten across eight
backends. The ten names, in the order the matrix uses, are
`cross_aggregate_atomicity`, `fencing`, `multi_process`, `multi_machine`,
`durable_outbox`, `versioned_migrations`, `interactive_transaction`, `remote`,
`max_document_bytes`, `offline_capable`. Nothing here re-derives them from vendor
documentation; where a value is asserted, the matrix row is the citation.

## Acceptance criteria

Behavioural. Each is carried by named tasks whose gates are in `tasks.md`.

1. **The transaction accumulates and commits once on exit.** A writer call appends a
   command and issues nothing. `__exit__` applies the whole batch as one unit on a clean
   exit and discards it otherwise. The shape must be implementable over a backend with no
   `BEGIN` — Cloudflare D1, whose `interactive_transaction` the matrix measures as `no ·
   real`. *(T6)*
2. **A store declaring `cross_aggregate_atomicity=False` refuses a spanning transaction.**
   It raises on commit, names both aggregates, and applies **neither**. A partial apply is
   defect B3 under a new name. *(T8)*
3. **`StoreProfile` carries all ten fields, and boot refuses rather than degrades.** An
   unmet required capability raises at selection time, naming the store, the field and the
   config key — it never falls back to a weaker store. *(T1, T13)*
4. **The engine receives its store and never discovers one.** The lazy property and the
   `getattr` host read are gone; a tripwire test proves construction without a store is
   impossible rather than merely unused. *(T11, T12)*
5. **The seven import-linter contracts pass unchanged, and no new layer appears.** Ports
   in `_types`, recorders in `_engine`, wiring in `_app`. Note that `lint-imports` alone is
   not sufficient evidence: `exclude_type_checking_imports = true` means a deferred
   `_types → _app` import reports "7 kept, 0 broken"
   (`contributor/architecture/codemaps/dependencies.md:37`). The criterion is therefore
   carried by `lint-imports` **and** an import-line test, as
   `tests/types/test_plugin_host_port.py` already does for that blind spot. *(T15)*
6. **`claim()` returns `Claimed | Conflict`.** Losing a claim is a value the caller
   branches on. The outcome must be *reached* by production code, not merely declared:
   `_engine/frontier.py` and `app/_workflow_control.py` are the two call sites, and the
   reachability rule makes converting them part of this criterion rather than a later
   ticket's. *(T4, T14)*

## Out of scope

- `SqliteRuntimeStore`, normalized tables and migrations — FUN-19/FUN-18.
- Any network SQL provider — D-12 forbids one until FUN-22 names a database.
- The public-API decision on `ScopeStore` / `RunStore` (D-9). This wave exports nothing
  new from `functualize.plugin`; see `contracts.md` for why that is deliberate.
- Measuring any backend. The matrix is the authority and is not re-run (FUN-25's record
  is not re-measured to look current).

This initiative fails most plausibly by one ticket absorbing the next one's work. If a
task appears to need a deliverable from the list above, stop and say so.

## Evidence baseline

`origin/master` @ `1f3b760`, branch `feat/runtime-persistence-ports` rebased onto it.
Every `path:line` citation in this file was checked against the working tree **after** the
rebase. Re-check before relying on one — master moves.
