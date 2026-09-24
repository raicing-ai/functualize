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
