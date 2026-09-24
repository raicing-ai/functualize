# Vault Remote Redemption — tasks

- [ ] A1  port crypto core (envelope + canonical) → app/vault_remote.py
- [ ] A2  copy vectors verbatim; port the 37 fail-closed cases; green
- [ ] A3  port http client (UA, timeout, origin check, id-echo, errors)
- [ ] A4  mock origin server fixture speaking contracts v1
- [ ] A5  CLI-integration test: share→redeem round-trip (mock origin)
- [ ] B1  app seam: share()/redeem()/import_to_vault(); extend the
          no-value-leaves reflection test to new report types
- [ ] B2  `func vault share` (explicit --set + local-vault item picker)
- [ ] B3  `func vault redeem` (+ --into-vault, --dotenv 0600, export lines)
- [ ] B4  optional `func vault show <link>` (meta-only, never burns)
- [ ] B5  top-level `func vault` alias mount; `func builtin vault` intact
- [ ] B6  spent/expired/tampered CLI failure tests; hygiene grep (A9)
- [ ] C1  live tier behind FUNC_VAULT_LIVE; one manual live run recorded
- [ ] C2  docs: vault_cmd docstrings + docs/ page stub; STATUS entry
Merge blocker: A2 vectors PASS. Cross-repo witness: funccloud eval.
