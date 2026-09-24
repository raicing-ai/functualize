# Vault Remote Redemption — contracts

Consumed (frozen, owned by funccloud repo — do not redefine here):
- Wire API v1 + client obligations (UA, no-cache, fragment-never-transits):
  funccloud `.spec/features/vault-redeem-journey/contracts.md`.
- EnvelopeV1 crypto + canonical-JSON rules + locked vectors
  (blob d5eca81…): funccloud `packages/vault-crypto/README.md` and
  `vectors/vectors.json`. The vectors file is copied VERBATIM into
  `tests/vault_remote/vectors.json`; byte drift = contract breach.

Produced (this repo):
- `app.vault_remote`: `share(...) -> ShareLink`, `redeem(link) ->
  RedeemedBundle(items, labels, expires_at)`, `import_to_vault(bundle,
  scope)`; single error type `VaultRedeemError` (closed, no oracles).
- CLI surface: `func vault share [--set N=V]… [--from-vault SEL]…
  [--labels L]… [--expires 1h] [--redemptions 1] [--origin URL]`;
  `func vault redeem <link> [--into-vault SCOPE] [--dotenv PATH]`;
  exit codes follow house ExitCode conventions.
- Origin resolution order: `--origin` > `FUNC_VAULT_ORIGIN` >
  config layer (`vault.remote_origin`) > default
  `https://funccloud-vault.raicing-ai.workers.dev`.


## Revision 2026-10-31 (contracts)
- `share`: `--group G [--job J] --field F [--env E]` (repeatable) selects local entries; `--set N=V` unchanged.
- Item wire name for vault entries: JSON `{"g":..,"j":..,"f":..,"e":..}` (see spec R1). The wire
  contract only sees an opaque string.
- `redeem <link> [-y|--yes] [--only SEL]... [--replace] [--print-only] [--dotenv PATH]`.
  Replaces `--into-vault SCOPE`: vault import is the default, `--scope` is removed.
- Exit codes: no TTY without `-y`/`--only`/`--print-only` -> usage error, before any network call.
- Seam: `plan_import(bundle, app) -> ImportPlan(rows)`, `apply_import(plan, selected, replace)
  -> ImportReport`; rows carry identity, environment, status (`storable|exists|no_match|no_address`)
  and a reason. No row carries a value in its repr.
