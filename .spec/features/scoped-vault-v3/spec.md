# Scoped vault v3 — behavior

## Authority and problem

Shape intent: [SD/12779576, version 3](https://raicing-ai.atlassian.net/wiki/spaces/SD/pages/12779576), Authority **Approved**, read 2026-10-14. This feature implements the approved subject-address and environment amendment to the scoped local vault. The current three-part identity cannot distinguish `prod` from `staging`, and a group target limited to declared command groups cannot name a Rise subject address.

The vault remains one store per project. The active Functualize environment selects entries; there is no vault-only environment flag or second vault.

## User stories

- As an operator, I can store a secret for a secret-marked group option, job config field, or subject config field using explicit scope, target, and field, and know which environment owns it.
- As an operator, I can inspect the exact entry a subject address or job would use, including ancestor and shared fallback, without revealing secret bytes.
- As an operator, I can sync declarations for the active environment without contacting providers for other environments.
- As a job author, I can rely on the existing source precedence and offline run behavior for secret fields.

## Behavior

1. An entry is identified by `(scope, target, field, environment)`. Scope is `group` or `job`; environment is either a case-folded active environment name or absent for a shared entry. `FUNCTUALIZE_ENV`, then `ENVIRONMENT`, then `ENV` selects the environment; absent selection defaults to `DEV`. `base` addresses shared entries. Storage for shared entries retains the existing three-part spelling and associated data, so existing v2 ciphertext remains readable. Environment entries use a four-part spelling. Dots in targets are never parsed as field or environment separators.
2. Direct `put`, `inspect`, and `remove` use exactly one of `--group TARGET` or `--job TARGET`, plus `--field FIELD`. A job target is its full, registered, dot-separated command path, including every parent group and the job leaf. For example, `func deploy infra app` uses `--job deploy.infra.app --field api_token` for a secret-marked config field on `app`; `--job app` does not mean that nested job. The target is the canonical registered name, so normalized command segments use hyphens where applicable. A subject address may be a group target. Eligible fields are secret-marked group options, job config fields, and subject config fields. An ordinary job function parameter is not eligible. Validation happens before a direct `put` accepts a value. Existing recovery semantics for removing an orphaned target remain available.
3. `put` writes only the active-environment entry. `remove` deletes only that exact identity, not an ancestor or shared fallback. `inspect` reports the winning exact identity and whether it is shared. `put`, `remove`, `inspect`, and `list` report the active environment and whether it was selected or defaulted. `list` identifies each entry's scope, target, field, environment, origin, and freshness.
4. For a group target, lookup tries the full address and then each dotted ancestor, first within the active environment and then within shared entries. A plain group has a single target in each tier. Job lookup keeps its exact target and scope. A missing entry falls through according to normal field precedence. A present but unreadable entry refuses resolution and never falls through to another entry or source.
5. Secret-marked group options, job config fields, and subject config fields resolve in this order: runtime override, explicit command-line value, vault, environment variable, config file, default. Ordinary function parameters remain invocation inputs. Runs use the local vault; only `vault sync` contacts remote providers.
6. `[[vault_secret]]` blocks require exactly one of `group` or `job`, `field`, and `source`. A declaration in `config.base.*` or an unslotted config file is shared; one in `config.<env>.*` belongs to that environment. Duplicate identities are rejected within an environment. `sync` processes shared and active-overlay declarations only and does not contact other overlays. Direct and provider-backed entries cannot silently replace one another. Inline provider annotations in ordinary config values remain invalid legacy syntax.
7. `list`, `inspect`, and error output never contain secret bytes, including when a key is missing or wrong. Existing old flat-key store refusal remains non-mutating and points to `vault clear` for recovery.

## Acceptance criteria

- With the same scope, target, and field, `prod`, `staging`, and shared entries remain distinct. A write with no selected environment lands in `dev` and reports the default.
- A `prod.apps.web` group lookup checks `prod.apps.web`, then `prod.apps`, then `prod` in `prod` before checking those targets in shared; it never reads a `staging` entry. `inspect` identifies the exact winner. `remove` under `prod` leaves shared and ancestor entries intact.
- A v2 shared entry decrypts without rewriting; a present but unreadable nearer entry stops resolution.
- `config.prod.*` and `config.staging.*` may declare the same scope, target, and field; a prod sync contacts only shared and prod sources and detects duplicates or origin conflicts in those identities.
- Through a canonical operation job, a secret-marked subject field resolves for the subject address used to invoke it. Group and job entries with otherwise identical names remain separate. Explicit CLI input outranks vault, while vault outranks environment input for both group and config fields.
- Given `JOB_GROUP = "deploy.infra"` and a job function `app` with a secret-marked `api_token` config field, `func deploy infra app` resolves the entry named by `--job deploy.infra.app --field api_token`. A `--group deploy.infra --field api_token` entry remains a different identity and cannot substitute for that job field.
- CLI and public API tests cover metadata redaction and prove jobs do not contact a provider. Documentation and the Unreleased changelog describe the behavior.

## Boundaries

In scope: local vault entry handling in `put`, `inspect`, `remove`, `list`, `sync`, `status`, `init`, and `clear` where affected; group, job, and subject resolution; corresponding documentation. Out of scope: share/redeem, FuncCloud delivery, plaintext reveal/export, old-format migration, a vault-specific environment flag, separate vaults per environment, and Rise's mapping from its environment declaration to Functualize's active environment name.
