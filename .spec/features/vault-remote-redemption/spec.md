# Vault Remote Redemption — `func vault share` / `func vault redeem`

Status: specified, not implemented. Chain item 2 of the FuncCloud
vault-redeem-journey (funccloud repo, private). Shape Intent published on
Confluence (SD space) per this repo's workflow; this branch spec atomizes
it for implementation. **Everything cross-repo is frozen**: wire + crypto
contracts live in the funccloud repo (`.spec/features/vault-redeem-journey/
contracts.md`, frozen v1, 2026-09-25) — this feature consumes them, never
redefines them.

## Objective

An ordinary functualize user can hand a working environment to anyone else,
accountlessly, from the CLI:

```
sender$   func vault share --labels demo --expires 1h --redemptions 1 --set KEY=VAL…
          → prints https://<origin>/s/<id>#k1.<key>
receiver$ func vault redeem <link>
          → summary (labels, redemptions, expiry) + export lines
receiver$ func vault redeem <link> --into-vault [scope]
          → imports into the local secrets vault (ADR-016 store)
```

The receiver needs **no FuncCloud account and no functualize config beyond
defaults**; the default origin is the public FuncCloud vault, configurable
for any conforming host (self-hosters, tests).

## Assertions (assertion-level, per house style; PASS/GAP vs master)

A1 **Vendored client reproduces the locked vectors.** A port of the
funccloud Python implementation lives in this repo (`functualize/` package),
reshaped to house layering; the cross-language vector file is copied
**verbatim** and the test suite must reproduce every vector byte-identically
and pass all 37 fail-closed cases (tamper/expiry/label/name/kind/mode/
version/wrong-key/wrong-recipient). *GAP today: no remote-vault code here.*

A2 **No new dependencies.** `cryptography>=42` (already core, ADR-016) +
stdlib `urllib` only. *PASS by construction if held at review.*

A3 **Layering.** The client and verbs' behavior live in the delivery-neutral
seam (`app/vault.py` pattern — extend it or a sibling `app/vault_remote.py`);
`_cli` mounts stay thin (`_cli/vault_cmd.py` grows `share`/`redeem`
commands; `_cli` imports public API only; `_config` untouched except store
writes via existing seams). Import-linter contracts unchanged. *GAP.*

A4 **`func vault share`** (sender): builds an EnvelopeV1 fragment-mode
bundle from explicit `--set NAME=VALUE` pairs and/or selected local-vault
items; client-generates the 32-hex share id (AAD requires it); sends the
frozen create request with `User-Agent: functualize/<version>`; prints the
link **with the fragment** and a one-line possession warning (per the
link-key study: "anyone with this complete link can redeem it"). Values
never appear in logs. *GAP.*

A5 **`func vault redeem`** (receiver): parses `<origin>/s/<id>#k1.…`;
warns on origin mismatch vs configured default (threat T5.1); POSTs redeem;
verifies the envelope's `metadata.share_id` echo; decrypts locally
(single indistinguishable failure class); prints labels/redemptions/expiry
summary + `export NAME=VALUE` lines (values visible on the receiver's own
terminal by design — that is the point); `--into-vault` imports items
through the local-vault seam as a named scope; `--dotenv PATH` opt-in
writes the file 0600. Default materialization = export lines only (safest;
nothing persisted). *GAP.*

A6 **Burn semantics at CLI level.** Redeeming a spent/expired share exits
nonzero with a closed message; previewing via `func vault show <link>`
(optional verb) hits meta and **never** redeems. *GAP.*

A7 **CI-safety + live opt-in.** Unit/CLI tests run against a mock origin
(local http.server implementing contracts v1 — reuses the vendored client
as the server's seal path); a live-origin tier runs only when
`FUNC_VAULT_ORIGIN` + `FUNC_VAULT_LIVE=1` are set, skipped silently in CI.
*GAP.*

A8 **`func vault` top-level surface.** Today vault lives under
`func builtin vault` (ADR-016 mount). The journey's success transcript
invokes `func vault …`. Ship a top-level `vault` group aliasing the same
app (two-line mount in `_cli/main`), keeping `func builtin vault` working.
Decision recorded here; reversible UX, not a contract. *GAP.*

A9 **Fragment hygiene.** Fragment parsed from argv, held in memory, never
logged by functualize's own logging/event surfaces (test: run redeem under
the testing fixtures with event capture; grep captures for `k1.` — zero).
*GAP.*

## Non-goals (this feature)

Account-bound sync, team wrapping, passphrase `k2.` mode, custom vault
servers beyond honoring origin configuration, anything capability/policy —
all later chain items in the funccloud roadmap.

## Evidence on merge

Durable half to `STATUS.md` per house workflow; the funccloud-side journey
closes on their eval harness (chain item 3), which pins this submodule
pointer — the cross-repo witness lives there, not here.
