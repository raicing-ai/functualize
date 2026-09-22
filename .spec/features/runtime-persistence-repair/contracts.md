# FUN-24 — Contracts

**Status:** complete (2026-09-22, Factory Designer). Every claim below was verified by
running the command that would falsify it, against
`/home/ubuntu/orca/workspaces/functualize/rp-24-defect-repair` @ `b82fc78`.

---

## Corrections to this file's own previous draft

Two premises in the pre-loaded scaffold are **false** and are replaced below. Recorded rather
than quietly overwritten, because both were load-bearing.

1. ❌ *"`tests/test_public_api_surface.py` enforces the exported surface"* — applied to
   `functualize.app.utils`, this is wrong.

   ```
   grep -n '^\s*"functualize' tests/test_public_api_surface.py
   -> "functualize", "functualize.app", "functualize.job", "functualize.plugin",
      "functualize.types", "functualize.workflow", "functualize.testing"

   grep -rn 'app.utils' tests/test_public_api_surface.py
   -> (no output)
   ```

   `EXPECTED_EXPORTS` covers seven modules and **`functualize.app.utils` is not one of them**.
   So `FreshStore`, `ScopeStore`, `RunStore` and `ShellHistoryStore` sit in
   `app/utils.py:__all__` (`:266`, `:267`, `:271`, `:272`) with **no test guarding additions or
   removals**. The scaffold's conclusion — "any addition or removal is a deliberate decision,
   not a side effect" — is the intent, not the current state.

2. ❌ *"The design recommends deprecating `ScopeStore` and `RunStore` for one minor version."*
   That recommendation (`05-the-design.md` §6) **cannot be followed in this repository.**
   `.spec/CONSTITUTION.md` → *Forbidden Patterns*: "`DeprecationWarning` / backward-compat
   shims — reason: pre-release, no users to deprecate toward. Remove old code." and
   *Pre-Release Stance*: "No backward compatibility obligation. Breaking changes are free."

   A forbidden pattern is a blocker, not an accepted compromise. It is also **not FUN-24's
   work** — the deprecation belongs to whichever wave narrows `StoreSubstrate`. Reported here,
   not built here.

---

## 1. What this ticket changes at a boundary

### 1.1 `Stored.revision` — a type change on a public-facing port (AC-5)

```python
# src/functualize/_types/protocols.py:765-784   BEFORE
@dataclass(frozen=True, slots=True)
class Stored:
    data: dict[str, Any]
    revision: int          # :784

# AFTER
Revision = NewType("Revision", str)
...
    revision: Revision
```

**This is a type change, not a behaviour change, and the docstring already demanded it.**
`protocols.py:776-781` reads: *"An opaque token identifying this content. Compare it, pass it
to `StoreSubstrate.write`; do not order it or do arithmetic on it."* The annotation permits
exactly what the prose forbids. Recorded as decision **D-15** in
`contributor/architecture/research/runtime-persistence-engine-owned/09-decisions.md:25`
("safe to proceed").

**Every consumer, measured.** AC-5's gate as the issue words it —
`grep -rn '\.revision' src/functualize plugins` *"shows nothing did arithmetic on it"* — is
not runnable as written: the grep returns **9** hits, so it cannot come back empty. The
runnable form is in `spec.md` §AC-5. The nine:

| Site | What it does | Opaque-safe? |
|---|---|---|
| `src/functualize/_primitives/substrate.py:164` | `current.revision != expect` | ✅ compare |
| `plugins/substrates/…-sqlite/src/…/substrate.py:130` | SQL `revision = documents.revision + 1` | ✅ **arithmetic, and legitimate** — this is the minter, inside the substrate that defines the token. The SQL column stays `INTEGER`; only the Python-side token stringifies at `:112`. |
| `plugins/domains/functualize-tasks-local/src/…/_provider.py:119` | returns `stored.revision` | ✅ pass-through — but its annotation at `:106` is `tuple[dict[str, Any], int \| None]` and **must change** |
| `…-sqlite/tests/test_sqlite_substrate.py:123,131,157` | `expect=stored.revision` | ✅ pass-through |
| `…-sqlite/examples/persistent_counter/persistent_counter.py:47` | `stored.revision if stored else None` | ✅ pass-through |
| `…/examples/persistent_counter/test_persistent_counter.py:50` | `second.revision != first.revision` | ✅ compare |
| `…/examples/persistent_counter/test_persistent_counter.py:67` | `expect=stale.revision` | ✅ pass-through |

**This settles an open research question.** `durability-outsourcing/09-verdict.md:113` lists as
unresolved: *"Does anything actually depend on `Stored.revision` being an `int`? Cheap to
settle."* Settled: **one** site depends on int-ness, it is the SQLite substrate's own
`UPDATE`, and it does not need the Python token to be an int. `substrate.py:66` records the
reason the `int` was chosen — *"64 bits because the port types a revision as an int and callers
only ever compare it"* — which is circular and dissolves with the annotation.

**Backward compatibility:** breaks any third-party `StoreSubstrate` implementation that returns
an `int`. Under *Pre-Release Stance* that is free. Falsifier: `uv run mypy src/` plus
`uv run pytest tests/primitives/test_scope_state_store.py`; the two shipped substrates are the
only implementations in-tree (`grep -rn 'Stored(' src plugins`).

### 1.2 `SubstrateInstallError` — a new public name (AC-4)

New in `src/functualize/_types/errors.py`, re-exported from **`functualize.plugin`**, because
the SQLite plugin must raise it and a plugin may not import `_types` (`.spec/CONSTITUTION.md`
→ *Forbidden Patterns*: "`_cli`/user code importing internals").

**This one has a test consequence that will fail loudly, and that is correct.**
`functualize.plugin` **is** in `EXPECTED_EXPORTS` (`tests/test_public_api_surface.py:108`), so
`test_no_unexpected_additions` fails until `EXPECTED_EXPORTS["functualize.plugin"]` gains the
name. It is also the **first** error class in that surface —
`grep -n 'Error' src/functualize/plugin/__init__.py` returns nothing today. So this is a
deliberate widening of the plugin-author API, recorded here with its reason, not a side effect.

Semantics, stated as a contract:

> `SubstrateInstallError` means *"this app cannot have the storage it was configured with."*
> It is the **only** exception type that escapes the `APP_READY` hook loop. Every other
> exception from an `APP_READY` hook remains logged and swallowed
> (`_app/boot.py:881-882`, `:471-473`) — a telemetry plugin that throws must not kill boot.

### 1.3 What does **not** change at a boundary

- **`StoreSubstrate`'s method set is untouched.** Six members, unchanged.
- **`app.install_substrate` keeps its signature, its `APP_READY` timing, and its late-install
  refusal** (`app/core.py:353`, `_app/impl.py:1584`). The three documents that teach the
  pattern stay correct: `docs/guides/workflows.md:391`,
  `docs/examples/plugins/custom-state-backend.md:61`,
  `examples/plugins/custom_state_backend/README.md:65`. *This is the reason §6 of `plan.md`
  chose the error-exemption over a new boot step.*
- **`ScopeStore`'s public method set is untouched.** `_fenced_state` is private; the five
  `*_state` methods keep their signatures, so the single production caller
  (`_engine/capabilities/state.py:106,123,127,130,133,147`) needs no edit. What changes is that
  they can now raise `StaleGenerationError` — see §3.
- **`functualize.app.utils.__all__` is untouched.** No store is added, removed or renamed.
- **`lease.py` exports nothing new.** `check_generation` keeps its signature.

---

## 2. Import-linter contracts

Seven contracts in `pyproject.toml` decide whether the AFTER shape is legal. Baseline measured
at authoring time, in this worktree:

```
uv run lint-imports
Analyzed 363 files, 1007 dependencies.
Peer layers are independent                               KEPT
Events depends on foundation only                         KEPT
Primitives import nothing internal                        KEPT
Types import nothing internal                             KEPT
Internal never imports public                             KEPT
_cli uses public API only                                 KEPT
Delivery adapters go through the request, not the engine   KEPT
Contracts: 7 kept, 0 broken.
```

**The AFTER adds no layer and no new edge**, so all seven must still pass unchanged. The three
that could plausibly break, and why they do not:

| Contract | Risk | Why it holds |
|---|---|---|
| `Types import nothing internal` | `Revision`/`SubstrateInstallError` land in `_types/` | `NewType` is `typing`; the error subclasses `Exception`. Stdlib only. |
| `_cli uses public API only` | `shell_mode.py` must reach the installed substrate | It reads `app.substrate` — a **public** property on `functualize.app.core` (`:333-335`) — and imports `ShellHistoryStore` from `functualize.app.utils`, which it already does at `:305`. No `_`-prefixed import added. |
| `Primitives import nothing internal` | `_fenced_state` needs `read_lease` + `check_generation` | Both are already in `_primitives/lease.py` and already imported by `scope_store.py`. No new import at all. |

**If a contract needs editing, stop and raise it** — `.spec/CONSTITUTION.md` and the
`functualize-repo-ops` skill both forbid editing them without raising first. Nothing in this
plan requires it.

Adjacent, found while checking: `contributor/architecture/layer-contract-blind-spot.md:248-255`
records that `src/functualize/ui/` is a **seventh** public package no contract names, so
`_cli → functualize.ui` passes `_cli uses public API only` while the identical import from
`functualize._types` would fail. Not touched by FUN-24 and not this ticket's to settle;
flagged because AC-6's fix is a `_cli` change and a reader may wonder whether it relies on
that hole. It does not — `functualize.app` is a properly declared public package.

---

## 3. Backward compatibility

"Nothing breaks" is not claimed. Here is what breaks, for whom, and the command that falsifies
each line.

| Change | Breaks | Falsifier |
|---|---|---|
| `Stored.revision: int → Revision` | any out-of-tree `StoreSubstrate` implementation, and any caller that stored a revision in an int-typed field | `uv run mypy src/`; `uv run pytest plugins/substrates/functualize-substrate-sqlite/tests/` |
| `SubstrateInstallError` added to `functualize.plugin.__all__` | `tests/test_public_api_surface.py::test_no_unexpected_additions` until `EXPECTED_EXPORTS` is updated | `uv run pytest tests/test_public_api_surface.py` |
| **`rc.state` writes can now raise `StaleGenerationError`** | **job authors.** This is the largest behavioural break in the ticket and it is the point of AC-2: a job whose scope was reclaimed mid-run now gets an exception from `rc.state.set()` where it previously got a silent successful overwrite. Nothing in `_engine/capabilities/state.py` catches it today. | `grep -rn 'StaleGenerationError' src/functualize/_engine/` → sites that would need to handle it; `uv run pytest tests/primitives/test_scope_state_store.py tests/test_scope_store.py` |
| `scopes.json` writes can now fail after exhausting CAS retries | a caller under extreme contention; previously the last writer silently won | the AC-1 two-process gate |
| `"state": {}` removed from `_blank_scope()` | nothing in-tree reads it — `grep -rn 'get("state"' src/functualize plugins` returns **one** hit, `scope_state_store.py:125`, which is a *different document* (`scope-state/<id>`, not `scopes.json`). Records written before this change keep an inert extra key; `normalize_scopes` does not reject unknown keys. | `uv run pytest tests/test_scope_store.py` |
| Nothing in `functualize.app.utils` | — | — |

**The `StaleGenerationError`-from-`rc.state` break is a spec question, not just a contract
note.** AC-2 says a stale runner's write must be *refused*; it does not say how a job learns
that. Two readings, and they produce different code:

- *refused loudly* — the exception reaches the job body, which is honest and can break a job
  that was previously (wrongly) succeeding;
- *refused and translated* — `ScopeBackedStateStore.set` (`_engine/capabilities/state.py:123`)
  catches it and re-raises as the scope-closed error it already knows how to raise
  (`InvalidStateTransitionError`, `state.py:94-103`), which is the vocabulary a job author has
  already met.

**Recommendation: refused loudly** for this wave — AC-2's gate asserts the refusal, and adding
a translation layer is a design decision that FUN-17's transaction boundary will want to own.
Raised in `plan.md` → *Surviving smells* as a maintainer question rather than decided here.
