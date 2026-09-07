# ADR-016: Activating the Remote Config Layer, via an Encrypted Local Vault

**Status**: accepted
**Date**: 2026-09-05
**Deciders**: Hakim, with the spec-driven workflow. Specification artifacts live in
`.spec/features/remote-source-activation/` and are cleared at merge, as that workflow
requires; recover them from the pull request ref if needed.

## Context

Functualize ships a complete remote configuration layer that resolves nothing.

`RemoteSource` (`_config/sources.py:246`), `ProviderRegistry` with
`register_remote_provider` / `get_remote_provider` / `list_remote_providers`
(`_config/registry.py:69,117,147`), the `functualize.remote_providers`
entry-point group (`:193`), and `manifest.parse_annotation` for
`provider://reference` (`_config/manifest.py:37`) are all built, exported and
unit-tested.

None of it is reachable. `grep -c remote src/functualize/_app/boot.py` returns
**0**, and `parse_annotation` has **zero** production callers.

The user-visible consequence is `remote_first()`. It is a public preset —
exported at `app/__init__.py:29,57`, documented, and pinned by
`tests/test_public_api_surface.py:49`. Its own docstring says it leaves
`config_resolution_chain=None` *"so that the boot path can wire up RemoteSource
and FileSource"*. The boot path never does, so `None` falls through to the
classic chain builder.

**Someone selecting `remote_first()` for AWS Secrets Manager or Vault gets
local files and environment variables, silently.** Not an error, not a warning
— the wrong source, confidently.

This went unnoticed because `test_app_presets_properties.py:124` asserts that
`remote_first()` returns `config_resolution_chain=None`. It tests the stub, and
it tests it faithfully. Shipped, unit-tested, unreachable: the failure class
`AGENTS.md:82` names, and STATUS follow-up #16.

That follow-up states the resolution needs an ADR, because the preset is public
API. This is that ADR.

### What the audit established first

Before deciding, the layer was proven correct rather than assumed broken. Two
~10-line providers were written against real AWS services in a local emulator —
nothing written into `src/` — and resolved:

```
db_password  -> 's3cret-from-secrets-manager'    # Secrets Manager
api_url      -> 'https://api.internal'           # SSM Parameter Store
api_token    -> 'tok-abc123'                     # SSM SecureString, decrypted
fallback     -> 'https://api.internal'           # aws-sm://missing | aws-ssm://... fell through
```

Annotations parse, fallback chains fall back, `SecureString` decrypts, and the
`RemoteProvider` protocol needs no widening. **The gap is boot wiring and
nothing else.**

## Decision

Wire it. And make the read path a local encrypted vault rather than a live
fetch.

### 1. `remote_first()` is activated, not removed

The alternative was deleting the preset and the machinery behind it. Rejected:
the machinery is correct and proven, the pieces are individually sound, and the
demand is real — the whole point of a job runner reaching production is that
its credentials do not live in the repository.

`remote_first()` resolves to `CLI → Vault → Env → Files → Defaults`.

An app selecting `remote_first()` with **no** registered remote provider is an
error at construction, naming the entry-point group. It must not degrade to
`classic()`. That degradation is the defect; a quieter version of it is not a
fix.

### 2. The read path is a local vault, not a live fetch

The obvious wiring resolves annotations against the remote at
config-resolution time. Rejected on two measured facts:

- `FunctualizeApp()` construction is **73.3 ms** (STATUS #9, after the
  entry-points snapshot work). A live AWS round trip is 10–40× that, on every
  invocation.
- `RemoteSource` carries a **30-second timeout**. On a live path that timeout
  sits between the operator and every job run — including runs of jobs that
  use no secret at all.

So remote values are **synced into an encrypted local store**, and jobs resolve
against the store. The network is touched when an operator asks for it, never
because a job ran. A developer offline keeps working with what they last
synced.

The design is Turso's secrets vault: an encrypted local database opened with a
key supplied at connect time, with queryable metadata, an unreadable value, and
an append-only audit log.

### 3. The vault is in core; the providers are plugins

`cryptography` becomes a core dependency. This was weighed against shipping the
vault as a plugin, and core won: `remote_first()` is core public API, and a
public preset whose behaviour depends on whether an optional package happens to
be installed is the same class of surprise this ADR exists to remove.

The cost is real and accepted: the standalone binary across seven build targets
grows. It is measured at the feature's checkpoint rather than estimated.

Provider implementations are **not** in core. They arrive through
`functualize.remote_providers`, the group that already exists and is currently
empty. Two ship with this work — `functualize-aws` (Secrets Manager and SSM
Parameter Store) and `functualize-bitwarden` (Bitwarden Secrets Manager). Core
must not import either; `grep -rn "boto3" src/functualize/` stays **0**.

### 4. Storage: stdlib SQLite, per-value AES-256-GCM, one vault per project

`sqlite3` is stdlib, handles concurrent readers in WAL mode — which is the real
access pattern, since `builtin parallel` runs several jobs at once — and
matches the migration shape `functualize-state-sqlite` already established.

Each **value** is encrypted under a fresh per-entry nonce. `key`, `annotation`,
`provider` and `synced_at` stay cleartext **on purpose**, so `vault list`
reports what is stored and how fresh it is without the key being present. None
of them is the secret. This is Turso's split between queryable metadata and an
unreadable value.

One vault per project, at
`$XDG_DATA_HOME/functualize/vaults/<project_id>/vault.db`, reusing
`compute_project_id` (`_primitives/locator.py:527`) — the same identity the
discovery cache already keys on. A single machine-wide vault was rejected: a
repository you cloned to look at would otherwise run with access to every
secret you have ever synced.

### 5. The encryption key comes from a seam, not a source

Where the key comes from is a `VaultKeyProvider` protocol in `plugin/`, with
its own entry-point group. Two implementations ship:

- **Environment** (`FUNCTUALIZE_VAULT_KEY`) — non-interactive, and the only
  thing that works in CI, Lambda and containers. Consistent with
  `RemoteProvider`'s existing mandate that *"Credentials MUST be resolved from
  environment variables only."*
- **Keychain** — the first *interactive* implementation.

The keychain is one implementation of the seam, **not** the seam itself. KMS,
1Password and a future FuncCloud provider are the same protocol with no core
change. Hardcoding "keychain, with an env fallback" would have made the common
case a special case.

**Ordering is part of the contract**: non-interactive providers first, and
interactive ones only when no key was found and a TTY exists. Reversed, an
unattended Lambda run hangs on a keychain prompt.

With no key, the vault does not open. There is no plaintext fallback.

### 6. Sync is explicit; staleness is loud

`func builtin vault sync` is the only thing that contacts the network. The
vault records `synced_at`; a vault older than `[vault] max_age` (default `24h`)
makes every run warn, and **still run**.

Auto-syncing when stale was rejected: it puts the network back on the run path
exactly when nobody planned for it, and turns a flight or an expired AWS
session into a failed job. Warning-only was chosen over failing because
offline work is a feature, not an edge case.

Silence was rejected outright. The rotated-password case — sync on Monday,
someone rotates on Tuesday — otherwise surfaces as an authentication error from
*your database*, four layers away from its cause.

### 7. A vault miss falls through, loudly

When a declared annotation has no vault entry, resolution continues to the next
source — and warns, every run, naming the key, the annotation it was declared
as, **which source actually answered**, and the command that fixes it.

Hard-failing was considered and rejected: it makes a first run after adding an
annotation impossible, and it removes the escape hatch that lets someone work
while a provider is down.

The distinction that matters: **falling through is fine, falling through
silently is the original bug**. A warning that only says "not in vault" is not
enough — the operator's question is *what am I running with instead*, so the
answering source is named.

The value is never printed. `is_secret_field` (`_types/redaction.py`) stays the
single answer to "is this a secret" and `MASK = "•••"` stays canonical, per
ADR-008. This feature adds no second opinion; ADR-008's own docstring explains
why two would be a leak.

### 8. Annotations make config files discoverable without making them leak

ADR-008 recorded that a config file *"gives no sign that a job needs a
credential"*, and noted the good property underneath: a config file has no
vocabulary for naming a secret's location, so it cannot leak one.

The annotation syntax resolves that tension rather than trading it away. An
annotation names a credential's **location**; it never carries its **value**.
`parse_annotation` gains its first production caller, and ADR-008's Problem 1
is discharged.

## Consequences

- `remote_first()` stops being a lie. An operator who selects it gets the
  remote source they named, or an error — never a local file wearing its label.
- The network leaves the run path entirely. Boot stays at ~73 ms and the
  30-second timeout is only reachable from `vault sync`.
- Core gains `cryptography` and the standalone binary grows across seven
  targets. Measured, not estimated, at the feature checkpoint.
- Secrets are isolated per project. A shared credential is stored once per
  project that uses it, which is duplication accepted in exchange for blast
  radius.
- A stale vault is now a visible warning rather than a confusing downstream
  auth failure.
- `functualize.remote_providers`, empty since it was created, finally has
  entries — and the seam FuncCloud is designed to plug into is exercised by two
  real implementations before any commercial work depends on it.

### The commercial boundary is not settled here

The FuncCloud proposal states: *"a closed-source plugin (`functualize-cloud`)
plus a hosted control plane. Nothing in this proposal changes the license of the
core repo; the commercial boundary is the existing entry-point plugin seam."*

The maintainer's direction is that **FuncCloud will later be integrated into
core by default**, which places that boundary inside the open-source repository
instead. That is a licensing decision, not a packaging one, and the two
positions are currently in conflict.

Recorded, deliberately unresolved. Nothing in this ADR depends on the answer:
every seam it adds is registrable from outside core, so either outcome stays
reachable. It is called out so the next person to read both documents does not
have to discover the disagreement themselves.

### A dangling reference, now resolved

The FuncCloud proposal declares a hard dependency on
`oss-remote-source-activation.md`. No such file existed in git or in the wiki.
`.spec/features/remote-source-activation/` is that document; its durable half
should be migrated under that name at merge so the dependency resolves rather
than dangling — the same failure the `func watch` deferral hit when
`persistent-process.md` disappeared (STATUS, *Deferred*).

## Alternatives rejected

| Alternative | Why not |
|---|---|
| Delete `remote_first()` and the machinery | The machinery is correct and proven against real services; the demand is real. Deleting would have been the cheap answer to a defect that is one function call wide. |
| Live remote fetch at resolution time | Puts a 30-second timeout and a network round trip on every run, against a 73 ms boot — including runs that use no secret. |
| libsql/Turso encrypted database | Matches the inspiration most closely and encrypts metadata too, but adds a heavier, less common dependency, and makes `vault list` impossible without the key. |
| Single encrypted file, no database | Simplest, but no audit log and no concurrency story — and `builtin parallel` means concurrent readers are normal. |
| Vault as an optional plugin | A core public preset whose behaviour depends on an optional install is the same surprise this ADR removes. |
| Keychain with an env fallback, hardcoded | Makes the common case (CI, Lambda, containers) the fallback path, and forecloses KMS, 1Password and FuncCloud without a core change. |
| One machine-wide vault | A cloned repository would run with access to every secret ever synced. |
| Hard-fail on a vault miss | Makes the first run after adding an annotation impossible and removes the escape hatch during a provider outage. |
| Silent fall-through on a miss | This is the original defect, relocated one layer down. |
