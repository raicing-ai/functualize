# Vault Remote Redemption — plan

Wave A — vendored client (A1–A3):
port `packages/vault-crypto/py/{envelope,vault_client}.py` (funccloud repo,
branch vault-journey-d1-probe) into `app/vault_remote.py` house-shaped:
- crypto half: pure functions, no I/O; vectors file copied verbatim to
  `tests/vault_remote/vectors.json`; test module mirrors the funccloud
  fail-closed suite (37 cases).
- http half: `_request()` with UA + timeout; origin validation; the
  share-id echo check; errors → one `VaultRedeemError`.
- mock origin: `tests/vault_remote/mock_vault.py` (http.server) speaking
  contracts v1 — create/meta/redeem/ciphertext, used by all CLI tests.

Wave B — verbs (A4–A6, A8, A9):
- `app` seam: `share(items, labels, ttl, redemptions, origin) -> link`,
  `redeem(link) -> RedeemedBundle`, `import_to_vault(bundle, scope)`;
  metadata-only report types (extend the existing "no value leaves"
  reflection test to the new dataclasses).
- `_cli/vault_cmd.py`: `share`, `redeem` (+ optional `show`) commands;
  `_cli/main` top-level `vault` alias mount (A8).
- fixtures/tests: share→redeem round-trip via mock origin; spent-share and
  tampered-envelope failures; hygiene grep (A9).

Wave C — live tier + handoff:
- `FUNC_VAULT_LIVE=1` tier against the real origin (guarded, skipped in
  CI); run once manually against funccloud-vault.raicing-ai.workers.dev;
  hand the branch to PR; funccloud bumps pointer after merge and runs
  their journey eval (chain item 3).

Gates: house spec-workflow hooks + agents on this branch; every wave ends
green on the full test suite; the vectors test is the one non-negotiable
merge blocker (cross-repo contract).
