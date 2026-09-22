# FUN-24 — Repair the four runtime persistence defects

**Status:** refined against the code (2026-09-22, Factory Designer). One acceptance
criterion (AC-5) was **not runnable as written** and has been replaced with a runnable form;
the intent is unchanged. Everything else stands as the issue states it.

## Goal

Make the existing document stores safe before anything migrates them.

## Why

A corrupt source stays corrupt. FUN-19 migrates the documents these defects write; repairing
after the migration means migrating known-bad records and paying twice. All four defects have
runnable reproductions that were executed, not reasoned about.

## Acceptance criteria

These are **gates run at authoring time**, with each task's file scope equal to the gate's hit
set. Each one below was executed in
`/home/ubuntu/orca/workspaces/functualize/rp-24-defect-repair` @ `b82fc78`; the recorded
output is what it returned **before** any repair, so each gate is known to be red today.

### AC-1 — a two-process claim race yields two distinct generations

Assert it with locking **disabled** — a test that runs with locking working cannot tell the two
designs apart. Reproduction: `03-the-four-defects.md` → B4, `defect_b4.py`.

Today: `distinct generations: 1 of 2`. Required: `2 of 2`.

The no-op-lock harness already exists and must be reused rather than rewritten:
`tests/primitives/test_lease_fencing.py:194-220` (`_no_locking`, which patches
`JsonFileSubstrate.lock` — one place since `store-substrate`/T2, so it disables all locking).
It is **single-process**; AC-1 needs two real OS processes, because a fork-safe barrier is what
makes the claim race real (`contributor/reference/pitfalls.md` §22: *"Test across separate
processes; one process hides this class of bug completely."*).

### AC-2 — a stale runner's write to `scope-state/<id>` is refused, not accepted

Reproduction: `03-the-four-defects.md` → B1, `defect_b1.py`.

Today:
```
record write  : REFUSED    (StaleGenerationError)
state write   : ACCEPTED
value B now reads back: 'OVERWRITTEN-BY-STALE-A'
```
Required: both lines `REFUSED`, and B reads back `'written-by-A-while-holder'`.

**How a job learns it was refused is an open decision** — see `contracts.md` §3. This wave
raises `StaleGenerationError` to the job body.

### AC-3 — every fenced write passes `expect=`

The advisory lock becomes defence in depth, not the mechanism.

```
grep -rn 'expect=' src/functualize --include='*.py' | grep -v 'def write'
-> (no output)              # today: zero
```
Required after: every `substrate.write` inside `scope_store._mutate`, `scope_store.batch`,
`scope_state_store._mutate` and `scope_state_store.batch` appears in that output.

**Scope note.** AC-3 as worded is about `expect=`, and it is achievable in this wave. B3's
*headline* — "there is no cross-document atomicity" — is **not**, and must not be attempted
here: no `lock(*keys)` call site takes two keys today (13 production call sites, all arity 1),
and giving `scopes.json` and `scope-state/<id>` one commit point is FUN-17's
`RuntimeTransaction`. Report, do not build.

**Reuse, not invention.** `expect=` already has one working production caller with a bounded
retry loop: `plugins/domains/functualize-tasks-local/src/functualize_tasks_local/_provider.py:139-158`.
Copy its shape, and carry its recorded limitation: `write(..., expect=None)` on a
never-written document is *unconditional*, so the very first write to a document cannot be
compare-and-swapped. For `scopes.json` this is mitigated because `ensure_scope` creates the
document before any claim (`_engine/frontier.py:177` → `:183`), but the mitigation must be
stated in the code, not assumed.

### AC-4 — a substrate install failure fails boot

Reproduction: `03-the-four-defects.md` → B2, `defect_b2.py`.

Today: `BOOT SUCCEEDED despite the substrate plugin raising.` / `engine is running on:
JsonFileSubstrate`. Required: `BOOT FAILED as intended: SubstrateInstallError: …`.

Both boot paths, not one: `_app/boot.py:879-882` (`boot_standard`) and `:467-473`
(`boot_static`). **And a second assertion in the same gate**: an unrelated `APP_READY` hook
that raises must still be logged and swallowed — otherwise the fix has changed what an
`APP_READY` hook means, which it must not.

### AC-5 — `Stored.revision` is opaque *(replaced: the issue's form is not runnable)*

The issue words this gate as:

> `grep -rn '\.revision' src/functualize plugins` shows nothing did arithmetic on it.

**That command cannot come back empty.** Measured today it returns **9** hits, of which 8 are
compares or pass-throughs and exactly 1 is arithmetic — and that one is legitimate. So the gate
as written is unsatisfiable while the intent is entirely satisfiable. The runnable form, in two
parts:

```
# (a) no arithmetic on a revision outside the substrate that mints it.
grep -rn '\.revision' src/functualize plugins --include='*.py' \
  | grep -E '\.revision\s*[-+*/]|[-+*/]\s*[A-Za-z_.]*\.revision'
-> today: one hit, and it must remain the only one:
   plugins/substrates/functualize-substrate-sqlite/src/.../substrate.py:130
   "revision = documents.revision + 1"      # SQL, inside the minter

# (b) the type forbids it, which the annotation does not today.
grep -n 'revision:' src/functualize/_types/protocols.py
-> today:  784:    revision: int
   after:  784:    revision: Revision        # NewType, so arithmetic is a mypy error
uv run mypy src/    -> must stay clean
```

Part (b) is the real gate: `protocols.py:776-781` has always said *"do not order it or do
arithmetic on it"* in prose while `:784` permitted both. Recorded as decision **D-15**
(`09-decisions.md:25`, "safe to proceed"). Full consumer inventory: `contracts.md` §1.1.

### AC-6 — a TUI write and a CLI read agree

The split brain at `_cli/tui/shell_mode.py:312` is closed.

Today, verified by reading both halves:

| | Substrate it uses |
|---|---|
| **writer** — `shell_mode.py:312` | `ShellHistoryStore.for_project(Path.cwd())` — always `JsonFileSubstrate` |
| **reader** — `_cli/builtins.py:959-961`, `:1062-1064`, `:2092-2094` | `ShellHistoryStore(substrate) if substrate is not None else …for_project(…)`, where `substrate = _project_substrate(ctx)` → `app.substrate` (`builtins.py:661-691`) |

So with a substrate plugin installed the TUI writes a file and the CLI reads a database. The
`app` handle the writer needs is **already in scope one frame up**:
`execute_shell_handoff(app, command)` at `:217` receives it and `:243` drops it.

Gate: with `SQLiteSubstratePlugin` installed, a `!` command recorded through the TUI handoff
path is visible to `func builtin history`. Assert through both surfaces, not by comparing paths
— `tests/primitives/test_one_substrate_choice.py` already asserts "one answer" for the
*filesystem walk* and passes today **while this bug exists**, because `for_project` does route
through the single `substrate_for_project` decision. It is the *installed* substrate that is
bypassed. A path-comparison test would pass just as happily.

## Out of scope

Anything belonging to another wave. Found while verifying, **reported not built**:

1. **Cross-document atomicity** (B3's headline) — FUN-17 `RuntimeTransaction`. See AC-3.
2. **`StoreSubstrate` narrowed and made public; `Stored` exported from `functualize.plugin`** —
   `05-the-design.md` §6. `StoreSubstrate` is public **nowhere** today
   (`grep -rn 'StoreSubstrate' src/functualize/app/utils.py src/functualize/plugin/*.py
   src/functualize/types/*.py` → no output) while `docs/guides/workflows.md:385-386` tells
   plugin authors to implement `functualize._types.protocols.StoreSubstrate`, a private path.
   Real defect, later wave.
3. **Deprecating `ScopeStore` / `RunStore`** — `05-the-design.md` §6. **Cannot be done in this
   repository at all**: `.spec/CONSTITUTION.md` forbids `DeprecationWarning`/compat shims under
   *Pre-Release Stance*. Reported as a contradiction in the design document, not a task.
4. **`StoreSubstrate`'s docstring contradicts itself** — `protocols.py:790` says *"Three
   members, deliberately"*, `:812` says *"Six members, not three"*. A one-line docs fix, and it
   is inside AC-5's file, so task 1.2 may correct it; it is not an acceptance criterion.
5. **The codemaps never absorbed `store-substrate`** — `contributor/architecture/codemaps/`
   mentions none of `ScopeStore`, `ScopeStateStore` or `StoreSubstrate`. `/sync-docs` work.
6. **`src/functualize/ui/` is an unnamed seventh public package** —
   `contributor/architecture/layer-contract-blind-spot.md:248-255`. Needs its own decision.
7. **Research line-citation drift** — `05-the-design.md` §4 cites `boot.py:614/718/754/841`;
   the real lines are `:619/:742/:780/:868`. `06-s3.md:53` and `07-the-design.md:215` cite
   `protocols.py:755-756` for `Stored.revision`; it is at `:765`/`:784`. The `03-the-four-defects.md`
   citations are **exact** — the drift is confined to the design and durability documents.

## Evidence baseline

`origin/master` @ `8c06198`. **`git diff --stat 8c06198..HEAD -- src plugins` is empty**, so
every `src/` and `plugins/` citation in these artifacts is identical on the branch and on
master. Re-verification log, run at authoring time:

| Research claim | Verdict |
|---|---|
| `grep -c generation scope_state_store.py` → 0 | ✅ **0** |
| `ScopeStateStore._mutate` at `scope_state_store.py:144-152` | ✅ exact |
| `ScopeStore.set_state` at `scope_store.py:520-525` | ✅ `def` at `:520` |
| guarded write at `scope_store.py:250-266` | ✅ `_guarded` `:249`, write `:266` |
| `claim_scope` skips the fence, `scope_store.py:715-750` | ✅ `def` `:715`, `self._mutate(_apply)` `:749-750`, no `scope_id` |
| dead `"state": {}` at `scope_store.py:102` | ✅ exact, and dead: the only `get("state"` in `src`+`plugins` is `scope_state_store.py:125`, a different document |
| `check_generation` owner-blind, `lease.py:282-305` | ✅ `def` `:282`, the compare at `:302`; the function runs to `:308`, so the cited range stops three lines early |
| APP_READY swallow `boot.py:879-882` | ✅ exact |
| APP_READY swallow `boot.py:467-473` (static) | ✅ exact |
| plugin docstring / install, `_plugin.py:86-90` | ⚠ the **install** is at `:86-87`; the docstring the research quotes starts at `:71`. Both real, the label is off |
| engine resolves lazily via `substrate_override` | ✅ `_engine/executor.py:1526` |
| split brain at `shell_mode.py:312` | ✅ exact |
| `Stored.revision` at `protocols.py:930` *(plan.md)* / `:755-756` *(research)* | ❌ **both wrong** — `class Stored` `:765`, `revision: int` `:784` |
| 7 import-linter contracts in `pyproject.toml` | ✅ 7, all KEPT |
| `StoreSubstrate` public nowhere; `docs/guides/workflows.md:386` names a private path | ✅ both |
| **"All 14 `lock()` call sites pass one key"** | ⚠ **13**, not 14, in production. *All arity 1* ✅. The research's own command (`rg -n '\.lock\(' --include='*.py'`) is **not runnable** — `--include` is grep syntax; `rg` needs `-g`/`--glob` |
| **"`write(expect=)` … Zero production callers"** | ⚠ **true of `src/functualize/` (0), false of the repository**: `plugins/domains/functualize-tasks-local/.../_provider.py:153` is one |
| `scope_state_store.py` 235 / `scope_store.py` 923 / `lease.py` 305 / `shell_mode.py` 331 | ✅ all four exact |
| `boot.py` 2016 *(plan.md)* | ❌ **2079** |
| `protocols.py` 930 *(plan.md)* | ❌ **958** |
| `tests/test_public_api_surface.py` enforces `app.utils`'s surface *(contracts.md)* | ❌ **it does not** — `EXPECTED_EXPORTS` has 7 modules and `functualize.app.utils` is absent |

Targeted baseline green on `b82fc78` (207 passed, 3 skipped), measured by Mika before this run
and not re-run here.
