# Scoped vault v3 — external contracts

Authority: [SD/12779576, version 3](https://raicing-ai.atlassian.net/wiki/spaces/SD/pages/12779576), Authority **Approved**, read 2026-10-14. The subject-address capability required by the Rise foundation is included here.

## CLI

```text
func builtin vault put --group TARGET --field FIELD
func builtin vault put --job TARGET --field FIELD
func builtin vault inspect --group TARGET --field FIELD
func builtin vault remove --group TARGET --field FIELD
func builtin vault list
func builtin vault sync
```

`TARGET` for `--group` accepts a command group or subject address, with dots preserved. The active process environment applies to every command, for example `FUNCTUALIZE_ENV=prod func builtin vault put --group prod.apps.web --field tls_crt`. `FUNCTUALIZE_ENV=base` selects the shared slot. There is no vault environment flag. `inspect` and `list` show metadata and exact resolved identity without values; `remove` acts on the exact active-environment identity.

## Config declaration

```toml
# config.prod.toml
[[vault_secret]]
group = "prod.apps.web"
field = "tls_crt"
source = "provider://reference"
```

`group` and `job` are mutually exclusive. `field` and `source` are required. A `config.base.*` or unslotted declaration is shared; `config.<env>.*` has that file's environment. An `environment` key in a declaration is unsupported. Sync processes only shared and active-overlay declarations.

## Observable identity and resolution

The conceptual entry identity is `(scope, target, field, environment)`; `environment` is absent for shared entries. Shared entries retain the v2 three-part encoded spelling and ciphertext authentication. Environment entries add a fourth part. The encoding is a storage detail, not a user-supplied path grammar.

For a group address `a.b.c` and active environment `prod`, candidate order is `prod/a.b.c`, `prod/a.b`, `prod/a`, then `shared/a.b.c`, `shared/a.b`, `shared/a`, always with the same group scope and field. A job uses its exact target in `prod`, then shared. A present entry that cannot be read terminates lookup with an error. Field-source order remains runtime override, explicit CLI value, vault, environment, config file, default.

## Public vault API

The existing `functualize.app.vault` operations (`resolve_vault_identity`, `vault_put`, `vault_remove`, and `vault_inspect`) continue to validate and operate on a scoped identity. Their reports must expose the environment context and, for inspection, the exact identity selected by lookup. Any signature additions required for subject-field resolution are decided in Plan, after mapping existing public callers; no independent environment selector is added to the API.

## Privacy and compatibility

Metadata output and errors never include plaintext. Stored v2 shared entries remain readable as-is. Old flat-key stores remain refused without mutation, with the existing `vault clear` recovery instruction. Direct and provider-backed entries cannot silently replace one another.
