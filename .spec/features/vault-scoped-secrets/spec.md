# Scoped vault secrets and group resolution

## Authority and purpose

This specification implements the approved [Shape Intent — func builtin vault: Scoped Secrets and Resolution](https://raicing-ai.atlassian.net/wiki/spaces/SD/pages/12779576), version 2, `Authority = Approved` on 2026-10-04. Its originating report is FOSS-32. The goal is to let an operator identify a vault secret by **scope, command target, and field**, and to make the vault outrank the environment for both group options and job config fields.

This document specifies observable behavior. Architecture, files to edit, storage schema, and work sequencing belong in the implementation plan.

## Scope

The user-visible surfaces in scope are `func builtin vault put`, `inspect`, `remove`, `list`, and `sync`; `status`, `init`, and `clear` where their output or handling of the new entry identity changes; group and job config resolution; and the corresponding documentation. The same behavior must be available through the delivery-neutral app API used by the CLI.

The vault targets secret-marked **group options** and secret-marked **job config fields**. Ordinary job function parameters remain invocation inputs and cannot be vault targets. Share/redeem, FuncCloud delivery, plaintext reveal/export commands, and migration of the old vault format are outside this change.

## Terms and identity

A vault identity is the tuple `(scope, target, field)`:

| Component | Meaning | Example |
| --- | --- | --- |
| `scope` | Exactly `group` or `job` | `group` |
| `target` | The discovered canonical command path | `deploy.service` |
| `field` | One declared field on that target | `iam_key` |

Dots within `target` denote command/subcommand hierarchy. The field is always supplied separately. Scope is part of identity: `(group, deploy, token)` and `(job, deploy, token)` cannot be stored as the same entry even if a programmatic registry can expose both targets. An inherited group option retains the identity of the group that declared it: a `deploy` option used by `deploy.web.run` remains `(group, deploy, field)`; an overriding option declared by `deploy.web` uses `(group, deploy.web, field)`.

All entry producers and consumers—direct write, provider sync, runtime read, inspection, removal, listing, and metadata reporting—must agree on this identity. No route may flatten group and job entries to a common `section.field` key.

## Direct command behavior

`put`, `inspect`, and `remove` require `--field <name>` and exactly one of `--group <command-path>` or `--job <command-path>`. The positional `<job>.<field>` form is rejected; it has no compatibility alias.

```console
func builtin vault put --group deploy --field token
func builtin vault put --job deploy.service --field iam_key
func builtin vault inspect --group deploy --field token
func builtin vault remove --job deploy.service --field iam_key
```

The target must exist in discovery, the field must belong to the target's group options or job config model as selected by `scope`, and the field must be classified secret by the existing secret-field rule (`Secret[...]` or the supported explicit marker). Validation happens before `put` prompts or reads `--stdin` / `--file`. A typo, non-secret field, or function parameter produces a specific non-secret-bearing error. Normal input methods and deliberate same-origin replacement remain available.

`list` and `inspect` report scope, target, field, origin, and relevant freshness/readability metadata. They never reveal the stored value. A direct entry and a provider entry at the same identity cannot silently replace one another; an explicit removal is needed to change origin. Removing a direct entry retains the warning that it has no upstream copy. Removing an entry and clearing a project vault remain possible without the encryption key.

## Provider declarations and sync

Provider-backed secrets are declared in config files as explicit blocks:

```toml
[[vault_secret]]
group = "deploy"
field = "token"
source = "aws-sm://prod/deploy-token"

[[vault_secret]]
job = "deploy.service"
field = "iam_key"
source = "aws-sm://prod/deploy-service-iam-key"
```

Each block requires exactly one of `group` or `job`, plus `field` and `source`. Sync validates target existence, field ownership, secret eligibility, and duplicate identities. A malformed or ambiguous declaration receives a clear error that names its declaration location and identity without printing a fetched value. If two declarations claim the same identity, sync refuses the conflict instead of letting file order choose.

`source` names a provider location, never a literal secret. Provider plugins continue to interpret their own references. Only `vault sync` contacts a remote provider; job execution uses the local vault and remains network-independent. The origin and partial-failure behavior of sync remain visible without exposing values.

The old inline `provider://reference` annotation in an ordinary config field no longer declares a vault source. When it appears in a secret-marked field as legacy vault syntax, configuration fails with an instruction to use `[[vault_secret]]`; it must not become the job's literal credential. Ordinary URL strings in non-secret fields remain ordinary application data. Literal values for secret config fields remain supported through their normal config sections.

## Resolution and failure behavior

For both group options and job config fields, the first present value in this order wins:

```text
runtime override > explicit command-line value > vault > environment > config file > model default
```

An explicit group flag or job config CLI value wins over a stored vault value. A readable vault value wins over an environment value, including the group's `GROUP__FIELD` environment spelling. A secret marker does not force vault use: CLI, environment, config file, and runtime override remain valid sources. Function parameters continue to bind per invocation outside this config chain.

An absent vault entry falls through to lower sources. A provider declaration that has not been synced retains the existing warning about the absent entry and names the source that actually supplied the value. A stored entry that cannot be opened refuses the run instead of falling through to a different secret. The entry's identity and recovery action may be reported; its value may not.

No old vault entries are migrated. A store with the old identity format must be recognized and refused with a clear instruction to run `func builtin vault clear`; it is not silently interpreted, deleted, or treated as empty. The operator will clear the existing local vault before using the new format. `clear` must remain usable without a vault key.

## Documentation and compatibility

Documentation and command help replace the positional `put`/`inspect`/`remove` examples and inline provider-annotation instructions with the scoped flags and `[[vault_secret]]` blocks. The group-options precedence table gains the vault rung and matches the actual resolver. Examples distinguish group `deploy` / field `token` from job `deploy.token` / field `token`. The removal of old syntax is intentional and documented as a breaking change; no alias or data migration is supplied.

The accepted ADRs on remote activation and vault access remain authoritative for offline execution, missing-versus-unreadable behavior, freshness, key handling, and origin conflicts. This change revises the old provider-annotation and flat-key contract in ADR-016, and the job-only positional interface in the current guide. The implementation plan must identify the durable ADR update needed before merge. ADR-008's single secret-classification rule and ADR-009's group secret masking and CLI/app parity remain in force.

## Acceptance scenarios

1. A project declares a secret `token` on group `deploy` and a secret `iam_key` on job `deploy.token`. Direct writes, inspection, listing, runtime reads, and removal address each without treating the final command segment as a field. The storage identity itself also distinguishes `group` from `job` when target and field text coincide.
2. A nested job uses a token inherited from group `deploy`; its read uses the declaring group's entry. A nearer group's override, if declared, uses that nearer group's entry.
3. For both a group secret and a job config secret, an explicit command-line value beats vault, and a readable vault entry beats environment and config-file values. With no vault entry, the existing lower-source behavior applies.
4. A separate secret-marked function parameter can still be passed at invocation; `vault put --job ... --field ...` rejects it as an ineligible vault target before reading a value.
5. `put`, `inspect`, and `remove` reject a missing scope, both scopes, a missing field, and the old positional form. A typo or non-secret field is rejected before a prompted/piped value is read.
6. A fake registered provider syncs one `[[vault_secret]]` group entry and one job entry. Job runs use those values with provider networking disabled. Duplicate declarations and direct/provider origin conflicts fail clearly.
7. A legacy inline provider annotation on a secret field and an old-format vault each produce a migration/clear instruction without exposing or deleting secret values. An ordinary non-secret URL is unaffected.
8. Metadata, help, errors, and documentation show the new scope and field vocabulary and never print secret bytes.

These scenarios are acceptance criteria, not claims of current passing behavior. The implementation plan will name the precise test commands and their required evidence.
