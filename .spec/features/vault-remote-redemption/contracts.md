# Vault Remote Redemption — contracts

Consumed (frozen, owned by funccloud repo — do not redefine here):
- Wire API v1 + client obligations (UA, no-cache, fragment-never-transits):
  funccloud `.spec/features/vault-redeem-journey/contracts.md`.
- EnvelopeV1 crypto + canonical-JSON rules + locked vectors
  (blob d5eca81…): funccloud `packages/vault-crypto/README.md` and
  `vectors/vectors.json`. The vectors file is copied VERBATIM into
  `tests/vault_remote/vectors.json`; byte drift = contract breach.
- Item `name` and share `labels` are sender-chosen strings in that contract;
  this repo's conventions for them (below) need no contract change.

Consumed (this repo, local vault):
- `functualize._primitives.vault_identity.VaultIdentity` — `encode()` /
  `decode()`; `base` folds to the shared slot (spec A15).
- `functualize.app.vault` — `resolve_vault_identity`, `vault_put`,
  `VaultEntryExistsError`; added by this feature (T21): a **private**
  `_read_value(app, identity, *, cwd) -> str` used only by
  `app.vault_handoff` (decision 2026-11-01: no public plaintext read), and the
  public `vault_supersede_synced(app, identity, value, *, cwd) -> VaultMutationReport`,
  `vault_require_key(app, *, cwd) -> None` (raises `VaultKeySourceError`).
- `functualize._config.vault.SecretsVault.supersede(key, value, *,
  encryption_key)` — one transaction: any-origin row → `DIRECT`, annotation /
  provider / `synced_at` cleared.
- `functualize._config.resolved_field` — `env_name_for`, `group_env_name_for`.
- `functualize._config.vault_key_resolver` — `resolve_vault_key` → `KeyLookup`,
  `describe_key_failure`.

Produced (this repo):
- `app.vault_remote` (crypto + wire only, vendored): `seal_envelope`,
  `open_envelope`, `parse_link`, `create_share`, `fetch_share_meta` (no burn),
  `redeem_link`, `resolve_origin`, `parse_expiry`; one error type
  `VaultRedeemError(reason, message)` (closed, no oracles).
- `app.vault_handoff` (new — local materialisation policy):
  - `parse_selector(text) -> Selector` (raises `VaultPathError` with the
    `vault put` reason codes);
  - `shareable_entries(app, *, cwd) -> list[ShareCandidate]` (identity,
    shareable or the reason not, `synced from` annotation) — the picker's rows;
  - `select_for_share(app, selectors | ALL, *, cwd) -> list[ShareCandidate]`;
  - `share(app, selectors, *, labels, ttl, redemptions, origin, cwd) ->
    ShareReport` (adds `env:<active>`);
  - `check_before_redeem(app, link, *, mode, cwd) -> ShareMeta` — every
    pre-burn refusal;
  - `plan_import(bundle, app, *, cwd) -> ImportPlan(rows)`; a row carries
    identity, status (`storable|exists|synced|no_match|malformed`), the
    `synced from` annotation when there is one, and a reason — never a value,
    in any field or repr;
  - `apply_import(app, plan, selected, *, replace, cwd) -> ImportReport` (names
    only);
  - `export_name(identity) -> str` (`JOB_FIELD` / `SCOPE__FIELD`).
- Conventions on the wire:
  - vault-entry item: `name = VaultIdentity.encode()`, `kind = "secret"`;
  - every share carries the label `env:<active env>` (counts toward the
    ≤ 8 × 64-char label limit).
- CLI surface:
  - `func builtin vault share [--entry SEL]… | --all  [--labels L]
    [--expires 1h] [--redemptions 1] [--origin URL]`; neither selector on a
    TTY opens the picker. `SEL` is `key=value[,key=value…]` with keys
    `group`, `job`, `field` (spec A4). The environment is `FUNCTUALIZE_ENV`,
    never a flag. No `--group`/`--job`/`--field`, no `--set`, no
    `--from-vault`.
  - `func builtin vault redeem <link> [-y|--yes] [--only SEL]… [--replace]
    [--print-only] [--dotenv PATH] [--origin URL]`.
  - `func builtin vault show <link>`.
  - No top-level `func vault` (removed, spec A8).
  - Pre-burn refusals (no project, environment mismatch, no TTY without
    `-y`/`--only`/`--print-only`, key not FOUND in store mode) are
    `ExitCode.USAGE` or the key refusal's own code, and send at most the
    non-burning meta read.
- Origin resolution: `--origin` > `FUNC_VAULT_ORIGIN` > default
  `https://funccloud-vault.raicing-ai.workers.dev`. A `vault.remote_origin`
  settings key is **deferred**: it is not declared, so #130 reports it as
  unknown (`app/vault_remote.py:643`).
