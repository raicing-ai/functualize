# Research: local-vault-access

## Research question

What local-first vault experience lets a user store and use a secret through an
ordinary Functualize job without requiring a remote provider, cloud account,
custom `FunctualizeApp`, or plaintext configuration file?

## Evidence and authority

This research was refreshed after rebasing onto `origin/master` `11d77f6`; the
feature commit is `791ad30`. The evidence order is:

1. Live code is authoritative for current behavior.
2. [ADR-016](../../../contributor/adr/016-remote-source-activation.md) is the
   accepted current vault decision.
3. [Shape Intent — Local Vault CLI and Lifecycle](https://raicing-ai.atlassian.net/wiki/spaces/FUN/pages/2031617/Shape+Intent+Local+Vault+CLI+and+Lifecycle)
   is the most specific proposed design, but labels itself an active proposal,
   not an implementation specification.
4. The [FuncCloud product thesis](https://raicing-ai.atlassian.net/wiki/spaces/FUN/pages/1146881/FuncCloud+Product+Thesis+and+Control+Plane)
   and its child pages constrain product direction and boundaries.
5. The [dead-code audit](https://raicing-ai.atlassian.net/wiki/spaces/FUN/pages/3637249/Research+Codebase+Extensibility+Hygiene+Audit+2026-09-16)
   is accepted historical evidence at commit `79545ef`; every finding needs
   live-code revalidation.

Curated source notes and page provenance are in
[`confluence/`](confluence/README.md).

The required zvec-grep semantic pass could not run in this checkout: the MCP
reported no index, `mise` is unavailable, and no executable `zg` was found
under the user, root, `/opt`, `/usr`, or `/usr/local` paths. The fallback was an
exhaustive `rg` pass over `contributor/`, `docs/`, `.spec/ARCHITECTURE.md`,
`.spec/STATUS.md`, and `README.md`, combined with the full Confluence search.
No persistent index was created silently.

## Maintainer constraint: public API

A zero in-repository call count does not prove a public API is dead. External
consumers are outside the audit graph. No public API deletion, rename, or
compatibility break—including `remote_first()`, current
`functualize.app.utils` vault exports, `VaultKeyProvider`, or existing vault
commands—is authorized without explicit maintainer confirmation.

This constraint overrides any dead-code-audit recommendation that infers
deletion from missing internal callers. The audit remains useful as a
reachability question and design-smell signal.

## Product direction found in Confluence

The Confluence pages converge on these UX/DX principles:

- **CLI first:** the terminal remains the stable operational surface.
- **Local first:** first value requires no account, network, hosted control
  plane, or remote execution.
- **Ordinary jobs:** the vault extends normal discovery and layered config; it
  is not a second job or execution model.
- **Complex inside, simple outside:** users see a small set of direct verbs and
  truthful states even when encryption, provider selection, and provenance are
  complex internally.
- **Jobs stay offline:** remote-provider traffic occurs only during explicit
  `vault sync`, never boot or job execution.
- **Direct and provider-backed values remain distinct:** storage and resolution
  may be shared, but provenance, refresh, deletion, and recovery differ.
- **Smallest useful primitive first:** prove `init → put → run` before process
  injection, environment bundles, accountless sharing, or governance.

The proposed first-run journey is:

```text
func builtin vault init
func builtin vault put deploy.api_token
func deploy
```

The user should not need to understand `RemoteSource`, provider entry points,
presets, annotation URIs, or encryption backends before this works.

## Current repository behavior

### Existing strengths

- `SecretsVault` stores values in a per-project SQLite database using
  per-value AES-256-GCM and a fresh nonce per write.
- Metadata is readable without the encryption key; values are not.
- `func builtin vault sync`, `list`, `status`, `clear`, and `keygen` exist.
- `sync` is the remote-provider network path; a job run reads the local store.
- `remote_first()` activates a vault-backed chain and preserves offline work by
  warning, rather than failing, for stale provider cache entries.
- Wrong-key/decryption failures do not silently become misses.
- `Secret[str]` already marks sensitive inputs and survives discovery/cache
  into public job schemas.
- `VaultKeyProvider` is a public structural protocol with environment and
  keychain implementations.

### The first-run gap

The existing feature is a provider cache rather than a generic local vault:

- normal discovery-mode `func` construction does not select `remote_first()`;
- `remote_first()` requires a registered remote provider;
- there is no `init`, `put`, `inspect`, or `remove` command;
- the keychain provider reads a stored key but no shipped flow writes one;
- `keygen` prints a key, leaving persistence/export to the user;
- provider identity is encoded in application config string values;
- the public vault orchestration seam remains in `functualize.app.utils`; no
  `functualize.app.vault` module exists.

Therefore adding commands alone is insufficient. Ordinary app composition must
also gain a dormant local source that has no effect when there is no matching,
readable entry.

## Dead-code audit reconciliation

The detailed source note is
[`confluence/dead-code-audit.md`](confluence/dead-code-audit.md).

### Key-provider entry points are declared but not loaded

Live `rg` confirms `functualize.vault_key_providers` is declared in
`pyproject.toml`, while production calls invoke `resolve_vault_key(project_id)`
without a loaded provider list. This is an integration gap, not permission to
delete the public extension point. A local initializer and normal job reads
must use the same provider universe and ordering.

### The vault audit ledger has no shipped reader

Live `rg` finds `SecretsVault.audit_records()` consumers only in tests. Direct
local writes should not accidentally turn that internal table into an implied
product history contract. A user-facing audit/history feature needs separate
retention, privacy, and output design.

### `app.utils` already has divergent-change pressure

The public-API audit identifies unrelated responsibilities accumulated in
`app.utils`, including vault orchestration. Adding more vault lifecycle logic
there would deepen the same smell. A focused public home can be additive while
existing exports remain thin forwards; no removal follows automatically.

### The nominal `CliSource` is empty

The audit and live code agree that explicit job arguments win through command
binding, not because `CliSource` carries them. User-facing precedence should be
specified behaviorally instead of attributing it to the empty tier.

## Users and jobs to be done

| User | Job | Minimum successful experience |
| --- | --- | --- |
| Local developer | Keep one project secret out of config files and shell profiles. | Initialize once, put by canonical input path, run the normal job. |
| Job author | Mark an input sensitive without choosing storage. | Declare `Secret[str]`; the job receives `Secret[str]`, not a vault/provider object. |
| CI operator | Use the same job non-interactively. | Supply an explicit environment key and stdin/file input; no prompts or plaintext output. |
| Provider-backed user | Retain current explicit sync and offline execution. | Existing provider declarations and commands continue to work. |
| External API consumer | Continue using published Python and CLI surfaces. | Existing public names remain unless a later confirmed decision changes them. |

## Recommended first increment

The smallest coherent vertical slice is additive:

1. `func builtin vault init` creates and persists a per-project key through an
   initializer-capable key provider, preferring the OS keychain.
2. `func builtin vault put <path>` validates the path against discovered job
   schema, requires `Secret[str]`, accepts a masked prompt or explicit
   stdin/file input, and stores a direct local value.
3. `func builtin vault inspect <path>` explains eligibility, key/store state,
   provenance, freshness, and winning source without possessing plaintext.
4. `func builtin vault remove <path>` deletes one direct value with deliberate
   confirmation.
5. Normal `FunctualizeApp` config resolution consults a dormant vault source
   between explicit per-run inputs and environment/files/defaults.
6. Existing `sync`, `list`, `status`, `clear`, `keygen`, `remote_first()`,
   provider annotations, and public Python exports remain available.

Structured provider declarations, store-format replacement, and public-surface
cleanup remain later decisions. This intentionally narrows the Confluence shape
intent so the first increment does not smuggle in unconfirmed removals.

## UX decisions recommended for specification

### Canonical paths

The path comes from the same discovered schema used by CLI, MCP, and TUI input
surfaces. A typo or path that is not a `Secret[str]` fails before value input is
read. Grouped jobs, nested models, aliases, and mounted apps need one grammar;
the exact grammar should be frozen in the external contract.

### Observable precedence

```text
per-run override / explicit job argument
    → matching readable local-vault entry
    → environment
    → configuration files
    → model defaults
```

No store or no matching entry leaves prior behavior unchanged. An entry that
exists but cannot be decrypted is different from absence and must not silently
fall through.

### Safe input and output

- Interactive `put` uses a masked prompt.
- Non-TTY `put` requires explicit `--stdin` or `--file`.
- Existing values require `--replace`.
- Empty values are refused in the first increment.
- Values are UTF-8 text; arbitrary bytes are out of scope.
- No command, JSON payload, error, log, or representation returns plaintext.
- `get`, `reveal`, shell export, and child-process injection are not added.

### Key initialization

`VaultKeyProvider` is read-only today. Adding a required write method would
break structural implementations, so key creation should use a separate,
optional initialization capability. If no initializer is available, `init`
refuses and explains the environment-key route; it does not print a key by
default. Existing `keygen` remains available.

### Provenance

Direct entries and provider cache entries must be distinguishable in metadata.
At minimum the system must know canonical path, origin (`direct` or
`provider`), provider/reference where applicable, creation/update time, and
provider sync time. `sync` must not silently overwrite a direct value, and
`clear` must warn that direct values may have no upstream recovery source.

## Failure semantics to settle in the behavior contract

| Condition | Recommended behavior |
| --- | --- |
| Unknown or non-secret path | Validation failure before reading value input. |
| Non-TTY `put` without explicit input source | Usage failure; never hang. |
| Existing direct value without `--replace` | Refusal with metadata only. |
| No initializer during `init` | Refusal naming available key-source alternatives. |
| Store absent or path absent during a run | Continue down existing config sources without warning. |
| Entry exists but key is unavailable | Refuse for that field/run rather than silently select a weaker source. |
| Wrong key or corrupt ciphertext | Refuse; never fall through. |
| Stale provider cache | Preserve ADR-016: warn once and continue. |
| Provider sync partly fails | Keep successful writes, report failures, exit non-zero. |
| Direct/provider origin conflict | Never overwrite implicitly; report conflict and require an explicit choice. |
| `clear` includes direct values | Strong source-aware confirmation. |

## Explicit non-goals

- Plaintext retrieval or reveal.
- Shell/process injection.
- Environment bundles, sharing, burn links, or accounts.
- FuncCloud policy, connections, runners, or remote execution.
- Binary values.
- Searchable audit history.
- Automatic provider access during boot or job execution.
- Structured provider-registry migration.
- Store-format migration or reset.
- Removal or rename of existing public API.

## Verification thesis

The central test begins where the user begins:

1. Discover an ordinary job with a required `Secret[str]` input.
2. Initialize and put through public CLI commands.
3. Deny outbound network access.
4. Run through cold discovery and warm-cache paths.
5. Observe that the job receives the secret wrapper/value.
6. Scan stdout, stderr, logs, JSON, exceptions, database files, and SQLite
   sidecars for the exact secret bytes.
7. Verify explicit argument > vault > environment/file/default precedence.
8. Break the composition-root wire and confirm the E2E test fails.

Component/store tests remain useful, but cannot close reachability.

## Open questions for review

1. Is `Secret[str]` alone sufficient eligibility, or should persistence require
   additional explicit metadata?
2. What is the canonical path grammar for grouped jobs and nested models?
3. Should an existing-but-unreadable direct entry refuse the run (recommended)
   or warn and fall through?
4. Should keychain support be a core dependency, CLI extra, or separate
   provider package?
5. What are exact stdin newline and multiline rules?
6. Does `clear` remain the all-entry destructive verb, or should an additive
   `reset --all` be introduced while preserving `clear`?
7. Should the internal write-only audit table be retained, removed, or promoted
   through a separately specified history surface?

## Recommendation

Specify the additive `init → put → ordinary run` vertical slice, plus metadata
inspection and direct removal. Make resolution common to every
`FunctualizeApp` execution surface, preserve existing provider sync and public
APIs, and prove reachability on cold and warm discovery paths. Defer plaintext
handoff, sharing, structured-source migration, audit history, and API removal
until each has its own confirmed contract.

