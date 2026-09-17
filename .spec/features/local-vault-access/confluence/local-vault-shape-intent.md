# Synced source note: Local Vault CLI and Lifecycle

Source: [Shape Intent — Local Vault CLI and Lifecycle](https://raicing-ai.atlassian.net/wiki/spaces/FUN/pages/2031617/Shape+Intent+Local+Vault+CLI+and+Lifecycle)  
Page ID: `2031617`  
Retrieved: 2026-09-17  
Source version: 2, modified 2026-09-15  
Source authority: **Proposal — active discussion; not an implementation specification**

This is a faithful working synopsis with the command and configuration snippets
preserved. Consult the linked page for the canonical text.

## Intent

Ordinary discovery-mode `func` should support a safe local secret lifecycle
without a custom `FunctualizeApp`, cloud account, or plaintext config file:

```bash
func builtin vault init
func builtin vault put deploy.api_token
func deploy
```

The proposed vault is a per-project encrypted local configuration store. It is
not a FuncCloud vault, target registry, connection manager, runner selector, or
network proxy.

## Decisions recorded by the proposal

- Keep vault administration under `func builtin vault`; top-level names remain
  available to discovered jobs.
- Make a clean pre-1.0 break: remove `remote_first()`, provider-URI annotation
  strings, the current vault cache format, and the current vault command/docs
  rather than carry aliases or migrations.
- Give generic `func` a dormant local-vault source between explicit job CLI
  values and environment/files. With no store, usable key, or matching entry,
  generic resolution behaves as it did before. A matching vault entry wins over
  environment/files; an explicit job argument still wins over the vault.
- A job run never contacts a remote secret provider. Only an explicit
  `func builtin vault sync` may perform provider network access.
- Direct local values and provider-cached values share encryption and
  resolution, but retain distinct provenance, refresh, removal, and reset
  semantics.

## Proposed command family

| Command | Intended experience |
| --- | --- |
| `func builtin vault init` | Establish the local encryption key, preferring an OS keychain. CI selects a non-interactive key source explicitly. |
| `status`, `list`, `inspect <path>` | Show store/key availability, provenance, freshness, and missing declared inputs; never show plaintext. |
| `put <path>` | Accept a masked prompt, stdin, or file for one validated schema-eligible path. |
| `remove <path>` | Remove one local value with a source-aware warning. |
| `sync [--dry-run] [--json]` | Reconcile structured provider declarations. Retain partial success; selected failures produce a non-zero exit and structured reasons. |
| `reset --all` | Delete this project's store after clearly separating direct values from provider cache. |

The proposal explicitly excludes `get`, `reveal`, shell export, and process
injection from the first surface because each places plaintext in a terminal,
log, shell history, environment, or child process and requires a separate
security contract.

## Source identity

Three concepts stay separate:

1. Schema metadata—normally `Secret[...]` or explicit eligibility—controls
   whether `vault put` may write a path.
2. A direct local value is keyed only by canonical config path, such as
   `deploy.api_token`; it needs no TOML declaration.
3. An external source is declared in a reserved structured registry rather
   than encoded as a string value.

Proposed external-source syntax:

```toml
[functualize.sources."deploy.api_token"]
provider = "aws-sm"
ref = "platform/production/api-token"
```

A URL in normal application configuration always remains application data; it
is never reclassified because it resembles a URI. The resolver supplies a
normal `Secret[str]` to the job, not a provider reference object. The top-level
`functualize` namespace is reserved, and every source path is validated against
the discovered schema.

## Boundary and experiment

The local store belongs to its operator. FuncCloud delivery to a runner and
FuncCloud-hosted executor values are separate control-plane mechanisms and must
not assume a developer's project vault.

The proposed first experiment is:

1. Discover an ordinary job with one eligible `Secret[str]` input.
2. Initialize the vault and put a value at that job's canonical path.
3. Run the job with outbound network denied.
4. Prove the job receives the value while all command output from `status`,
   `list`, `inspect`, and execution contains no secret bytes.

Open questions retained by the source are the exact eligibility metadata,
desktop/CI/runner key-provider UX, final preset or option naming, provider
plugin contracts, and `func --app` parity.

