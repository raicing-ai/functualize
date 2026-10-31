# Vault Remote Redemption — plan

Waves A–C (2026-09-24) are implemented and recorded in `tasks.md`. This plan
covers the **2026-10-31/11-01 revision** (spec A4, A10–A15, decisions O1–O4):
rebased onto scoped vault v3/v4 (#88, #117) and keyring unlock (#78), with
`--set` and the top-level alias removed.

## Retrieval (architecture pass, 2026-11-01)

- **zvec-grep** (index built in this worktree under the standing authorization,
  scoped per `code-intel`): ADR-023 §1 (presence decides resolution), §3
  ("`sync` must never overwrite a direct entry"; removing a provider entry is
  safe, the value is authoritative upstream); ADR-016 §5 (lazy, silent key
  read; only `vault unlock` prompts); `docs/guides/configuration.md` (the
  scoped `vault` commands); `docs/cli/user-app.md` ("there is no top-level …
  it lives under the reserved `builtin` subtree").
- **serena** `get_symbols_overview`: `app/vault_remote.py` holds 3 distinct
  groups — crypto (`seal_envelope`, `open_envelope`, `canonical`, key codecs),
  wire (`_request`, `parse_link`, `create_share`, `fetch_share_meta`,
  `redeem_link`) and verbs + store bridge (`share`, `load_vault_items`,
  `import_to_vault`). `app/vault.py` exports `resolve_vault_identity`,
  `vault_put`, `vault_inspect`, `vault_remove`, `vault_key_state`; it has **no
  public value read** and keeps key resolution private (`_resolve_key`,
  `_key_failure`).
- **graphify**: the shared `graphify-out/graph.json` predates this branch and
  has no node for `vault_remote.py` ("No node matching"); dependency direction
  was taken from the modules' import statements instead (counts below).
- **codemaps**: `contributor/architecture/codemaps/*.md` contain **no mention
  of the vault at all** (`grep -i vault` → 0 lines). The layer map in
  `overview.md` (app = public; `_config`, `_primitives` internal; `_cli` →
  public API only) is the one used below. Gap recorded for `/sync-docs`.
- Measured: `vault_remote.py` 827 lines, `app/vault.py` 1019, `_cli/vault_cmd.py`
  1431. `vault_remote.py` imports `_config.vault_keys.resolve_vault_key` ×2 and
  `app.vault._project_id` ×2 (a private name); `vault_cmd.py` imports only
  `functualize.app.*`.

## Skills consulted

`python-design-patterns` (in-repo: SRP, KISS, separation of concerns) and
`coding__design-patterns-refactoring` (user-level; the Refactoring.Guru smell
catalogue used for every smell name below).

## BEFORE

```
 layer:   _cli (delivery)        app (PUBLIC seam)                          _config (internal)         _primitives
          ─────────────────      ─────────────────────────────────────      ──────────────────────     ─────────────
          vault_cmd.py ────────▶ vault.py ──────────────────────────────▶  vault.py (SecretsVault) ─▶ vault_identity.py
           share/redeem/show       resolve_vault_identity, vault_put…        vault_key_resolver          "base" stored as
             │                                                                                             a 4th env  ✗
             └───────────────▶  vault_remote.py  (827 lines)
                                 ├ crypto   (vendored)
                                 ├ wire     (vendored)
                                 └ verbs + store bridge ──────────────────▶ vault.py, vault_paths,
                                       │                                    vault_keys.resolve_vault_key ✗ (API changed)
                                       └──▶ app.vault._project_id  (private) ✗

          builtins/__init__.py  BUILTIN_NAMES = {builtin, vault};  add_command(vault_app, "vault")
          completions/data.py, app/commands.py: alias special cases
          dispatch.py: builtin names win before groups/jobs → a project job/group `vault` unreachable ✗
```

Boundary crossings: `_cli → app` only (legal); `app → _config` (legal: public
may import internal); `app.vault_remote → app.vault` private name (legal to the
linter, illegal by convention).

**Smells in BEFORE** (catalogue names):

| Smell | Where | Evidence |
|---|---|---|
| Divergent Change | `app/vault_remote.py` | changes for funccloud contract reasons (crypto, wire) *and* local vault policy reasons (store bridge); this rebase broke only the third part |
| Inappropriate Intimacy | `vault_remote.load_vault_items` / `import_to_vault` → `app.vault._project_id`, `_config.vault.SecretsVault` | a second path to the store beside `app/vault.py`; it is why `resolve_vault_key`'s API change broke it and `vault_put`'s checks are skipped |
| Duplicate Code | the same two functions vs `app/vault.py` key resolution | both resolve a key and open the store, differently |
| Shotgun Surgery | top-level alias across `builtins/__init__.py`, `completions/data.py`, `app/commands.py`, 8 test modules | one decision, nine files |
| Primitive Obsession | `import_to_vault(scope: str)` + flat `f"{scope}.{name}"` keys | a dotted string standing for an identity v2 replaced with `VaultIdentity` |

## AFTER

```
 layer:   _cli                    app (PUBLIC)                                 _config                         _primitives
          ────────────            ──────────────────────────────────────       ──────────────────────          ─────────────
          vault_cmd.py ─────────▶ vault_handoff.py   (new)
           share/redeem/show        select entries · env label · pre-burn
           (flags, prompt,          checks · plan_import · apply_import ·
            render only)            export names
                                      │        │          │
                                      │        │          └──────────────────▶ resolved_field
                                      │        │                                (env_name_for, group_env_name_for)
                                      │        ▼
                                      │      vault.py  + _read_value           vault.py (SecretsVault)  ───▶ vault_identity.py
                                      │                + vault_supersede_synced  + supersede()                  base = shared ✓
                                      │                + vault_require_key  ───▶ vault_key_resolver
                                      ▼
                                    vault_remote.py   crypto + wire only (vendored, behaviour-faithful)

          builtins/__init__.py  BUILTIN_NAMES = {builtin}   (alias removed; master shape)
```

Dependency direction: `_cli → app.vault_handoff → {app.vault_remote, app.vault,
_config.resolved_field}`; `app.vault → _config.vault → _primitives`. Nothing
points upward. Import-linter: "_cli uses public API only" holds (`vault_cmd` →
`app.*`); "Internal never imports public" holds (`_config` gains a method,
no import); "Primitives import nothing internal" holds (`SHARED_SLOT` is
local); "Peer layers are independent" untouched.

**Smells the AFTER removes**: Divergent Change (crypto/wire vs policy split by
Extract Module), Inappropriate Intimacy and Duplicate Code (every store touch
goes through `app/vault.py`), Shotgun Surgery (alias deleted), Primitive
Obsession (`VaultIdentity` end to end; `scope: str` gone).

**Smells the AFTER introduces, checked per candidate:**

1. *Candidate A — keep everything in `vault_remote.py`, fix in place.* Keeps
   Divergent Change and grows the module past 1000 lines; rejected.
2. *Candidate B — `replace_origin: bool` on `SecretsVault.put` / `vault_put`.*
   Introduces a flag argument that inverts the documented "never overridden by
   `replace`" rule of the same method (catalogue: **Replace Parameter with
   Explicit Methods**). Rejected for an explicit `SecretsVault.supersede()` /
   `vault_supersede_synced()`.
3. *Candidate C — the chosen AFTER.* Introduces one private plaintext read
   (`app.vault._read_value`) and one new module. Checked: `vault_handoff` has one reason
   to change (local materialisation policy) and one caller (`vault_cmd`); it
   is not a Middle Man (it decides, it does not forward). See Surviving smells.

Forbidden-pattern check (`.spec/CONSTITUTION.md`): no class over ~500 lines is
created or grown (`VaultIdentity`, `ImportPlan`, rows are small dataclasses); no
peer-layer cross-import; no module-level mutable state; no ABC or implicit
`Callable` port; no hard-coded config path; `_cli` imports public API only.
**None present.**

## Surviving smells

| Smell | Where | Why accepted | Maintainer review |
|---|---|---|---|
| Large Class (module analogue) | `_cli/vault_cmd.py`, 1431 lines | one Click family; the revision moves logic *out* of it (modes, checks, rows live in `vault_handoff`). Module size is not on the forbidden list, which is about classes | no |
| Inappropriate Intimacy (contained) | `app.vault_handoff` → `app.vault._read_value` | maintainer decision 2026-11-01 (option B): no public plaintext read. The private import stays inside the `app/` layer and has exactly one caller, unlike BEFORE's reach into `_config` and its own key resolution | no — decided |
| Temporal coupling | `redeem`: meta → checks → redeem → confirm → apply | forced by the frozen wire: items are readable only after the burn. Every check that *can* precede it does (A11). The remaining post-burn failures (wrong link key, `no_match`, `malformed`, user abort) are disclosed, not hidden | **yes** — see "Not checkable before the burn" |

## Technical approach

- **Share (A4, A10, A11, A12).** `vault_cmd share` →
  `vault_handoff.select_for_share(app, selectors | ALL, cwd)` → per entry
  `resolve_vault_identity` → `app.vault._read_value(app, identity, cwd)` (private); an entry that
  resolved only through the shared fallback is refused (A12). Items are
  `{name: identity.encode(), kind: "secret", value}`; labels gain
  `env:<active>`. `--set` and `--from-vault` are removed.
- **Share selection (A4).** `--entry SEL`… / `--all` / picker, nothing else.
  `vault_handoff.shareable_entries` builds the rows from `vault_entries()`
  (no key needed) filtered to the active environment and to identities that
  still resolve. Subtree membership for `group=G`: a **group** entry is in `G`
  when its target is `G` or starts with `G.` (dots belong to group paths); a
  **job** entry is in `G` when its descriptor's own `group` is `G` or under
  it — read from `app.get_job(target)`, never by splitting the registered
  name (SD/12779576: "it is never split back apart"). The picker is a small
  CLI-layer checklist: the existing terminal multi-select lives in
  `_engine/capabilities/stdin_collector.py`, which `_cli` may not import, and
  has no pre-ticked defaults or group rows.
- **Redeem (A11, A13).** Order, each step refusing before the next:
  project found → TTY/`-y`/`--only`/`--print-only` → `fetch_share_meta`
  (gone/expired/not-found answered without a POST; `env:` label equals the
  active environment) → `vault_require_key` (store mode) → `redeem_link` →
  `plan_import` → prompt or `-y`/`--only` → `apply_import`.
- **Synced rows (O2).** Status `synced`, selectable, **unticked**, suffix
  `(synced from <annotation>)`. Applying it calls `vault_supersede_synced`,
  which atomically rewrites the row as `DIRECT` with `annotation`, `provider`
  and `synced_at` cleared. Consequence (ADR-023 §3, by design): the next
  `vault sync` reports "direct entry already exists; remove it before
  syncing" for that identity; the confirmation row says so.
- **Export names (O1).** `--print-only` / `--dotenv` write `JOB_FIELD` for a job
  config field and `SCOPE__FIELD` for a group option, via
  `_config.resolved_field.env_name_for` / `group_env_name_for` — the names a
  run actually resolves.
- **Not checkable before the burn (O3).** The receiver's vault key is local:
  checking it needs no endpoint. What frozen v1 cannot check before a burn is
  whether the link's own key is right, or which items it holds: meta returns
  labels, counts and timestamps only, and `ciphertext` requires the redemption
  token that only `redeem` issues. A mistyped-but-well-formed link therefore
  spends a redemption and fails `open_failed`. Closing that needs a v2 wire
  change in funccloud (e.g. a key-check value in meta); recorded as a proposal
  for the funccloud repo (SD/23822368), out of scope here. `plan_import` takes
  its identities from the decrypted payload under v1, so a v2 manifest can feed
  it unchanged; the "payload items equal the planned items" check is applied
  under v1 too.
- **Alias removal (O4).** Revert the alias hunks to master's shape; the
  journey transcript becomes `func builtin vault share|redeem|show`.

## Files to change (hit sets)

- Alias — the hit set is the branch's own diff, not a grep for `A8` (21 files
  match that label, most of them other features'): files changed in
  `origin/master...HEAD` whose added lines mention the alias.
  Source: `_cli/builtins/__init__.py` (`BUILTIN_NAMES`, `builtin_descriptions`,
  the `add_command`), `_cli/completions/data.py`, `app/commands.py`.
  Tests restored to master's version: `tests/_cli/test_dispatch_preservation.py`,
  `tests/cli/test_dispatch_properties.py`, `tests/cli/test_command_inventory_parity.py`,
  `tests/cli/test_help_surface_pinned.py`, `tests/cli/test_info_subcommands.py`,
  `tests/core/test_click_command_provider.py`, `tests/core/test_plugin_command_provider.py`,
  `tests/config/test_secret_surface_parity.py` (the fixture job renamed
  `vault` → `emit_annotated` "because the name is reserved" goes back to
  `vault`), `tests/_cli/__snapshots__/test_snapshot_baseline/test_snapshot_panel_ring_open.raw`.
  Spelling only: `tests/vault_remote/test_cli.py`, `docs/cli/vault-share.md`,
  `_cli/vault_cmd.py` / `app/vault_remote.py` comments.
- Seam: `src/functualize/app/vault.py`, `src/functualize/_config/vault.py`,
  `tests/app/test_vault_seam.py`, `tests/config/test_vault_store.py`.
- Handoff: new `src/functualize/app/vault_handoff.py`,
  `tests/vault_remote/test_handoff.py`; trimmed `src/functualize/app/vault_remote.py`.
- CLI: `src/functualize/_cli/vault_cmd.py`, `tests/vault_remote/test_cli.py`.
- Docs: `docs/cli/vault-share.md`, `.spec/STATUS.md`.

## Risks

- **Cross-repo transcript.** funccloud chain item 3 (the journey eval) was
  written against `func vault redeem`; removing the alias changes the command it
  must run. Not a frozen wire/crypto contract, but it must be told.
- `vault_supersede_synced` is a new write path in the store; it is covered by a
  store test that the row's origin, annotation, provider and `synced_at` all
  change in one transaction.
- `env_name_for` is not in `resolved_field.__all__`; importing it from `app` is
  legal but should be made explicit (add to `__all__`).

Gates: house spec-workflow hooks; every wave ends green on its step tier; the
vectors test stays the one non-negotiable merge blocker.
