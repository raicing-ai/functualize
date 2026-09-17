# Specification: local-vault-access

## 1. Problem

Functualize already has an encrypted per-project vault, but its usable path is
provider-oriented: an application selects `remote_first()`, declares remote
references, exports or retrieves a key out of band, and runs `vault sync`.

A developer with one local project secret cannot currently ask ordinary
discovery-mode `func` to initialize secure storage, put that value, and resolve
it into a normal job. They must use plaintext config/environment state or adopt
remote-provider concepts that are irrelevant to the task.

The feature must add that direct local lifecycle without removing or renaming
existing public Python APIs, presets, provider declarations, or vault commands.

## 2. Goals

1. An ordinary discovered job can receive a locally provisioned secret through
   the normal configuration path.
2. A developer can initialize, put, inspect, and remove a value through
   `func builtin vault` without a remote provider or cloud account.
3. The default interactive flow never displays plaintext.
4. CI and other non-TTY callers have an explicit, deterministic flow.
5. Job execution remains offline; only explicit provider synchronization may
   contact a provider.
6. Existing public vault and provider behavior remains available.
7. Direct and provider-backed entries have truthful, distinguishable metadata.

## 3. Non-goals

- Plaintext `get` or `reveal` commands.
- Shell export or child-process secret injection.
- Cross-project or cross-user sharing.
- Environment bundles, burn links, accounts, or FuncCloud synchronization.
- Connection management, policy, approvals, runners, or remote execution.
- Binary values; this increment stores UTF-8 text.
- A user-facing audit/history product.
- Automatic provider access during boot or job execution.
- Replacing the current structured store format. Additive columns and a
  one-time in-place upgrade **are** in scope (D1); a format replacement is not.
- Replacing provider-annotation syntax with a new registry.
- Removing, renaming, or deprecating an existing public API or command.

## 4. Users and stories

### US-1 — local developer

As a developer with an ordinary discovered job, I can initialize the project
vault, put one declared secret, and run the job without configuring a remote
provider or writing plaintext to a project file.

### US-2 — job author

As a job author, I use the existing secret declaration vocabulary. My job
receives the same `Secret[str]` value shape regardless of whether environment,
file, CLI, or local vault supplied the underlying string.

### US-3 — CI operator

As a non-interactive operator, I can select the environment key source and pass
a value through stdin or a file. No command waits for a prompt.

### US-4 — provider-backed user

As an existing `remote_first()` user, my preset, declarations, sync flow,
offline reads, staleness behavior, and public APIs keep working.

### US-5 — diagnoser

As an operator, I can inspect whether a path is eligible, stored, readable,
direct or provider-backed, and which source would win without receiving its
plaintext.

## 5. Terminology

- **Eligible field:** a **config-model** field of the selected job whose
  existing descriptor marks it secret. `Secret[str]` and the supported explicit
  secret field marker both produce that descriptor state.

  The config-model half is load-bearing, not decoration. `job_input_schema`
  publishes `descriptor.config_fields or descriptor.parameters`, and a plain
  function parameter can carry `secret=True` too — but config resolution only
  ever walks `config_class.model_fields`, so a secret *parameter* could never
  receive a vault value. Eligibility therefore also requires
  `from_config_model=True`; a job with no config model has no eligible fields.
- **Canonical vault path:** dot-joining the published command path and one
  top-level eligible field name. Example: command path `infra deploy` and field
  `api_token` produce `infra.deploy.api_token`.
- **Direct entry:** a value explicitly written by `vault put`.
- **Provider entry:** a value written by `vault sync` from an existing provider
  declaration.
- **Readable entry:** an entry in a store whose **key check value** the
  currently resolved key opens.
- **Key check value:** one non-secret row, written when the store first
  receives a write, holding a fixed known plaintext encrypted under the vault
  key. It answers "is this the key this store was written with?" without
  decrypting any secret, and is what lets `inspect` and `status` report
  readability while holding no plaintext (D7).
- **Key scope:** which vaults one key opens. A provider's choice. Both shipped
  providers are **user-scoped**: one key opens every project's vault. Isolation
  between projects comes from the separate files, not from separate keys (D6).
- **Project (for vault location):** the directory found by walking **upward**
  for `.functualize/`, falling back to hashing the working directory when there
  is none — the same rule discovery already uses to locate its cache (D4).

  The vault does not do this today: it hashes the working directory
  unconditionally, so the same project resolves to a different vault depending
  on which subdirectory you stand in, and the store's own claim to agree with
  the discovery cache "on what this project means" is false wherever
  `.functualize/` exists. This feature makes users meet that on their first run
  — `vault put` from a subdirectory, then the job from the root — so it is
  fixed here rather than documented as a trap. Every vault surface and the
  resolution path must agree on one answer.

Nested-model field paths are outside this increment. A secret must be a
top-level published field of the selected job schema.

## 6. First-run behavior

The default local flow is:

```text
func builtin vault init
func builtin vault put deploy.api_token
func deploy
```

1. `init` ensures a **user-scoped** vault key exists. It needs no project, no
   app and no discovery: one key opens every project's vault (D6), so this is
   run once per machine rather than once per project.
2. With no explicit key source, an interactive invocation prefers an available
   OS-keychain provider capable of initialization. The `keyring` library is an
   optional extra (`functualize[keychain]`), so on a stock install this
   refuses and the refusal names both routes forward (D5, §9.1).
3. `put` resolves `deploy.api_token` against the discovered command schema
   before requesting a value.
4. Interactive `put` prompts with echo disabled.
5. A successful write reports the path and non-secret metadata only.
6. The later job run resolves the entry through the ordinary config path and
   supplies the declared secret wrapper to the job.

Neither `init` nor `put` requires a remote provider. The job run makes no
provider network request.

**`init` is a preflight, never a gate (D8).** The store is created lazily by
the first write, so anything that works today without `init` — notably
`export FUNCTUALIZE_VAULT_KEY=… && func builtin vault sync` in CI — keeps
working untouched. `init` must never become a prerequisite for `put` or `sync`.

`keygen` and `init` are not two stages of one sequence. `keygen` prints a key
and stores nothing, for an operator who will place it themselves; `init`
persists a key into a provider and never shows it. The only hard requirement in
the system is that a key is resolvable when something first writes.

## 7. Eligibility and canonical paths

1. The command path must identify exactly one runnable job.
2. The field must be a **config-model** field of that job (`from_config_model`),
   present in the canonical published input schema. A job with no config model
   has no eligible fields, however its parameters are annotated.
3. The field descriptor must be secret.
4. A plain field is rejected even when its name resembles a credential.
5. Validation completes before stdin/file/prompt content is read.
6. Error output identifies the invalid path and explains how to inspect the
   job schema; it never prints candidate values.
7. **The split is rightmost.** A path is parsed as
   `<everything before the last dot>` = the job's full dotted name, and
   `<after the last dot>` = the field. This is correct because a registered job
   carries its group in its canonical name (`infra.aws.provision-it`), and it
   stays correct for a leaf name that itself contains a dot.
8. **Command segments are normalized; the field segment is the model field
   name.** Job and group names are lowercase-hyphenated at registration
   (`data_ops.run_etl` → `data-ops.run-etl`), so the command half of the path
   uses that spelling. The field half must be the config-model field name
   (`api_token`) — that is the string config resolution is keyed on, not the
   CLI flag spelling (`--api-token`). A path whose field segment is given in
   flag spelling is accepted and normalized to the model field name; the
   reports always echo the canonical form.

## 8. Resolution behavior

For an eligible field, observable precedence is:

```text
per-run override or explicit job argument
    → matching readable local-vault entry
    → environment
    → configuration file
    → model default
```

Rules:

The governing rule is **presence, not origin** (D2):

```text
vault holds no entry for this path  ->  fall through to env / file / default
vault HOLDS an entry for this path  ->  that entry is the intended value;
                                        if it cannot be opened, refuse the run
```

Rules:

1. No store or no matching entry leaves pre-feature behavior unchanged and
   emits no vault warning for a direct entry.
2. A matching direct entry is available to ordinary `FunctualizeApp` execution,
   not only one `func` dispatch path. This includes the chain rebuilt by public
   `FunctualizeApp.refresh()`, which today drops the vault source entirely
   (§14.7).
3. Explicit job input continues to win over the vault.
4. A readable vault entry wins over environment, file, and default values.
5. If entry metadata exists but no key is available, resolution refuses rather
   than silently selecting a lower-precedence value. **This applies to provider
   entries as well as direct ones** — the rule is about presence, and an entry
   that is present is the intended value whatever wrote it.
6. Wrong-key, authentication, or corruption errors refuse; they are not misses.
7. Provider **staleness** behavior is unchanged: warn once and continue
   (ADR-016 §6). Provider **miss** behavior — no entry at all — is unchanged:
   fall through, loudly (ADR-016 §7).
8. Provider network access never occurs as a consequence of resolution.

### 8.1 Relationship to ADR-016 §7

Rule 5 **narrows ADR-016 §7 and must ship with an ADR amendment saying so.**
That section rejected hard-failing, and was right to for the case it considered:
a *declared annotation with no vault entry*, where failing would make the first
run after adding an annotation impossible. That case still falls through.

What changes is a case ADR-016 did not separate out: an entry that **is**
present but cannot be opened. Today `VaultSource.usable` is false whenever no
key is available, so every lookup — including one whose value is sitting in the
store — falls through to a lower-priority source. The operator then runs with a
stale environment variable while believing they are running with the vault's
value, which is the substitution ADR-016 exists to prevent, arriving through a
door it left open.

The recovery paths keep this from being a trap, and all three are cheap:
`vault remove PATH` and `vault clear` need no key (§9.4, §9.5), and `vault sync`
refreshes provider entries from upstream. The key check value (§11) makes the
refusal name the fix rather than surfacing as a bare decryption error.

CI is structurally unaffected: a fresh runner has no vault file, therefore no
entries, therefore nothing to refuse. The one exposed case — a cached
`~/.local/share/functualize` plus a rotated key — is reported by `sync` on the
first run rather than by the job later.

## 9. Commands

All new commands live under the existing `func builtin vault` group.

### 9.1 `init`

```text
func builtin vault init [--key-source SOURCE] [--json]
```

- The key it ensures is **user-scoped**: one key for every project (D6). `init`
  therefore needs no project, no app and no discovery.
- Idempotent when the selected provider already holds a usable key.
- Without `--key-source`, interactive mode chooses the first available
  initializer using the existing non-interactive-before-interactive provider
  ordering rules; the built-in keychain is the expected desktop path *when
  `functualize[keychain]` is installed*.
- **`init` has two behaviors and must say which one happened.** With a
  keychain-shaped source it *creates and persists*; with `--key-source env` it
  *validates only* and writes nothing, anywhere. Human output says either
  "created a key in your OS keyring" or "validated $FUNCTUALIZE_VAULT_KEY —
  nothing was written", never a generic "initialized". JSON carries this as
  `created`.
- `--key-source env` validates an existing `FUNCTUALIZE_VAULT_KEY`; it does not
  write to the caller's shell or print a generated key. It is a useful CI
  preflight — the existing key decoder already rejects a truncated key rather
  than yielding a different valid one — and it remains optional.
- Reports which provider it settled on. With `FUNCTUALIZE_VAULT_KEY` exported,
  env outranks the keychain everywhere, so `init` must not announce "keychain"
  by assumption.
- Refuses when no selected provider can initialize or supply a valid key. The
  refusal is the teaching surface for a stock install and **names both routes**:
  installing `functualize[keychain]`, or `keygen` → export → `--key-source env`.
- Never replaces an existing key, and never prints one. It does not call
  `keygen` or emit its output.
- Writes nothing to the vault file. The key check value is written by the first
  *store* write, which is `put` or `sync` (§11).

### 9.2 `put`

```text
func builtin vault put PATH [--stdin | --file FILE] [--replace] [--json]
```

- `--stdin` and `--file` are mutually exclusive.
- With neither option, a TTY receives a masked prompt.
- Without an explicit input option, a non-TTY invocation exits with usage
  failure and does not read implicitly.
- stdin removes one terminal line ending (`LF` or `CRLF`) and preserves all
  other characters.
- file input decodes UTF-8 and preserves its contents exactly.
- Empty input is refused.
- Existing entries are refused unless `--replace` is present.
- Replacing a provider entry is refused; this increment does not silently
  change an entry's provenance.

### 9.3 `inspect`

```text
func builtin vault inspect PATH [--json]
```

The report contains eligibility, existence, origin, provider/reference when
applicable, timestamps, key availability, readability state, staleness when
applicable, and the source kind that would currently win. It contains no value,
ciphertext, nonce, or key bytes.

`inspect` can explain an unknown/ineligible path and exit with usage failure;
it does not require the vault key merely to report metadata.

Readability is answered against the **key check value**, never by decrypting the
entry (§11). So `inspect` distinguishes `readable`, `key_unavailable` and
`wrong_key` while holding no plaintext at any point, which is what makes §12.5
true of it rather than merely aspirational.

### 9.4 `remove`

```text
func builtin vault remove PATH [--yes] [--json]
```

- **Removes any entry, of either origin, and never needs the vault key (D3).**
  Metadata columns are cleartext by design and a delete decrypts nothing, so
  `remove` is the scalpel that recovers a store this machine cannot open.
- Reports the origin it removed.
- Warns **only** when the removed entry was `direct`, because that is the only
  kind with no upstream copy. Removing a provider entry is safe: the value is
  authoritative upstream and the next `sync` refills it.
- A missing entry is a successful no-op and reports `removed: false`.
- Interactive mode confirms unless `--yes` is present.
- Non-TTY mode requires `--yes` when an entry exists.

This replaces the earlier draft's refusal to remove a provider entry. That
refusal fired exactly in the case the command exists to rescue — a locked-out
store whose unopenable entry is usually provider-written — and the provenance
property it was protecting is carried by §9.5's rule that *sync* must never
overwrite a direct entry, which is separate and stays.

### 9.5 Existing commands

`sync`, `list`, `status`, `clear`, and `keygen` remain available.

- `list` and `status` gain origin-aware metadata where applicable. Because a
  direct entry has no `provider`, no `annotation` and no `synced_at`, the
  existing `list` renderers must stop assuming those are present — today the
  human path measures `len(entry.provider)` and calls
  `entry.synced_at.isoformat()`, both of which fail on a direct row. This is a
  compatibility change to a shipped JSON shape, and §14.6 governs it.
- `status` gains `direct_entries` / `provider_entries` counts, and reports when
  the store's key check value does not match the currently resolved key.
- `clear` retains its name and behavior, **gains `--json`**, and its
  confirmation and report must state how many direct and provider entries will
  be removed and warn that direct values may have no upstream recovery source.
  It continues to require no key, so it remains the sledgehammer counterpart to
  `remove`.
- `sync` never overwrites a direct entry. A direct/provider conflict is
  reported, other successful syncs are retained, and the command exits
  non-zero.
- **`sync` detects a changed vault key and says so.** It compares the resolved
  key against the store's key check value before writing. Today `sync` only
  ever writes — it never reads an existing row — and it rewrites only paths that
  are *currently declared* as annotations. So after a key change, rows whose
  annotation was since removed, and every direct entry, stay encrypted under the
  old key. Under §8's presence rule those orphans become permanent hard
  failures, so `sync` reporting `ok: true` while minting them is not acceptable.
  On a mismatch `sync` refuses, names the orphans it would have created, and
  points at `vault remove` / `vault clear`.
- `keygen` remains an explicit plaintext-producing escape hatch; `init` does
  not call it or print its output.

The vault key and a provider's credentials are independent. The vault key opens
the local file and never leaves the machine; provider credentials authorize the
*fetch* and are what `is_ready()` reports on. Rotating the vault key needs no
provider credentials; recovering values after rotating it needs both. In CI they
arrive from the same secret store and feel like one thing; on a workstation they
are not, and no command may wire `init` to touch a provider.

## 10. Key-provider behavior

1. Existing `VaultKeyProvider` remains read-only and unchanged.
2. Initialization is a separate optional structural capability so third-party
   read-only providers remain valid.
2a. **Key scope is a provider's choice, and both shipped providers are
   user-scoped (D6).** The environment provider already ignores `project_id`
   and documents why; the keychain provider is changed to match, so that one
   key opens every project's vault. `get_key(project_id)` and
   `initialize_key(project_id)` both keep the parameter, so a third-party KMS
   or hosted provider may still scope per project — the seam is unchanged.

   This is a deliberate behavior change to a shipped provider, made now because
   it is free now: nothing in the codebase has ever written a keychain key
   (`set_password` appears nowhere), no test asserts per-project keychain
   scoping, and `KEYCHAIN_SERVICE` is not a public export. Once `init` ships and
   begins writing keys, the same change becomes a migration.

   It closes a live hazard rather than adding one. With the two providers
   disagreeing about scope, *which* scope applies depends on whether an
   environment variable happens to be exported — so exporting
   `FUNCTUALIZE_VAULT_KEY` once silently re-encrypts every synced project under
   the shared key, and unsetting it later strands them all. The check value
   would diagnose that; agreeing on scope prevents it.

   The property given up is real and is accepted, not elided: one compromised or
   lost user key now reaches every project's vault rather than one. It was never
   a system property — only one provider's, while the primary non-interactive
   route had no such isolation — and an inconsistent guarantee is worth less
   than none. Isolation between projects remains the separate files.
3. The configured provider registry used by `init`, `put`, `status`, `sync`,
   and job resolution is the same registry.
4. Non-interactive providers are checked before interactive providers.
5. Interactive providers are never consulted without a TTY, except when the
   caller explicitly selects one and the provider can operate without a prompt.
6. A generated key is exactly the size required by the existing vault cipher.
7. No plaintext key fallback or project-file key storage is introduced.

## 11. Entry provenance and metadata

Every entry reports enough metadata to distinguish:

- canonical path;
- origin: `direct` or `provider`;
- provider identifier and reference for provider entries;
- creation and last-update time for direct entries;
- last-sync time for provider entries;
- key-provider identifier used to write the store, where already tracked.

Metadata must not include secret plaintext. Direct values and provider values
may share encrypted storage but cannot silently replace one another.

### 11.1 Storage change

The existing `secrets` table cannot express this: `annotation`, `provider` and
`synced_at` are all `NOT NULL`, because every row it was designed for came from
a sync. A typed-in value has none of the three.

The store therefore gains columns — `origin`, `created_at`, `updated_at`,
`key_provider` — and `annotation`, `provider` and `synced_at` become nullable
(D1). Filler values were rejected: a row claiming `provider = "direct"` makes
every existing reader see a provider name that is not one, and a `synced_at`
meaning "when I typed it" is simply untrue.

**A one-time in-place upgrade is required and is in scope.** The schema is
applied today with `CREATE TABLE IF NOT EXISTS` and carries no `user_version`,
so an existing `vault.db` would never gain the columns and every new write
against it would fail. The upgrade must be idempotent, must preserve existing
rows and their ciphertext untouched, and must stamp a version so it runs once.

### 11.2 Key check value

One additional non-secret row holds a fixed known plaintext encrypted under the
vault key. It is written when the store first receives a write — by `put` or
`sync`, never by `init`, so `init --key-source env` stays genuinely read-only
and the vault file continues to appear on first write rather than before.

It is what lets the system answer "is this the key this store was written
with?" without decrypting a secret, and it earns its place four times over:
`sync` detects a key change instead of silently minting orphans (§9.5);
`status` can report a key mismatch, which it cannot today; the §8 refusal names
the fix instead of surfacing as a bare decryption error; and `inspect` reports
readability while holding no plaintext (§9.3, §12.5).

## 12. Output and security

1. Human and JSON output for every new command contains metadata only.
2. Exceptions and logs do not include value input, decrypted output, key bytes,
   ciphertext, or nonces.
3. Validation happens before reading secret input wherever possible.
4. The exact submitted secret bytes do not appear in the database or SQLite
   sidecar files.
5. Existing redaction remains a defense in depth; commands are designed not to
   receive decrypted values unless the operation requires a write or job
   resolution.
6. Help and examples never place secret values in command arguments.

## 13. Exit semantics

- Success: `ExitCode.OK` (`0`).
- Invalid syntax, unknown path, ineligible field, incompatible input options:
  `ExitCode.USAGE` (`2`).
- Missing key, unavailable initializer, overwrite refusal, provider-origin
  conflict, wrong key, corrupt ciphertext: `ExitCode.REFUSED` (`3`).
- Existing provider sync partial-failure behavior remains unchanged.

JSON failures contain a stable machine-readable reason code and safe message;
they never require parsing human stderr to identify the failure class.

## 14. Public compatibility

1. No existing public Python name is removed, renamed, or made private.
2. `remote_first()` retains its current provider-oriented behavior.
3. Existing `functualize.app.utils` vault exports remain callable.
4. `VaultKeyProvider` retains its current required methods.
5. Existing vault subcommands retain their names.
6. Existing provider annotation syntax continues to work.

Two shipped behaviors **do** change, each deliberately and each recorded:

7. `FunctualizeApp.refresh()` currently rebuilds the resolution chain without a
   vault source at all, though the rebuild is documented as needing to stay
   argument-for-argument equivalent to the boot path's call. The vault is
   therefore silently dropped from a refreshed app today, for `remote_first()`
   users as much as for this feature. This is fixed rather than reproduced, and
   §15 AC-13 covers the wire.
8. `list --json` entry objects: `provider`, `annotation` and `synced_at` become
   nullable, because a direct entry has none of them. Existing fields are not
   removed and no field is renamed, but a consumer that assumed `provider` was
   always a string must now handle `null`. This is called out as a compatibility
   note rather than described as purely additive.

`init` is additionally constrained **not** to become a gate: every flow that
works today without it must keep working (§6, D8).

Any future removal requires a separate explicit maintainer decision.

## 15. Acceptance criteria

### AC-1 — direct local happy path

Given an ordinary discovery-mode project with a top-level required
`Secret[str]` field and no remote provider, `init`, `put`, and the normal job
command succeed; the job receives the submitted secret.

### AC-2 — common execution path

The same stored value resolves when the job runs through direct
`FunctualizeApp` execution. Vault resolution is not implemented only in
`func`'s pre-boot or dispatch layer.

### AC-3 — cold/warm parity

The happy path produces the same value and type on cold discovery and a second
boot using the discovery cache.

### AC-4 — precedence

An explicit job argument beats vault; vault beats environment, configuration
file, and model default; removing the entry restores previous resolution.

### AC-5 — dormant default

Projects with no store and projects with a store but no matching path retain
their previous job result and emit no direct-vault warning.

### AC-6 — unreadable entry refuses, by presence not origin

When matching entry metadata exists but its key is absent, wrong, or corrupt,
the run refuses and does not use a lower-precedence value. This holds for a
provider entry exactly as for a direct one. The refusal message names a
recovery: `vault sync`, `vault remove PATH`, or `vault clear`.

An entry that is **absent** still falls through, unchanged, and a declared
annotation with no entry still warns and continues (ADR-016 §7).

### AC-7 — schema eligibility

`put` accepts the existing supported secret declarations and rejects a plain
field before reading prompt/stdin/file data.

### AC-8 — non-interactive behavior

CI can initialize from an explicit environment key and put through stdin/file.
A non-TTY call without explicit input never prompts or hangs.

### AC-9 — overwrite and provenance

Direct overwrite requires `--replace`; provider entries cannot be replaced or
removed as direct entries; sync cannot overwrite a direct entry.

### AC-10 — no plaintext surfaces

For a distinctive submitted secret, the exact bytes are absent from stdout,
stderr, logs, JSON, errors, database files, and SQLite sidecars across init,
put, inspect, list, status, remove, clear, sync, and job execution.

### AC-11 — offline run

After provisioning, job execution succeeds with outbound provider access
denied and makes no provider call.

### AC-12 — compatibility

The existing preset, public Python vault names, provider protocol, provider
annotations, and existing vault commands remain present and their existing
behavioral tests pass.

### AC-13 — reachability proof

The production call path is named for direct CLI and `FunctualizeApp`
execution, cold and warm. Removing each composition wire makes a public E2E
test fail. **There are two wires, not one**: the boot-path chain build and the
rebuild behind public `FunctualizeApp.refresh()`. A test must fail for each.

### AC-14 — store upgrade

A vault written before this feature opens, keeps every existing row and its
ciphertext byte-for-byte, gains the new columns, and accepts a direct write
afterwards. Running the upgrade twice changes nothing.

### AC-15 — key change is reported, never silently orphaned

With a store written under one key and a different key resolved, `sync` refuses
and names what it would have orphaned, `status` reports the mismatch, and
`inspect` reports the path as unreadable — none of them decrypting a stored
secret to do so.

### AC-16 — recovery needs no key

With no key available at all, `remove PATH` deletes an entry of either origin
and reports which, and `clear` empties the store. Removing a direct entry warns
that it has no upstream copy; removing a provider entry does not.

### AC-17 — one key, every project

A key created once by `init` opens a vault in a second, unrelated project with
no further initialization. The keychain and environment providers agree on
scope, so exporting `FUNCTUALIZE_VAULT_KEY` and later unsetting it does not
strand a keychain-provisioned store.

### AC-18 — project root, not working directory

`vault put` from a subdirectory of a project and the job run from the project
root reach the same entry. Every vault surface reports the same location.

### AC-19 — `init` is not a gate

`export FUNCTUALIZE_VAULT_KEY=… && func builtin vault sync` succeeds on a
machine where `init` has never run, creating the store on first write. The same
holds for `put`.

### AC-20 — eligibility excludes what the vault cannot supply

A job whose secret is a plain function parameter rather than a config-model
field is rejected by `put` with `field_not_secret`'s sibling reason, before any
input is read, and `inspect` explains why it is ineligible.

## 16. Decisions (confirmed)

Confirmed with the maintainer before Plan. Referenced as `D1`–`D8` above.

| # | Decision |
|---|---|
| D1 | **Storage.** Add `origin`, `created_at`, `updated_at`, `key_provider`; make `annotation`, `provider`, `synced_at` nullable. Ship a one-time idempotent in-place upgrade. Filler values rejected as untruthful (§11.1). |
| D2 | **Resolution is presence-based, not origin-based.** No entry → fall through. Entry present → it is the intended value; refuse if it cannot be opened. Applies to provider entries too; ships with an ADR-016 amendment (§8.1). |
| D3 | **`remove` takes any entry and never needs the key.** Reports origin; warns only for `direct`. The draft's refusal to remove a provider entry is dropped (§9.4). |
| D4 | **Project = walk upward for `.functualize/`,** hashing the working directory only as fallback — the rule discovery already uses (§5). |
| D5 | **`keyring` stays an optional extra** (`functualize[keychain]`). Bare `init` on a stock install refuses, and the refusal teaches both routes (§9.1). |
| D6 | **One key per user, not per project.** The keychain provider is changed to match the environment provider. Free now; a migration once `init` ships (§10.2a). |
| D7 | **Key check value** written on first store write, so key state is answerable without decrypting a secret (§11.2). |
| D8 | **`init` is a preflight, never a gate.** Everything that works today without it keeps working (§6). |

### Still open, and deliberately deferred

These are named so Plan does not silently decide them:

1. Nested-model field paths and a grammar for mounted apps (§5 excludes them).
2. Whether the internal write-only `audit_log` table is retained, removed, or
   promoted through a separately specified history surface. Direct writes must
   not turn it into an implied product contract; today it has no shipped
   reader. Direct writes must at minimum stop being recorded as `"sync"`.
3. Structured provider declarations replacing annotation strings.
4. Whether an ordinary run may raise an interactive keychain prompt, and how
   the dormant source avoids putting `cryptography` on every cold boot. Both
   are architecture questions the Plan phase answers (§17).

## 17. Notes carried into Plan

Constraints discovered while auditing this spec against the live code. They do
not change the behavior above; they shape how it can be built.

1. **Eligibility validation cannot live in `_config`.** Import-linter's peer
   independence contract walls `_config` off from `_discovery`/`_engine`, and
   `_cli` may import only public API. Path validation needs the job schema; the
   store needs `_config.vault`. The seam must compose in `_app`/`app`.
2. **A universal dormant source must not import the vault eagerly.** The
   configuration module records that `_config.vault` is deliberately kept off
   the cold boot path because it pulls in `cryptography`. The source must be
   gated on a cheap existence check before anything is imported.
3. **Key resolution may prompt.** With a TTY, the interactive keychain provider
   is consulted whenever no non-interactive key is found. Making the source
   universal risks an unlock prompt on every ordinary run, which §6 does not
   contemplate.
4. **`SecretsVault` lacks the primitives.** `put` unconditionally
   `ON CONFLICT DO UPDATE`s and always records the audit action as `"sync"`;
   there is no `delete` at all, only `clear`. `--replace`, §9.5's
   no-clobber rule, and `remove` each need store-level support.
5. **The new initializer protocol is public API** and therefore requires an
   ADR, as does the §8.1 amendment. They may be the same ADR.
