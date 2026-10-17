# Scoped vault v3 — behavior

## Authority and problem

Shape intent: [SD/12779576](https://raicing-ai.atlassian.net/wiki/spaces/SD/pages/12779576), page version **5**, read 2026-10-16. Its v4 composed-target amendment has `Authority: Approved`; the maintainer confirmed this spec on the issue at 2026-10-16 11:59 UTC. The page's Status and Last reviewed prose still describe the preceding proposal; the Authority field and explicit confirmation establish the gate. This feature implements the subject-address and environment amendment to the scoped local vault, plus v4's target grammar. The current three-part identity cannot distinguish `prod` from `staging`, and a group target limited to declared command groups cannot name a Rise subject address.

The vault remains one store per project. The active Functualize environment selects entries; there is no vault-only environment flag or second vault.

## User stories

- As an operator, I can store a secret for a secret-marked group option, job config field, or subject config field by naming the group with `--group`, the job by its own name with `--job`, and the field with `--field`, and know which environment owns it.
- As an operator, I can inspect the exact entry a subject address or job would use, including ancestor and shared fallback, without revealing secret bytes.
- As an operator, I can sync declarations for the active environment without contacting providers for other environments.
- As a job author, I can rely on the existing source precedence and offline run behavior for secret fields.

## Behavior

1. An entry is identified by `(scope, target, field, environment)`. Scope is `group` or `job`; environment is either a case-folded active environment name or absent for a shared entry. `FUNCTUALIZE_ENV`, then `ENVIRONMENT`, then `ENV` selects the environment; absent selection defaults to `DEV`. `base` addresses shared entries. Storage for shared entries retains the existing three-part spelling and associated data, so existing v2 ciphertext remains readable. Environment entries use a four-part spelling. Dots in targets are never parsed as field or environment separators.
2. Direct `put`, `inspect`, and `remove` name their target with `--group GROUP` and/or `--job JOB`, plus `--field FIELD`. At least one of `--group` or `--job` is required. The two compose:
   - `--group G` alone names group `G`: a secret-marked option of that group, or a secret-marked subject config field when `G` is a subject address. Scope `group`, target `G`.
   - `--group G --job J` names job `J` whose group is exactly `G`. Scope `job`; target is the job's registered name, which is `G.J`. For `func app deploy service` this is `--group app.deploy --job service`.
   - `--job J` alone names job `J` that is in no group. Scope `job`, target `J`.

   A `--job` value is a single job name and contains no dot. `--job app.deploy.service` is refused before any value is read, and the message suggests `--group app.deploy --job service`. `--job J` alone, when `J` exists only inside a group, is refused and names the `--group` to add. `--group G --job J`, when `G` has no job `J`, is refused as an unknown job in that group. Group and job segments use the normal canonical naming (`run_etl` reaches `run-etl`). The operator never types the combined job name, and the vault never splits a target back into parts. A subject address may be a group value. Eligible fields are secret-marked group options, job config fields, and subject config fields. An ordinary job function parameter is not eligible. Validation happens before a direct `put` accepts a value. Existing recovery semantics for removing an orphaned target remain available.
3. `put` writes only the active-environment entry. `remove` deletes only that exact identity, not an ancestor or shared fallback. `inspect` reports the winning exact identity and whether it is shared. `put`, `remove`, `inspect`, and `list` report the active environment and whether it was selected or defaulted. `list` identifies each entry's group, job, field, environment, origin, and freshness, spelled the way the flags are (`--group deploy.infra --job app --field api_token`).
4. For a group target, lookup tries the full address and then each dotted ancestor, first within the active environment and then within shared entries. A plain group has a single target in each tier. A job entry is looked up for exactly its group and job, active environment then shared; it never falls back to the same job name in an ancestor group, nor to the group's own option of the same field name. A missing entry falls through according to normal field precedence. A present but unreadable entry refuses resolution and never falls through to another entry or source.
5. Secret-marked group options, job config fields, and subject config fields resolve in this order: runtime override, explicit command-line value, vault, environment variable, config file, default. Ordinary function parameters remain invocation inputs. Runs use the local vault; only `vault sync` contacts remote providers.
6. `[[vault_secret]]` blocks name their target with `group` and/or `job` under the same rule as the flags (`group` alone, `group` with `job`, or `job` alone), and require `field` and `source`. A dotted `job` value is refused with the split `group` / `job` spelling to use. A declaration in `config.base.*` or an unslotted config file is shared; one in `config.<env>.*` belongs to that environment. Duplicate identities are rejected within an environment. `sync` processes shared and active-overlay declarations only and does not contact other overlays. Direct and provider-backed entries cannot silently replace one another. Inline provider annotations in ordinary config values remain invalid legacy syntax.
7. `list`, `inspect`, and error output never contain secret bytes, including when a key is missing or wrong. Existing old flat-key store refusal remains non-mutating and points to `vault clear` for recovery.

## Acceptance criteria

- With the same scope, target, and field, `prod`, `staging`, and shared entries remain distinct. A write with no selected environment lands in `dev` and reports the default.
- A `prod.apps.web` group lookup checks `prod.apps.web`, then `prod.apps`, then `prod` in `prod` before checking those targets in shared; it never reads a `staging` entry. `inspect` identifies the exact winner. `remove` under `prod` leaves shared and ancestor entries intact.
- A v2 shared entry decrypts without rewriting; a present but unreadable nearer entry stops resolution.
- `config.prod.*` and `config.staging.*` may declare the same scope, target, and field; a prod sync contacts only shared and prod sources and detects duplicates or origin conflicts in those identities.
- Through a canonical operation job, a secret-marked subject field resolves for the subject address used to invoke it. Group and job entries with otherwise identical names remain separate. Explicit CLI input outranks vault, while vault outranks environment input for both group and config fields.
- Given `JOB_GROUP = "deploy.infra"` and a job function `app` with a secret-marked `api_token` config field, `func deploy infra app` resolves the entry written by `--group deploy.infra --job app --field api_token`. `--job app` alone and `--job deploy.infra.app` are both refused with that composed spelling, before any value is read. A `--group deploy.infra --field api_token` entry is a different identity and cannot substitute for the job field.
- `--group deploy --field token`, `--group deploy --job token --field token`, and `--job deploy --field token` are three distinct entries. A top-level job `myjob` is addressed by `--job myjob` alone.
- A `[[vault_secret]]` block with `group = "deploy.infra"` and `job = "app"` syncs into the same identity a direct `--group deploy.infra --job app` write uses; a block with a dotted `job` value is refused.
- A job entry stored before this change under the registered name `deploy.infra.app` is the same entry as `--group deploy.infra --job app` and decrypts without rewriting.
- CLI and public API tests cover metadata redaction and prove jobs do not contact a provider. Documentation and the Unreleased changelog describe the behavior.

## Boundaries

In scope: the `--group` / `--job` target grammar and the matching `[[vault_secret]]` keys; local vault entry handling in `put`, `inspect`, `remove`, `list`, `sync`, `status`, `init`, and `clear` where affected; group, job, and subject resolution; corresponding documentation. Out of scope: share/redeem, FuncCloud delivery, plaintext reveal/export, old-format migration, a vault-specific environment flag, separate vaults per environment, and Rise's mapping from its environment declaration to Functualize's active environment name.
