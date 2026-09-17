# Plan: local-vault-access

Inputs: `spec.md` (decisions D1–D8, §17 constraints), `contracts.md`,
`research.md`. `.spec/STATE.md` absent — no work in flight.

## 0. Retrieval performed

| Pass | Tool | Notes |
|---|---|---|
| Architecture — prose | zvec-grep `/usr/local/bin/zg` | Index absent; built for this worktree (1774 files, 36033 entities, 2m09s). `zg status` confirms root `…/feat-local-vault-access` — not the parent checkout. |
| Architecture — surface | serena, activated by absolute path | `get_symbols_overview` on the vault modules; real surface, not remembered. |
| Architecture — direction | graphify | `graph.json` built at `78d9ff4`, **12 commits behind HEAD** — used for shape only. `get_neighbors` errored (`'label'`) on a file node, so direction was taken from the import-linter contracts and `dependencies.md` instead. |
| Blast radius | serena `find_referencing_symbols` | `SecretsVault.put`, `VaultEntry`; grep for `vault_path_for_project` / `vault_location` callers. Hit sets are the task file lists in `tasks.md`. |

**Skills consulted:** `python-design-patterns` (KISS, SRP, composition,
rule of three, "delete before abstracting") and `design-patterns-refactoring`
(Refactoring.Guru smell catalogue — ch32 bloaters, ch34 change preventers,
ch36 couplers — used for the smell names below).

**Codemaps read:** `overview.md`, `modules.md`, `dependencies.md`,
`data-flow.md`, `entry-points.md`. One contradiction found and resolved in §4.

### A finding the prose pass produced

`docs/guides/configuration.md:566` states as a user-facing promise:

> With no key at all the vault does not open. There is **no plaintext
> fallback**: resolution falls through to the next source, and says so.

D2 (presence-based refusal) contradicts that sentence directly. The doc is
therefore a required edit, not an optional one, and it is listed in §6.

## 1. BEFORE

```
  PUBLIC (user-importable)                INTERNAL (framework-only)
  ────────────────────────                ─────────────────────────

                                          _cli/  (delivery; public API only)
                                          ┌──────────────────────────────┐
                                          │ builtins.py          3182 LOC│
                                          │  vault_app  L2648-2891       │
                                          │   keygen list status         │
                                          │   clear sync                 │
                                          │ plugin_cmd.py         598 LOC│  ← the
                                          │ self_cmd.py           833 LOC│    precedent
                                          └───────────┬──────────────────┘
                                                      │ may import ONLY public
            ┌─────────────────────────────────────────┘
            ▼
  app/utils.py   2380 LOC, 130 exports
  ┌────────────────────────────────────┐
  │ vault_sync  vault_status           │   ← 7 vault names among 130
  │ vault_entries  vault_clear         │     unrelated ones
  │ vault_location  vault_duration     │
  │ generate_vault_key                 │
  └───────────┬────────────────────────┘
              │  public → internal (allowed)
              ▼
  _config/   (peer layer)                      _app/  (composition root)
  ┌───────────────────────────┐                ┌──────────────────────────┐
  │ vault.py            500   │                │ boot.py            1962  │
  │   SecretsVault            │◄───────────────│  build_remote_source()   │
  │   _SCHEMA  (NOT NULL ×3)  │                │    → None unless         │
  │   vault_path_for_project  │                │      remote=True         │
  │   ── imports cryptography │                │  build_resolution_chain( │
  │      AT MODULE LEVEL      │                │      …, remote_source=)  │
  │ vault_keys.py       232   │                │                          │
  │   resolve_vault_key       │                │ impl.py                  │
  │   EnvKeyProvider   (user- │                │  _build_resolution_chain │
  │     scoped)               │                │    ✗ omits remote_source │
  │   KeychainKeyProvider      │               │      ── DEFECT, §3.6     │
  │     (project-scoped)  ◄── disagree          └──────────────────────────┘
  │ vault_source.py     307   │
  │   VaultSource  usable =   │                _types/protocols.py
  │     key AND file exists   │                  VaultKeyProvider (Protocol)
  │     → no key = inert      │                foundation; imported by all
  └───────────────────────────┘

  Boundary crossings, all legal today:
    _cli ──► app/           (contract "_cli uses public API only")
    app/ ──► _config/       (public → internal: unconstrained)
    _app ──► _config/       (composition root; the only peer-crosser)
    _config ─X─ _discovery  (contract "Peer layers are independent")
```

### Smells the BEFORE already carries

Catalogue names, with where each lives:

1. **Divergent change** (ch34) — `app/utils.py`, 2380 LOC / 130 exports. Vault
   orchestration sits beside job-schema helpers, group tries, packaging and run
   views; they change for unrelated reasons. `research.md` names this too.
   *Standard routing: Extract Class.*
2. **Divergent change** (ch34) — `_cli/builtins.py`, 3182 LOC. Every builtin
   group is inline except the three already extracted. *Routing: Extract Class
   — and the precedent is already in the tree.*
3. **Shotgun surgery** (ch34) — chain composition exists at two call sites
   (`boot.py:798`, `impl.py:1318`) kept equivalent by a *comment* asking for
   "argument-for-argument equivalence". They have already drifted: one passes
   `remote_source`, the other does not, so public `FunctualizeApp.refresh()`
   silently de-wires the vault today.
4. **Primitive obsession** (ch32) — an entry's provenance is smeared across
   three `NOT NULL` strings (`annotation`, `provider`, `synced_at`) with no
   `origin` concept. "Is this entry direct?" is *not representable*, which is
   why D1 is a schema change rather than a query.
5. **Divergent scope in one seam** — `EnvKeyProvider` is user-scoped and
   documents why; `KeychainKeyProvider` is project-scoped. Not a catalogue
   smell so much as an inconsistent invariant, and the one D6 closes.

**Explicitly NOT a smell:** `vault_location`, `vault_duration` and
`generate_vault_key` in `app/utils.py` are one-line forwards, which reads as
**middle man** (ch36) whose routing is *remove the middle man*. That would be
wrong here. The import-linter contract `_cli uses public API only` forbids
`_cli` importing `_config`, so the forward **is** the mechanism — a Facade
(ch14), not a middle man. Recorded so a later reader does not "simplify" it.

## 2. AFTER

```
  PUBLIC                                   INTERNAL
  ──────                                   ────────

                                           _cli/
                                           ┌──────────────────────────────┐
                                           │ builtins.py     ~2930 LOC    │
                                           │   (vault group REMOVED,      │
                                           │    2-line mount remains)     │
                                           │ vault_cmd.py    NEW  ~600    │
                                           │   init put inspect remove    │
                                           │   + keygen list status       │
                                           │     clear sync  (MOVED)      │
                                           └───────────┬──────────────────┘
                                                       │ public API only
            ┌──────────────────────────────────────────┘
            ▼
  app/vault.py   NEW  ~350 LOC          app/utils.py  (unchanged, 7 vault
  ┌──────────────────────────────┐       forwards stay — spec §14.3)
  │ vault_init    vault_put      │
  │ vault_inspect vault_remove   │      ◄── the ONLY place the job schema
  │ resolve_canonical_path()     │          and the store meet (spec §17.1)
  │ Vault*Report dataclasses     │
  └──────┬────────────────┬──────┘
         │                │ reads schema THROUGH the app object
         │                └─────────► app.execution_engine.materialize_job
         │                            (no _engine/_discovery import)
         ▼
  _config/                                    _app/
  ┌────────────────────────────────┐          ┌────────────────────────────┐
  │ vault_paths.py   NEW  ~60 LOC  │◄─────────│ boot.py                    │
  │   project_root_for()   (D4)    │  stat    │  build_vault_source(app)   │
  │   vault_path_for_project()     │  only    │   returns a source when    │
  │   ZERO crypto imports  ◄────── the cold-   │     remote=True  (as now)  │
  │                          boot gate        │   OR vault file exists     │
  │ vault.py            ~650 LOC   │          │     (NEW, dormant)         │
  │   _SCHEMA +origin +created_at  │          │  build_resolution_chain()  │
  │          +updated_at           │          │                            │
  │          +key_provider         │          │ impl.py                    │
  │          nullable ×3      (D1) │          │  _build_resolution_chain   │
  │   _upgrade()  user_version (D1)│          │    ✓ passes the source     │
  │   key check value         (D7) │          │      ── DEFECT FIXED       │
  │   put(origin=, replace=)       │          └────────────────────────────┘
  │   delete(key)  — needs NO key  │
  │   re-exports vault_path_for_…  │
  │ vault_keys.py       ~300 LOC   │          _types/protocols.py
  │   KeychainKeyProvider          │          ┌────────────────────────────┐
  │     user-scoped, fixed    (D6) │          │ VaultKeyProvider  unchanged│
  │     account                    │          │ VaultKeyInitializer   NEW  │
  │     + initialize_key()         │─────────►│   (Protocol, @runtime_     │
  │     keyring = optional    (D5) │ satisfies│    checkable)   ── ADR     │
  │ vault_source.py     ~380 LOC   │          └─────────────┬──────────────┘
  │   entry present + unopenable   │                        │ re-export
  │     → REFUSE, via check        │                        ▼
  │       value, decrypting no     │                 plugin/__init__.py
  │       secret              (D2) │
  └────────────────────────────────┘

  New boundary crossings — all checked against the seven contracts:
    _cli ──► app/vault          public API only          ✓ legal
    app/vault ──► _config/*     public → internal        ✓ unconstrained
    app/vault ──► app.utils     public → public          ✓
    _app ──► _config/vault_paths composition root        ✓
    app/vault ─X─ _engine       NOT imported; reached through the app object
    _config ─X─ _discovery      untouched — the peer contract still holds
```

### Why this shape and not the obvious one

**The obvious shape — put the four operations in `app/utils.py`** — is rejected.
It is where the existing vault functions live, so it looks like the consistent
choice. It would deepen the repo's worst **divergent change** (2380 LOC, 130
exports) with the largest single feature to land near it, and `research.md`
already recorded the pressure. *Delete before abstracting* does not apply — the
existing exports must stay (spec §14.3) — but *Extract Class* does: the new
lifecycle gets its own module and the old forwards are left exactly where they
are. Nothing is renamed, nothing is removed, and the smell stops growing.

**`vault_paths.py` is a split forced by physics, not taste.** `_config/vault.py`
imports `cryptography` at module level (lines 59–60), and `app/config.py:141`
records that this module is deliberately kept off the cold-boot path for
*every* app. The dormant source must answer "does this project have a vault?"
before deciding to import any of that — and the answer is a `stat`.
`vault_path_for_project` needs only `_primitives.locator`, zero crypto, so the
split is along a seam that already exists. `vault.py` re-exports the name, so
both current importers (`app/utils.py:2143`, `boot.py:991`) are untouched.
It is also the single place D4's walk-up lands, so every surface inherits it.

**`_cli/vault_cmd.py` follows a precedent rather than inventing one.**
`plugin_cmd.py` (598) and `self_cmd.py` (833) are already-extracted groups, and
the mount site is two lines (`from … import x_app` / `_mount(builtin_app, x_app,
"x")`). Adding four commands inline would push `builtins.py` past 3400 LOC;
moving the group out lands it ~250 lines lighter than today.

**One key check value, not four mechanisms.** D7 could have been four separate
features — sync's rotation guard, status's mismatch report, the refusal
message, inspect's readability. They are one question ("does this key open this
store?") asked from four places, so it is one row and one predicate. This is
the *rule of three* applied before the duplication exists rather than after.

### Iteration with Specify

Two candidate AFTERs were discarded:

1. **A separate `direct_secrets` table** (the storage option not chosen in D1).
   It keeps `secrets` untouched — attractive — but every read then consults two
   tables and merges them, and "which one wins" becomes a *new* rule maintained
   in `VaultSource`, `list`, `status`, `sync` and `inspect`. That is textbook
   **shotgun surgery** traded for a migration, and it makes spec §9.5's
   "sync never overwrites a direct entry" a cross-table invariant rather than a
   column check. Rejected in favour of D1.
2. **Validation inside `_config`,** next to the store. Illegal: the peer
   contract walls `_config` off from `_discovery`/`_engine`, and eligibility
   needs the job schema. Establishing that is what moved the seam to
   `app/vault.py`.

`spec.md` was revised during this loop rather than planned around — the audit
recorded in commit `7d626f8` rewrote §5, §7, §8, §9.1/9.3/9.4/9.5, §10, §11,
§14, §15 and §16. Most consequential: eligibility gained the
`from_config_model` requirement, because the AFTER made it obvious that a
secret *parameter* is addressable by a path the resolution path can never read.

## 3. Approach

### 3.1 Storage (D1, D7)

`_SCHEMA` gains `origin`, `created_at`, `updated_at`, `key_provider`; makes
`annotation`, `provider`, `synced_at` nullable; adds a one-row key-check table.
`_connect` gains `_upgrade(conn)`, stamped with `PRAGMA user_version`, run
inside the existing connection. Idempotent, additive, preserves ciphertext.
`put` gains `origin` and a no-clobber guard replacing today's unconditional
`ON CONFLICT DO UPDATE`; `delete(key)` is new and needs no key.

### 3.2 Key scope and initialization (D5, D6)

`KeychainKeyProvider` switches to a fixed account, ignoring `project_id` as
`EnvKeyProvider` already does, and gains `initialize_key`. `keyring` moves to a
`[keychain]` extra. `VaultKeyInitializer` lands in `_types/protocols.py` beside
`VaultKeyProvider` and is re-exported from `plugin/`. **ADR required** — new
public protocol *and* the ADR-016 §7 amendment (spec §8.1); one ADR covers both.

### 3.3 The public seam (spec §17.1)

`app/vault.py` holds the four operations plus canonical-path resolution. It
takes `app` and reads the schema *through* it, so it imports no peer layer.
Reports are frozen dataclasses with no field capable of holding plaintext.

### 3.4 Resolution (D2)

`VaultSource` distinguishes absent (fall through, unchanged) from
present-but-unopenable (refuse), deciding via the check value so no secret is
decrypted to make the decision.

### 3.5 Composition (spec §8 rule 2)

`build_remote_source` becomes `build_vault_source`: same behavior for
`remote=True`, plus a dormant source when `vault_paths.vault_path_for_project()`
exists. The gate is a `stat` before any crypto import.

### 3.6 The refresh wire (BEFORE smell 3)

`impl._build_resolution_chain` passes the vault source. A test asserts the two
call sites agree, so the comment stops being the only thing holding them
together.

## 4. Codemap contradiction found

`overview.md` line 72 states peer-layer independence "holds… No runtime
violation", and that is still true. But `modules.md`/`dependencies.md` describe
`app/utils.py` as the public façade without recording that it carries 130
exports across unrelated domains. That is not wrong, but it is the reason a
reviewer would expect the new code to land there. `/sync-docs` should record the
count when this feature lands; it is a documentation gap, not a drawing error.

## 5. Risks

| Risk | Mitigation |
|---|---|
| An abandoned vault from a past `remote_first()` experiment starts refusing runs under D2 once the dormant source sees it. | The refusal names `vault remove` / `vault clear`, both keyless. Called out in the changelog. |
| Making the source universal puts a keychain unlock prompt on ordinary runs for projects that have a vault. | Pre-existing behavior for `remote_first()` apps, now reaching more projects — not new behavior invented here. Surfaced for maintainer review in §7. |
| `_upgrade` runs against a vault someone is reading concurrently (`builtin parallel`). | WAL is already on; the upgrade is additive DDL inside the existing connection and takes the write lock for its duration. |
| `list --json` consumers break on `null` provider. | Pre-release stance (CONSTITUTION §7); recorded as a compatibility note in contracts §2.5 rather than described as additive. |
| Doc drift: `configuration.md:566` promises the opposite of D2. | Listed as a required edit in §6, not left to `/sync-docs`. |

## 6. Files to change

Hit sets from §0's blast-radius pass, not memory.

**New:** `_config/vault_paths.py`, `app/vault.py`, `_cli/vault_cmd.py`,
`contributor/adr/023-local-vault-access.md`.

**Changed:** `_config/vault.py`, `_config/vault_keys.py`,
`_config/vault_source.py`, `_types/protocols.py`, `plugin/__init__.py`,
`_app/boot.py`, `_app/impl.py`, `_cli/builtins.py` (mount only), `pyproject.toml`
(extra), `docs/guides/configuration.md`, `README.md`, `CHANGELOG.md`.

**Tests whose meaning changes** (from `find_referencing_symbols` on
`SecretsVault.put`): `tests/config/test_vault_store.py`,
`tests/config/test_vault_miss.py`, `tests/config/test_vault_staleness.py`,
`tests/cli/test_vault_commands.py`, `tests/app/test_remote_first.py`.

One of them is a *confirming* data point rather than a casualty:
`test_one_project_cannot_read_anothers_entry` already uses **one key across two
vault files** and asserts isolation comes from the files. It encodes D6's
position exactly and passes unchanged.

## Surviving smells

Smells the settled AFTER still carries. Nothing on
`.spec/CONSTITUTION.md` → *Forbidden Patterns* appears here; the AFTER has no
god-object above ~500 LOC among the modules it creates, no peer-layer
cross-import, no global mutable state, and no ABC used as a port.

| # | Smell | Where | Why it survives | Maintainer review? |
|---|---|---|---|---|
| 1 | **Divergent change** (ch34) | `app/utils.py`, 2380 LOC / 130 exports | Not deepened — the new lifecycle goes to `app/vault.py` — but not fixed either. Fixing it means moving or re-homing public names, which spec §14 forbids without a separate decision. | **Yes** — worth a standalone decision, not a side effect of this feature. |
| 2 | **Divergent change** (ch34) | `_cli/builtins.py`, ~2930 LOC after the move | Improved by ~250 lines, still a bloater. Extracting the remaining eight groups is a mechanical but broad change with no behavioral content. | No — strictly better than today. |
| 3 | **Shotgun surgery** (ch34), residual | `_app/boot.py` + `_app/impl.py` | §3.6 fixes the *drift* and adds a test that the two call sites agree, but there are still two call sites. Collapsing them into one is a boot/impl refactor far wider than this feature. | **Yes** — flagging that the fix is a guard, not a cure. |
| 4 | **Speculative generality / dead code** (ch35) | `audit_log` in `_config/vault.py` | Write-only: `audit_records()` has no shipped reader, only tests. This feature stops direct writes being mislabelled `"sync"` but does not remove or productise the table. Spec §16 defers it. | **Yes** — keep, remove, or promote is a product call. |
| 5 | **Primitive obsession**, residual (ch32) | `origin` stored as a TEXT column | D1 adds the column rather than a value object. A two-valued type code in SQLite is the KISS answer; an enum table would be ceremony for two rows. | No — deliberate, and the rule of three is not met. |

Entry 5 is the kind that is easy to over-fix. Entries 1, 3 and 4 are raised to
the maintainer by name in the Execute review, per step 11.
