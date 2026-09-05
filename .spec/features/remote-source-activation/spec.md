# Spec — Remote source activation via an encrypted local vault

Wires the remote configuration layer that ships today and resolves nothing.
`RemoteSource`, `ProviderRegistry`, `parse_annotation` and the
`functualize.remote_providers` entry-point group are all built, exported and
unit-tested; the boot path constructs none of them
(`grep -c remote src/functualize/_app/boot.py` → **0**).

This is the document the Lark proposal *Commercial: FuncCloud — Agent-Scoped
Secrets, Permissions & Audit Platform* names as
`oss-remote-source-activation.md` and declares a hard dependency on. That file
existed nowhere in git or in the wiki; this feature is it.

## Problem statement

`remote_first()` is a public preset. It is exported (`app/__init__.py:29,57`),
documented, unit-tested, and pinned by `tests/test_public_api_surface.py:49`.
Its own docstring says it leaves `config_resolution_chain=None` *"so that the
boot path can wire up RemoteSource and FileSource"* — and the boot path never
does. It therefore resolves as `classic()` with a different file pattern.

**Someone selecting `remote_first()` for AWS Secrets Manager gets local files
and environment variables, silently.** That is the failure class `AGENTS.md:82`
names: shipped, unit-tested, unreachable on the path that matters.

STATUS follow-up #16 records this and states the decision needs an ADR because
it is public API surface. This feature makes that decision: **wire it.**

### Why a vault, and not a live fetch

The obvious wiring — resolve annotations against the remote at
config-resolution time — puts the network on the run path. Two measured facts
make that the wrong default:

- `FunctualizeApp()` construction is **73.3 ms** after the entry-points work
  (STATUS #9). A live AWS round trip is 10–40× that.
- `RemoteSource` carries a **30-second timeout** (`_config/sources.py`). On a
  live path that timeout sits between the operator and every job run.

So remote values are **synced into an encrypted local store**, and jobs resolve
against the store. The network is touched when an operator asks for it, never
because a job ran. Design inspiration is Turso's secrets vault: an encrypted
local database, opened with a key supplied at connect time, with an append-only
audit log.

## User stories

- **As an operator**, `remote_first()` either resolves from the remote source I
  named or tells me why it did not — it never silently reads a local file while
  claiming to read AWS.
- **As a developer on a plane**, my jobs run against the values I last synced,
  with no network and no failure.
- **As a developer**, running a job with a stale vault warns me, rather than
  failing at my database with an authentication error four layers down.
- **As a security reviewer**, a project's secrets are not readable by a job in
  a different project I happen to have checked out.
- **As an operator**, I can see *which* remote source answered for each value,
  and when it was last synced, without ever printing the value.

## Behavior

### V1 — the boot path builds the chain

`remote_first()` resolves to `CLI → Vault → Env → Files → Defaults`. Boot
constructs the vault-backed source and inserts it, using the discovered
`ProviderRegistry` and `ResourceLocator` the preset's docstring already
promises.

A `remote_first()` app with **no** remote provider registered is an error at
construction, naming the annotations it cannot serve and the entry-point group
that would supply them. It must not degrade into `classic()` — that degradation
is the defect this feature exists to close.

### V2 — annotations are discovered from resolved config

A config value matching `provider://reference` is an annotation, not a literal.
`parse_annotation` (`_config/manifest.py:37`, **zero production callers**
today) gains its first caller: resolved config is scanned, matching values
become the `annotations` map `RemoteSource` already accepts, and the fallback
chain syntax (`aws-sm://a | aws-ssm://b`, max 5) works as specified.

This also discharges ADR-008's Problem 1 — *"a config file gives no sign that a
job needs a credential."* An annotation names a credential's **location**
without carrying its **value**, so the config file becomes discoverable without
becoming a leak.

### V3 — the vault is an encrypted local store

One SQLite database per project, at
`$XDG_DATA_HOME/functualize/vaults/<project_id>/vault.db`, mirroring the
per-project layout the discovery cache already uses
(`~/.cache/functualize/<project_id>/cache.json`).

Each secret **value** is encrypted with AES-256-GCM under a per-entry nonce.
Names and metadata stay queryable, so `vault list` works and reports what is
stored without the key being present — the same split Turso makes, where
metadata is queryable and the value is never returned to a caller.

An append-only `audit_log` table records each access: timestamp, key, the
provider that supplied it, and the outcome. It never records the value.

### V4 — the key comes from a provider seam, not a hardcoded source

Where the encryption key comes from is a **seam**, not a decision baked into
the vault. A `VaultKeyProvider` protocol is declared in a public folder, with
an entry-point group so third parties — and, later, FuncCloud — register their
own without a core change.

Two implementations ship:

- **Environment** (`FUNCTUALIZE_VAULT_KEY`) — non-interactive, always
  available, and the only one that works in CI, Lambda and containers. This is
  consistent with `RemoteProvider`'s existing mandate that *"Credentials MUST
  be resolved from environment variables only."*
- **Keychain** — the first *interactive* provider, using the OS keyring.

Resolution order: the environment variable **wins when set**, so an automated
run is deterministic and never blocks on a prompt. Interactive providers are
consulted only when it is unset.

Absent a key, the vault does not open and no plaintext fallback exists.

### V5 — sync is explicit, staleness is loud

`func builtin vault sync` fetches every declared annotation from its provider
and writes it to the vault. Nothing else contacts the network.

The vault records `synced_at` per entry. When the vault is older than a
configured `[vault] max_age`, every job run prints a warning naming the age and
the sync command — and **still runs**, so offline work stays possible.

### V6 — a vault miss falls through, loudly

When a declared annotation has no vault entry, resolution continues to the next
source in the chain — and warns, every run, naming:

- the key,
- the annotation it was declared as,
- **which source actually answered**,
- the command that would fix it.

The value itself is never printed. `is_secret_field` (`_types/redaction.py`)
stays the single answer to "is this a secret" per ADR-008, and `MASK = "•••"`
stays canonical. This feature adds no second opinion on secretness.

Falling through is a deliberate escape hatch. Falling through *silently* is the
original defect, and does not happen.

### V7 — providers ship as plugins

The vault and the seams are core. The provider implementations are not. Two
plugins ship with this feature:

- `functualize-aws` — `aws-sm` (Secrets Manager) and `aws-ssm` (SSM Parameter
  Store, including `SecureString`).
- `functualize-bitwarden` — Bitwarden Secrets Manager.

Both register through `functualize.remote_providers`, the group that already
exists and is currently empty.

## Acceptance criteria

Executable. Counts are from running each command against `537efe7` at authoring
time.

| # | Criterion | Authoring-time state |
|---|---|---|
| A1 | `grep -c "remote" src/functualize/_app/boot.py` ≥ 1 | **0** |
| A2 | `parse_annotation` has ≥ 1 production caller outside `_config/manifest.py` | **0** |
| A3 | A test asserts `remote_first()` with no registered provider raises at construction, naming the entry-point group | resolves as `classic()`, silently |
| A4 | A test writes a value via a fake provider, syncs, and asserts the on-disk bytes do **not** contain the plaintext | no vault exists |
| A5 | A test asserts a vault miss returns the next source's value **and** emits a warning naming the annotation | no vault exists |
| A6 | A test asserts a stale vault warns and the job still succeeds | — |
| A7 | A test asserts project A's vault cannot serve project B's key | — |
| A8 | `func builtin vault list` renders names and `synced_at` with **no** plaintext value, and passes the ADR-008 masking assertions | — |
| A9 | An integration test resolves a secret from Secrets Manager and a parameter from SSM Parameter Store against a local Floci container, including a `SecureString` and a fallback chain | proven by hand at authoring time; not yet a test |
| A10 | `uv run pytest`, `ruff check`, `ruff format --check`, `mypy src/`, `lint-imports` all green | — |

## Out of scope

- **The FuncCloud policy layer** — prefix-scoped grants, `use` vs `read`
  grants, approval and escrow. Specified in the Lark proposal and its
  *07 — Policy Model Specification*; this feature only provides the seams it
  plugs into.
- **Key rotation and re-encryption.** The vault is a cache of values that live
  authoritatively in the remote; the recovery path is `vault sync` with a new
  key, not an in-place rewrap. A rotation command is a follow-up.
- **Write-back.** Values move remote → vault only. Nothing in this feature
  writes a secret *to* AWS or Bitwarden.
- **Injecting secrets into child processes and scrubbing them from output.**
  Turso's vault does this; functualize's equivalent is the existing `Secret[T]`
  type and value-based redaction, which already covers Shell and Stdout.
- **Other clouds.** GCP, Azure and Vault providers are the same seam and are
  follow-ups, not tasks here.

## Note on the commercial boundary

The Lark proposal states: *"a closed-source plugin (`functualize-cloud`) plus a
hosted control plane. Nothing in this proposal changes the license of the core
repo; the commercial boundary is the existing entry-point plugin seam."*

The maintainer's direction for this feature is that **FuncCloud will later be
integrated into core by default**, which places the commercial boundary inside
the open-source repository rather than at the plugin seam. That is a licensing
decision, not a packaging one, and the two documents currently disagree.

Recorded here so the divergence is explicit. This feature does not depend on
its resolution: every seam it adds is registrable from outside core, so either
answer remains reachable. The decision belongs in the ADR this feature
requires.
